"""Export / import d'une session Instree (ZIP)."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from instree.config import (
    _format_local_toml,
    _format_profile_settings_toml,
    _read_toml,
    _validate_profile_id,
    _write_text,
    create_profile,
    parse_interval_minutes,
    parse_limit,
    parse_max_person_following,
    parse_page_size,
    profile_data_path,
    profile_local_path,
    profile_settings_path,
    set_active_profile,
)

EXPORT_FORMAT = "instree-session"
EXPORT_VERSION = 1

_SAFE_FILENAME = re.compile(r"[^a-zA-Z0-9._-]+")


def _slug(label: str) -> str:
    s = _SAFE_FILENAME.sub("-", (label or "session").strip())[:40].strip("-")
    return s or "session"


def export_profile_zip(profile_id: str, *, include_secrets: bool = False) -> tuple[bytes, str]:
    """Construit un ZIP mémoire. Retourne (bytes, filename)."""
    pid = _validate_profile_id(profile_id)
    settings_path = profile_settings_path(pid)
    if not settings_path.is_file():
        raise ValueError(f"session introuvable : {pid}")

    raw = _read_toml(settings_path)
    profile_meta = raw.get("profile") if isinstance(raw.get("profile"), dict) else {}
    label = str(profile_meta.get("label") or pid).strip() or pid

    data_dir = profile_data_path(pid)
    db = data_dir / "watch.db"
    journal = data_dir / "journal"
    local_path = profile_local_path(pid)

    manifest = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "label": label,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "includes_secrets": bool(include_secrets),
        "has_database": db.is_file(),
        "has_journal": journal.is_dir() and any(journal.iterdir()),
    }

    buf = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.write(settings_path, arcname="settings.toml")
        if include_secrets and local_path.is_file():
            zf.write(local_path, arcname="local.toml")
        if db.is_file():
            zf.write(db, arcname="watch.db")
        if journal.is_dir():
            for path in sorted(journal.rglob("*")):
                if path.is_file():
                    zf.write(path, arcname=f"journal/{path.relative_to(journal).as_posix()}")

    buf.seek(0)
    data = buf.read()
    buf.close()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    filename = f"instree-{_slug(label)}-{stamp}.zip"
    return data, filename


def _read_zip_member(zf: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        return zf.read(name)
    except KeyError:
        return None


def import_profile_zip(
    raw: bytes,
    *,
    label: str | None = None,
    activate: bool = True,
) -> dict:
    """Importe un ZIP en nouvelle session. Retourne {id, label, includes_secrets}."""
    if not raw:
        raise ValueError("fichier vide")

    with tempfile.TemporaryDirectory(prefix="instree-import-") as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "pack.zip"
        zip_path.write_bytes(raw)

        try:
            zf = zipfile.ZipFile(zip_path, "r")
        except zipfile.BadZipFile as e:
            raise ValueError("fichier ZIP invalide") from e

        with zf:
            names = set(zf.namelist())
            if "manifest.json" not in names and "settings.toml" not in names:
                raise ValueError("archive Instree invalide (manifest / settings manquants)")

            manifest_raw = _read_zip_member(zf, "manifest.json")
            manifest = {}
            if manifest_raw:
                try:
                    manifest = json.loads(manifest_raw.decode("utf-8"))
                except json.JSONDecodeError as e:
                    raise ValueError("manifest.json invalide") from e
                if manifest.get("format") not in (None, EXPORT_FORMAT):
                    raise ValueError(f"format inconnu : {manifest.get('format')!r}")

            settings_bytes = _read_zip_member(zf, "settings.toml")
            if not settings_bytes:
                raise ValueError("settings.toml manquant dans l'archive")

            extract_root = tmp_path / "extract"
            extract_root.mkdir()
            # Extraire seulement des chemins sûrs (pas de ..)
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if not name or name.endswith("/"):
                    continue
                if name.startswith("/") or ".." in name.split("/"):
                    raise ValueError(f"chemin ZIP dangereux : {name}")
                if name not in (
                    "manifest.json",
                    "settings.toml",
                    "local.toml",
                    "watch.db",
                ) and not name.startswith("journal/"):
                    continue
                dest = extract_root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)

        settings_file = extract_root / "settings.toml"
        imported = _read_toml(settings_file)
        profile_meta = (
            imported.get("profile") if isinstance(imported.get("profile"), dict) else {}
        )
        scan = imported.get("scan") if isinstance(imported.get("scan"), dict) else {}
        schedule = (
            imported.get("schedule") if isinstance(imported.get("schedule"), dict) else {}
        )
        final_label = (label or "").strip() or str(
            profile_meta.get("label") or "Session importée"
        ).strip()

        pid = create_profile(label=final_label)
        _write_text(
            profile_settings_path(pid),
            _format_profile_settings_toml(
                label=final_label,
                username=str(scan.get("username", "")).strip().lstrip("@"),
                n=parse_limit(scan.get("n", 100)),
                watch_n=parse_limit(scan.get("watch_n", 0)),
                max_person_following=parse_max_person_following(
                    scan.get("max_person_following", 2000)
                ),
                page_sleep=float(scan.get("page_sleep", 0.6)),
                page_size=parse_page_size(scan.get("page_size", 200)),
                schedule_interval_minutes=parse_interval_minutes(
                    schedule.get("interval_minutes", 0)
                ),
            ),
        )

        local_src = extract_root / "local.toml"
        includes_secrets = False
        if local_src.is_file():
            shutil.copy2(local_src, profile_local_path(pid))
            includes_secrets = True
        else:
            _write_text(
                profile_local_path(pid),
                _format_local_toml(sessionid="", ds_user_id=""),
            )

        data_dir = profile_data_path(pid)
        data_dir.mkdir(parents=True, exist_ok=True)
        db_src = extract_root / "watch.db"
        if db_src.is_file():
            shutil.copy2(db_src, data_dir / "watch.db")

        journal_src = extract_root / "journal"
        journal_dest = data_dir / "journal"
        journal_dest.mkdir(parents=True, exist_ok=True)
        if journal_src.is_dir():
            for path in journal_src.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(journal_src)
                    target = journal_dest / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)

        if activate:
            set_active_profile(pid)

        return {
            "id": pid,
            "label": final_label,
            "includes_secrets": includes_secrets,
            "has_database": (data_dir / "watch.db").is_file(),
        }
