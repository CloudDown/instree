"""Chemins, profils multi-session et chargement config."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import tomllib
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path

_CORE_DIR = Path(__file__).resolve().parent
_PACKAGE_DIR = _CORE_DIR.parent  # instree/
_REPO_CANDIDATE = _PACKAGE_DIR.parent

_DEFAULT_PROFILE = "default"
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SAFE_USER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_TRUTHY = frozenset({"1", "true", "yes"})

_current_user_id: ContextVar[str | None] = ContextVar("instree_user_id", default=None)
_web_mode = False
_migrated_roots: set[str] = set()


def project_root() -> Path:
    """Racine du dépôt."""
    cwd = Path.cwd()
    candidates = [cwd]
    if _REPO_CANDIDATE != cwd:
        candidates.append(_REPO_CANDIDATE)
    for candidate in candidates:
        if (candidate / "var" / "desktop" / "config" / "instree.toml").is_file():
            return candidate
        if (candidate / "config" / "instree.toml").is_file():
            return candidate
        if (candidate / "instree.toml").is_file():
            return candidate
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return cwd if (cwd / "pyproject.toml").is_file() else _REPO_CANDIDATE


def desktop_root() -> Path:
    """Racine données Desktop : `var/desktop/` (nouveau) ou racine repo (legacy)."""
    root = project_root()
    new = (root / "var" / "desktop").resolve()
    legacy_cfg = root / "config" / "instree.toml"
    if (new / "config" / "instree.toml").is_file():
        return new
    if legacy_cfg.is_file():
        return root
    return new


def desktop_data_root() -> Path:
    if is_web_mode():
        return user_home() / "data"
    base = desktop_root()
    return base / "data" if base.name == "desktop" else base / "data"


def default_web_home() -> Path:
    """Données Instree Web : `var/web/` (nouveau) ou `serveur/` (legacy)."""
    root = project_root()
    preferred = (root / "var" / "web").resolve()
    legacy = (root / "serveur").resolve()
    if preferred.is_dir():
        return preferred
    if legacy.is_dir():
        return legacy
    return preferred


def is_web_mode() -> bool:
    env = os.environ.get("INSTREE_WEB", "").strip().lower()
    # Alias historique
    if not env:
        env = os.environ.get("INSTREE_PUBLIC", "").strip().lower()
    return _web_mode or env in _TRUTHY


def runtime_root() -> Path:
    """Racine des données : INSTREE_HOME (Web) ou dépôt (Desktop)."""
    env = os.environ.get("INSTREE_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if is_web_mode():
        return default_web_home()
    return project_root()


def enable_web_mode(home: Path | str | None = None) -> Path:
    """Active Instree Web : auth + données isolées sous var/web/ (ou INSTREE_HOME)."""
    global _web_mode
    _web_mode = True
    os.environ["INSTREE_WEB"] = "1"
    if home is not None:
        root = Path(home).expanduser().resolve()
    elif os.environ.get("INSTREE_HOME", "").strip():
        root = Path(os.environ["INSTREE_HOME"]).expanduser().resolve()
    else:
        root = default_web_home()
    os.environ["INSTREE_HOME"] = str(root)
    bootstrap_web_home(root)
    return root


def current_user_id() -> str | None:
    return _current_user_id.get()


def set_current_user(user_id: str | None) -> Token:
    return _current_user_id.set(user_id)


def reset_current_user(token: Token) -> None:
    _current_user_id.reset(token)


def _validate_user_id(user_id: str) -> str:
    uid = str(user_id or "").strip().lower()
    if not _SAFE_USER.match(uid):
        raise ValueError(f"id utilisateur invalide : {user_id!r}")
    return uid


def user_home(user_id: str | None = None) -> Path:
    uid = _validate_user_id(user_id or current_user_id() or "")
    return runtime_root() / "users" / uid


def ensure_user_home(user_id: str) -> Path:
    """Crée l'arbre config/data d'un compte public."""
    home = user_home(user_id)
    (home / "config" / "profiles").mkdir(parents=True, exist_ok=True)
    (home / "data" / "profiles").mkdir(parents=True, exist_ok=True)
    return home


def server_config_path() -> Path:
    """Config globale Instree Web (bind host/port)."""
    return runtime_root() / "instree.toml"


def secret_key_path() -> Path:
    return runtime_root() / "secret.key"


def master_password_hash_path() -> Path:
    """Hash PBKDF2 du mot de passe maître (connexion à n'importe quel compte)."""
    return runtime_root() / "master.key"


def accounts_db_path() -> Path:
    return runtime_root() / "accounts.db"


def bootstrap_web_home(root: Path | None = None) -> Path:
    """Crée var/web/ (ou INSTREE_HOME), instree.toml, secret.key si absents."""
    home = Path(root).resolve() if root else runtime_root()
    home.mkdir(parents=True, exist_ok=True)
    (home / "users").mkdir(parents=True, exist_ok=True)
    cfg = home / "instree.toml"
    if not cfg.is_file():
        _write_text(
            cfg,
            _format_server_toml(host="0.0.0.0", port=1488),
        )
    key = home / "secret.key"
    if not key.is_file():
        key.write_text(secrets.token_hex(32), encoding="utf-8")
        key.chmod(0o600)
    return home


def load_secret_key() -> str:
    path = secret_key_path()
    if not path.is_file():
        bootstrap_web_home()
    return secret_key_path().read_text(encoding="utf-8").strip()


def _format_server_toml(
    *, host: str, port: int, daily_hour: int = 2, timezone: str = "America/Montreal"
) -> str:
    return f"""# Instree Web — données runtime (hors git)
# Comptes : users/<id>/

[web]
host = {_toml_str(host)}
port = {port}

[schedule]
daily_hour = {daily_hour}
timezone = {_toml_str(timezone)}
"""


def load_server_schedule_settings() -> dict:
    """Planification serveur Web (scan quotidien, anti-spam)."""
    raw = _read_toml(server_config_path())
    schedule = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
    hour = int(schedule.get("daily_hour", 2))
    tz = str(schedule.get("timezone", "America/Montreal")).strip() or "America/Montreal"
    return {
        "daily_hour": max(0, min(23, hour)),
        "timezone": tz,
        "timezone_label": _schedule_timezone_label(tz),
        "manual_scans_disabled": True,
    }


def _schedule_timezone_label(timezone: str) -> str:
    labels = {
        "America/Montreal": "Montréal",
        "Europe/Paris": "Paris",
    }
    return labels.get(timezone, timezone.replace("_", " "))


def ensure_server_schedule(
    *,
    daily_hour: int = 2,
    timezone: str = "America/Montreal",
) -> None:
    """Crée ou met à jour [schedule] dans instree.toml (serveur Web)."""
    path = server_config_path()
    if path.is_file():
        host, port = load_server_web_settings()
    else:
        host, port = "0.0.0.0", 1488
    _write_text(
        path,
        _format_server_toml(
            host=host,
            port=port,
            daily_hour=daily_hour,
            timezone=timezone,
        ),
    )


def load_server_web_settings() -> tuple[str, int]:
    raw = _read_toml(server_config_path())
    web = raw.get("web") if isinstance(raw.get("web"), dict) else {}
    host = str(web.get("host", "0.0.0.0")).strip() or "0.0.0.0"
    port = int(web.get("port", 1488))
    return host, max(1, min(65535, port))


def config_dir() -> Path:
    if is_web_mode():
        return user_home() / "config"
    base = desktop_root()
    return base / "config" if base.name == "desktop" else base / "config"


def profiles_config_dir() -> Path:
    return config_dir() / "profiles"


def profiles_data_dir() -> Path:
    if is_web_mode():
        return user_home() / "data" / "profiles"
    return desktop_data_root() / "profiles"


def _resolve_config_path(name: str) -> Path:
    """Chemin dans config/, avec repli sur la racine (legacy local uniquement)."""
    new = config_dir() / name
    if is_web_mode():
        return new
    root = project_root()
    legacy = root / name
    if new.is_file():
        return new
    if legacy.is_file():
        return legacy
    return new


def _write_config_path(name: str) -> Path:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def main_config_path() -> Path:
    return _resolve_config_path("instree.toml")


def legacy_local_config_path() -> Path:
    return _resolve_config_path("instree.local.toml")


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_limit(n: int) -> str:
    return _toml_str("MAX") if n <= 0 else str(n)


_MAX_ALIASES = frozenset({"max", "tous", "all", "∞"})


def parse_limit(raw) -> int:
    """Convertit un nombre ou MAX → limite interne (0 = tous)."""
    if isinstance(raw, bool):
        raise ValueError("valeur invalide")
    if isinstance(raw, int):
        return max(0, raw)
    s = str(raw).strip().lower()
    if not s or s in _MAX_ALIASES or s == "0":
        return 0
    if s.isdigit():
        return int(s)
    raise ValueError(f"limite invalide : {raw!r} (utilise un nombre ou MAX)")


def _parse_bool(raw, *, default: bool = True) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def _normalize_ig_username(raw: str) -> str:
    return str(raw or "").strip().lstrip("@").lower()


def parse_watch_blacklist(raw) -> tuple[str, ...]:
    """Liste de @ à exclure de la phase watch (normalisée, unique)."""
    if raw is None:
        return ()
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        u = _normalize_ig_username(str(item))
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return tuple(out)


def _toml_str_list(items: list[str] | tuple[str, ...]) -> str:
    if not items:
        return "[]"
    return "[ " + ", ".join(_toml_str(x) for x in items) + " ]"


def _scan_behavior(scan: dict | None) -> dict[str, bool]:
    scan = scan if isinstance(scan, dict) else {}
    return {
        "watch_following": _parse_bool(scan.get("watch_following"), default=True),
        "refetch_mutuals": _parse_bool(scan.get("refetch_mutuals"), default=False),
        "skip_unchanged_profiles": _parse_bool(
            scan.get("skip_unchanged_profiles"), default=True
        ),
        "partial_fetch": _parse_bool(scan.get("partial_fetch"), default=True),
    }


def _scan_extras(scan: dict | None) -> dict:
    """Booléens d'analyse + blacklist watch."""
    scan = scan if isinstance(scan, dict) else {}
    return {
        **_scan_behavior(scan),
        "watch_blacklist": parse_watch_blacklist(scan.get("watch_blacklist")),
    }


def parse_page_size(raw) -> int:
    """Taille de page API friendships (Instagram peut renvoyer moins)."""
    if isinstance(raw, bool):
        raise ValueError("valeur invalide")
    n = int(raw) if not isinstance(raw, int) else raw
    return max(12, min(200, n))


def format_limit(n: int) -> str:
    """Affichage : 0 → MAX."""
    return "MAX" if n <= 0 else str(n)


def parse_max_person_following(raw) -> int:
    """Ancien plafond (ignoré au scan) — 0 / MAX = illimité."""
    return parse_limit(raw if raw is not None else 0)


def parse_interval_minutes(raw) -> int:
    """Intervalle de scan en minutes (0 = désactivé)."""
    if raw is None:
        return 0
    if isinstance(raw, bool):
        raise ValueError("valeur invalide")
    n = int(raw) if isinstance(raw, int) else int(str(raw).strip())
    return max(0, n)


def _validate_profile_id(profile_id: str) -> str:
    pid = str(profile_id or "").strip().lower()
    if not _SAFE_ID.match(pid):
        raise ValueError(f"id de session invalide : {profile_id!r}")
    return pid


def profile_config_dir(profile_id: str) -> Path:
    return profiles_config_dir() / _validate_profile_id(profile_id)


def profile_data_path(profile_id: str) -> Path:
    return profiles_data_dir() / _validate_profile_id(profile_id)


def profile_settings_path(profile_id: str) -> Path:
    return profile_config_dir(profile_id) / "settings.toml"


def profile_local_path(profile_id: str) -> Path:
    return profile_config_dir(profile_id) / "local.toml"


def local_config_path() -> Path:
    """Secrets du profil actif (compat API existante)."""
    ensure_profiles_migrated()
    return profile_local_path(active_profile_id())


def db_path() -> Path:
    ensure_profiles_migrated()
    return profile_data_path(active_profile_id()) / "watch.db"


def journal_dir() -> Path:
    ensure_profiles_migrated()
    return profile_data_path(active_profile_id()) / "journal"


@dataclass(frozen=True)
class Settings:
    sessionid: str = ""
    ds_user_id: str = ""
    username: str = ""
    n: int = 0  # 0 = MAX
    watch_n: int = 0
    max_person_following: int = 0
    page_sleep: float = 0.6
    page_size: int = 200
    host: str = "127.0.0.1"
    port: int = 1488
    autostart_on_boot: bool = False
    schedule_interval_minutes: int = 0
    watch_following: bool = True
    refetch_mutuals: bool = False
    skip_unchanged_profiles: bool = True
    partial_fetch: bool = True
    watch_blacklist: tuple[str, ...] = ()
    profile_id: str = _DEFAULT_PROFILE
    profile_label: str = "Session 1"


def _format_global_toml(
    *,
    host: str,
    port: int,
    autostart_on_boot: bool,
    active_profile: str,
) -> str:
    return f"""# Instree — configuration globale (éditable via l'interface web)
# Sessions : config/profiles/<id>/  (+ data/profiles/<id>/)

[web]
host = {_toml_str(host)}
port = {port}
autostart_on_boot = {"true" if autostart_on_boot else "false"}

[profiles]
active = {_toml_str(active_profile)}
"""


def _format_profile_settings_toml(
    *,
    label: str,
    username: str,
    n: int,
    watch_n: int,
    max_person_following: int,
    page_sleep: float,
    page_size: int,
    schedule_interval_minutes: int,
    watch_following: bool = True,
    refetch_mutuals: bool = False,
    skip_unchanged_profiles: bool = True,
    partial_fetch: bool = True,
    watch_blacklist: list[str] | tuple[str, ...] = (),
    ig_username: str = "",
) -> str:
    return f"""# Instree — paramètres de session (profil)
# Secrets : local.toml (gitignored)

[profile]
label = {_toml_str(label)}
ig_username = {_toml_str(ig_username.strip().lstrip("@"))}

[scan]
username = {_toml_str(username)}
n = {_toml_limit(n)}
watch_n = {_toml_limit(watch_n)}
max_person_following = {_toml_limit(max_person_following)}
page_sleep = {page_sleep}
page_size = {page_size}
watch_following = {"true" if watch_following else "false"}
refetch_mutuals = {"true" if refetch_mutuals else "false"}
skip_unchanged_profiles = {"true" if skip_unchanged_profiles else "false"}
partial_fetch = {"true" if partial_fetch else "false"}
watch_blacklist = {_toml_str_list(parse_watch_blacklist(watch_blacklist))}

[schedule]
interval_minutes = {schedule_interval_minutes}
"""


def _format_local_toml(*, sessionid: str, ds_user_id: str) -> str:
    return f"""# Secrets Instagram — ne pas committer

[instagram]
sessionid = {_toml_str(sessionid)}
ds_user_id = {_toml_str(ds_user_id)}
"""


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _ensure_profile_dirs(profile_id: str) -> None:
    pid = _validate_profile_id(profile_id)
    profile_config_dir(pid).mkdir(parents=True, exist_ok=True)
    profile_data_path(pid).mkdir(parents=True, exist_ok=True)
    (profile_data_path(pid) / "journal").mkdir(parents=True, exist_ok=True)


def _next_session_label(existing_labels: set[str]) -> str:
    n = 1
    while True:
        label = f"Session {n}"
        if label.lower() not in {x.lower() for x in existing_labels}:
            return label
        n += 1


def _new_profile_id() -> str:
    return f"s-{uuid.uuid4().hex[:8]}"


def ensure_profiles_migrated() -> None:
    """Crée le profil default et migre l'ancienne config mono-session si besoin."""
    if is_web_mode() and not current_user_id():
        return

    root_key = str(config_dir().resolve())
    if root_key in _migrated_roots:
        return
    _migrated_roots.add(root_key)

    main_path = main_config_path()
    main = _read_toml(main_path) if main_path.is_file() else {}
    profiles_section = main.get("profiles") if isinstance(main.get("profiles"), dict) else {}
    active = str(profiles_section.get("active") or "").strip()

    profiles_config_dir().mkdir(parents=True, exist_ok=True)
    profiles_data_dir().mkdir(parents=True, exist_ok=True)

    existing_ids = [
        p.name
        for p in profiles_config_dir().iterdir()
        if p.is_dir() and _SAFE_ID.match(p.name)
    ]

    if not existing_ids:
        pid = _DEFAULT_PROFILE
        _ensure_profile_dirs(pid)
        web = main.get("web") if isinstance(main.get("web"), dict) else {}
        scan = main.get("scan") if isinstance(main.get("scan"), dict) else {}
        schedule = main.get("schedule") if isinstance(main.get("schedule"), dict) else {}

        _write_text(
            profile_settings_path(pid),
            _format_profile_settings_toml(
                label="Session 1",
                username=str(scan.get("username", "")).strip().lstrip("@"),
                n=parse_limit(scan.get("n", 0)),
                watch_n=parse_limit(scan.get("watch_n", 0)),
                max_person_following=parse_max_person_following(
                    scan.get("max_person_following", 0)
                ),
                page_sleep=float(scan.get("page_sleep", 0.6)),
                page_size=parse_page_size(scan.get("page_size", 200)),
                schedule_interval_minutes=parse_interval_minutes(
                    schedule.get("interval_minutes", 0)
                ),
                **_scan_extras(scan),
            ),
        )

        if not is_web_mode():
            legacy_local = legacy_local_config_path()
            if legacy_local.is_file():
                dest = profile_local_path(pid)
                if not dest.is_file():
                    shutil.copy2(legacy_local, dest)

            legacy_db = project_root() / "data" / "watch.db"
            dest_db = profile_data_path(pid) / "watch.db"
            if legacy_db.is_file() and not dest_db.is_file():
                shutil.move(str(legacy_db), str(dest_db))

            legacy_journal = project_root() / "data" / "journal"
            dest_journal = profile_data_path(pid) / "journal"
            if (
                legacy_journal.is_dir()
                and legacy_journal.resolve() != dest_journal.resolve()
            ):
                dest_journal.mkdir(parents=True, exist_ok=True)
                for item in legacy_journal.iterdir():
                    target = dest_journal / item.name
                    if not target.exists():
                        shutil.move(str(item), str(target))

        host = "127.0.0.1" if is_web_mode() else str(web.get("host", "127.0.0.1"))
        port = int(web.get("port", 1488)) if not is_web_mode() else 1488
        autostart = False if is_web_mode() else bool(web.get("autostart_on_boot", False))
        _write_text(
            main_path,
            _format_global_toml(
                host=host.strip() or "127.0.0.1",
                port=max(1, min(65535, port)),
                autostart_on_boot=autostart,
                active_profile=pid,
            ),
        )
        _write_text(profile_local_path(pid), _format_local_toml(sessionid="", ds_user_id=""))
        return

    if not active or active not in existing_ids:
        active = existing_ids[0]
        web = main.get("web") if isinstance(main.get("web"), dict) else {}
        _write_text(
            main_path,
            _format_global_toml(
                host=str(web.get("host", "127.0.0.1")),
                port=int(web.get("port", 1488)),
                autostart_on_boot=bool(web.get("autostart_on_boot", False)),
                active_profile=active,
            ),
        )

    for pid in existing_ids:
        _ensure_profile_dirs(pid)
        settings_path = profile_settings_path(pid)
        if not settings_path.is_file():
            _write_text(
                settings_path,
                _format_profile_settings_toml(
                    label=f"Session {pid}",
                    username="",
                    n=0,
                    watch_n=0,
                    max_person_following=0,
                    page_sleep=0.6,
                    page_size=200,
                    schedule_interval_minutes=0,
                    **_scan_extras({}),
                ),
            )


def active_profile_id() -> str:
    ensure_profiles_migrated()
    main = _read_toml(main_config_path())
    profiles = main.get("profiles") if isinstance(main.get("profiles"), dict) else {}
    active = str(profiles.get("active") or _DEFAULT_PROFILE).strip()
    try:
        return _validate_profile_id(active)
    except ValueError:
        return _DEFAULT_PROFILE


def _profile_label(profile_id: str) -> str:
    raw = _read_toml(profile_settings_path(profile_id))
    profile = raw.get("profile") if isinstance(raw.get("profile"), dict) else {}
    label = str(profile.get("label") or "").strip()
    return label or profile_id


def list_profiles() -> list[dict]:
    ensure_profiles_migrated()
    active = active_profile_id()
    out: list[dict] = []
    for path in sorted(profiles_config_dir().iterdir(), key=lambda p: p.name):
        if not path.is_dir() or not _SAFE_ID.match(path.name):
            continue
        pid = path.name
        local = _read_toml(profile_local_path(pid))
        ig = local.get("instagram") if isinstance(local.get("instagram"), dict) else {}
        settings = _read_toml(profile_settings_path(pid))
        scan = settings.get("scan") if isinstance(settings.get("scan"), dict) else {}
        profile = settings.get("profile") if isinstance(settings.get("profile"), dict) else {}
        ig_username = str(profile.get("ig_username") or scan.get("username") or "").strip().lstrip("@")
        out.append(
            {
                "id": pid,
                "label": _profile_label(pid),
                "active": pid == active,
                "username": str(scan.get("username") or "").strip().lstrip("@"),
                "ig_username": ig_username,
                "sessionid_set": bool(str(ig.get("sessionid") or "").strip()),
            }
        )
    return out


def profile_ig_username(profile_id: str | None = None) -> str:
    """@ Instagram mémorisé pour une session (affichage UI, sans réseau)."""
    ensure_profiles_migrated()
    pid = _validate_profile_id(profile_id or active_profile_id())
    raw = _read_toml(profile_settings_path(pid))
    meta = raw.get("profile") if isinstance(raw.get("profile"), dict) else {}
    return str(meta.get("ig_username") or "").strip().lstrip("@")


def remember_profile_ig_username(username: str, profile_id: str | None = None) -> None:
    """Mémorise le @ Instagram connecté pour l'affichage de la session."""
    ensure_profiles_migrated()
    pid = _validate_profile_id(profile_id or active_profile_id())
    settings_path = profile_settings_path(pid)
    if not settings_path.is_file():
        return
    raw = _read_toml(settings_path)
    profile = raw.get("profile") if isinstance(raw.get("profile"), dict) else {}
    scan = raw.get("scan") if isinstance(raw.get("scan"), dict) else {}
    schedule = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
    _write_text(
        settings_path,
        _format_profile_settings_toml(
            label=str(profile.get("label") or pid).strip() or pid,
            ig_username=str(username or "").strip().lstrip("@"),
            username=str(scan.get("username", "")).strip().lstrip("@"),
            n=parse_limit(scan.get("n", 0)),
            watch_n=parse_limit(scan.get("watch_n", 0)),
            max_person_following=parse_max_person_following(
                scan.get("max_person_following", 0)
            ),
            page_sleep=float(scan.get("page_sleep", 0.6)),
            page_size=parse_page_size(scan.get("page_size", 200)),
            schedule_interval_minutes=parse_interval_minutes(
                schedule.get("interval_minutes", 0)
            ),
            **_scan_extras(scan),
        ),
    )


def create_profile(*, label: str = "") -> str:
    ensure_profiles_migrated()
    existing = list_profiles()
    labels = {p["label"] for p in existing}
    final_label = (label or "").strip() or _next_session_label(labels)
    pid = _new_profile_id()
    _ensure_profile_dirs(pid)
    _write_text(
        profile_settings_path(pid),
        _format_profile_settings_toml(
            label=final_label,
            username="",
            n=0,
            watch_n=0,
            max_person_following=0,
            page_sleep=0.6,
            page_size=200,
            schedule_interval_minutes=0,
        ),
    )
    _write_text(profile_local_path(pid), _format_local_toml(sessionid="", ds_user_id=""))
    return pid


def set_active_profile(profile_id: str) -> None:
    ensure_profiles_migrated()
    pid = _validate_profile_id(profile_id)
    if not profile_settings_path(pid).is_file():
        raise ValueError(f"session introuvable : {pid}")
    existing = load_settings()
    host = "127.0.0.1" if is_web_mode() else existing.host
    port = 1488 if is_web_mode() else existing.port
    autostart = False if is_web_mode() else existing.autostart_on_boot
    _write_text(
        main_config_path(),
        _format_global_toml(
            host=host,
            port=port,
            autostart_on_boot=autostart,
            active_profile=pid,
        ),
    )


def rename_profile(profile_id: str, label: str) -> None:
    ensure_profiles_migrated()
    pid = _validate_profile_id(profile_id)
    settings_path = profile_settings_path(pid)
    if not settings_path.is_file():
        raise ValueError(f"session introuvable : {pid}")
    raw = _read_toml(settings_path)
    profile = raw.get("profile") if isinstance(raw.get("profile"), dict) else {}
    scan = raw.get("scan") if isinstance(raw.get("scan"), dict) else {}
    schedule = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
    new_label = (label or "").strip() or pid
    _write_text(
        settings_path,
        _format_profile_settings_toml(
            label=new_label,
            ig_username=str(profile.get("ig_username") or "").strip().lstrip("@"),
            username=str(scan.get("username", "")).strip().lstrip("@"),
            n=parse_limit(scan.get("n", 0)),
            watch_n=parse_limit(scan.get("watch_n", 0)),
            max_person_following=parse_max_person_following(
                scan.get("max_person_following", 0)
            ),
            page_sleep=float(scan.get("page_sleep", 0.6)),
            page_size=parse_page_size(scan.get("page_size", 200)),
            schedule_interval_minutes=parse_interval_minutes(
                schedule.get("interval_minutes", 0)
            ),
            **_scan_extras(scan),
        ),
    )


def delete_profile(profile_id: str) -> None:
    ensure_profiles_migrated()
    pid = _validate_profile_id(profile_id)
    profiles = list_profiles()
    if len(profiles) <= 1:
        raise ValueError("impossible de supprimer la dernière session")
    if pid == active_profile_id():
        raise ValueError("bascule vers une autre session avant de supprimer celle-ci")
    if not any(p["id"] == pid for p in profiles):
        raise ValueError(f"session introuvable : {pid}")
    cfg = profile_config_dir(pid)
    data = profile_data_path(pid)
    if cfg.is_dir():
        shutil.rmtree(cfg)
    if data.is_dir():
        shutil.rmtree(data)


def load_settings() -> Settings:
    ensure_profiles_migrated()
    pid = active_profile_id()
    main = _read_toml(main_config_path())
    web = main.get("web") if isinstance(main.get("web"), dict) else {}
    if is_web_mode():
        host, port = load_server_web_settings()
        autostart = False
    else:
        host = str(web.get("host", "127.0.0.1"))
        port = int(web.get("port", 1488))
        autostart = bool(web.get("autostart_on_boot", False))
    profile_raw = _read_toml(profile_settings_path(pid))
    local = _read_toml(profile_local_path(pid))

    # Compat : si secrets encore dans l'ancien local global
    if not local and not is_web_mode():
        legacy = _read_toml(legacy_local_config_path())
        if legacy:
            local = legacy

    ig = local.get("instagram") if isinstance(local.get("instagram"), dict) else {}
    scan = profile_raw.get("scan") if isinstance(profile_raw.get("scan"), dict) else {}
    schedule = (
        profile_raw.get("schedule")
        if isinstance(profile_raw.get("schedule"), dict)
        else {}
    )
    profile_meta = (
        profile_raw.get("profile") if isinstance(profile_raw.get("profile"), dict) else {}
    )

    return Settings(
        sessionid=str(ig.get("sessionid", "")).strip(),
        ds_user_id=str(ig.get("ds_user_id", "")).strip(),
        username=str(scan.get("username", "")).strip().lstrip("@"),
        n=parse_limit(scan.get("n", 0)),
        watch_n=parse_limit(scan.get("watch_n", 0)),
        max_person_following=parse_max_person_following(
            scan.get("max_person_following", 0)
        ),
        page_sleep=float(scan.get("page_sleep", 0.6)),
        page_size=parse_page_size(scan.get("page_size", 200)),
        host=host,
        port=port,
        autostart_on_boot=autostart,
        schedule_interval_minutes=parse_interval_minutes(
            schedule.get("interval_minutes", 0)
        ),
        **_scan_extras(scan),
        profile_id=pid,
        profile_label=str(profile_meta.get("label") or pid).strip() or pid,
    )


def config_for_api() -> dict:
    """Config éditable pour l'interface web (tokens du compte courant)."""
    s = load_settings()
    data = {
        "profile_id": s.profile_id,
        "profile_label": s.profile_label,
        "username": s.username,
        "n": format_limit(s.n),
        "watch_n": format_limit(s.watch_n),
        "max_person_following": format_limit(s.max_person_following),
        "page_sleep": s.page_sleep,
        "page_size": s.page_size,
        "host": s.host,
        "port": s.port,
        "autostart_on_boot": s.autostart_on_boot,
        "schedule_interval_minutes": s.schedule_interval_minutes,
        "watch_following": s.watch_following,
        "refetch_mutuals": s.refetch_mutuals,
        "skip_unchanged_profiles": s.skip_unchanged_profiles,
        "partial_fetch": s.partial_fetch,
        "watch_blacklist": list(s.watch_blacklist),
        "sessionid": s.sessionid,
        "ds_user_id": s.ds_user_id,
        "sessionid_set": bool(s.sessionid),
        "ds_user_id_set": bool(s.ds_user_id),
        "web_mode": is_web_mode(),
    }
    return data


def save_config(
    *,
    username: str = "",
    n: int | str = 0,
    watch_n: int | str = 0,
    max_person_following: int | str = 0,
    page_sleep: float = 0.6,
    page_size: int = 200,
    host: str = "127.0.0.1",
    port: int = 1488,
    autostart_on_boot: bool | None = None,
    schedule_interval_minutes: int | None = None,
    sessionid: str | None = None,
    ds_user_id: str | None = None,
    profile_label: str | None = None,
    watch_following: bool | None = None,
    refetch_mutuals: bool | None = None,
    skip_unchanged_profiles: bool | None = None,
    partial_fetch: bool | None = None,
) -> None:
    """Écrit le profil actif + la config web globale."""
    ensure_profiles_migrated()
    existing = load_settings()
    pid = existing.profile_id
    interval = (
        parse_interval_minutes(schedule_interval_minutes)
        if schedule_interval_minutes is not None
        else existing.schedule_interval_minutes
    )
    autostart = (
        False
        if is_web_mode()
        else (
            bool(autostart_on_boot)
            if autostart_on_boot is not None
            else existing.autostart_on_boot
        )
    )
    label = (
        profile_label.strip()
        if profile_label is not None and profile_label.strip()
        else existing.profile_label
    )

    new_sessionid = existing.sessionid
    new_ds_user_id = existing.ds_user_id
    if sessionid is not None and sessionid.strip():
        new_sessionid = sessionid.strip()
    if ds_user_id is not None and ds_user_id.strip():
        new_ds_user_id = ds_user_id.strip()

    # En Web : host/port viennent de var/web/instree.toml (inchangé ici).
    write_host = "127.0.0.1" if is_web_mode() else (host.strip() or "127.0.0.1")
    write_port = 1488 if is_web_mode() else max(1, min(65535, int(port)))
    _write_text(
        main_config_path(),
        _format_global_toml(
            host=write_host,
            port=write_port,
            autostart_on_boot=autostart,
            active_profile=pid,
        ),
    )
    existing_raw = _read_toml(profile_settings_path(pid))
    existing_profile = (
        existing_raw.get("profile")
        if isinstance(existing_raw.get("profile"), dict)
        else {}
    )
    _write_text(
        profile_settings_path(pid),
        _format_profile_settings_toml(
            label=label,
            ig_username=str(existing_profile.get("ig_username") or "").strip().lstrip(
                "@"
            ),
            username=username.strip().lstrip("@"),
            n=parse_limit(n),
            watch_n=parse_limit(watch_n),
            max_person_following=parse_max_person_following(max_person_following),
            page_sleep=max(0.0, float(page_sleep)),
            page_size=parse_page_size(page_size),
            schedule_interval_minutes=interval,
            watch_following=(
                watch_following
                if watch_following is not None
                else existing.watch_following
            ),
            refetch_mutuals=(
                refetch_mutuals
                if refetch_mutuals is not None
                else existing.refetch_mutuals
            ),
            skip_unchanged_profiles=(
                skip_unchanged_profiles
                if skip_unchanged_profiles is not None
                else existing.skip_unchanged_profiles
            ),
            partial_fetch=(
                partial_fetch if partial_fetch is not None else existing.partial_fetch
            ),
            watch_blacklist=existing.watch_blacklist,
        ),
    )

    if new_sessionid or new_ds_user_id or sessionid is not None:
        save_session_credentials(new_sessionid, new_ds_user_id)

    if not is_web_mode():
        from instree.desktop.autostart import sync_autostart

        try:
            sync_autostart(autostart)
        except (OSError, RuntimeError) as e:
            raise RuntimeError(f"démarrage automatique : {e}") from e


def save_watch_blacklist(usernames: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Met à jour uniquement la blacklist watch du profil actif."""
    ensure_profiles_migrated()
    existing = load_settings()
    blacklist = parse_watch_blacklist(usernames)
    pid = existing.profile_id
    existing_raw = _read_toml(profile_settings_path(pid))
    existing_profile = (
        existing_raw.get("profile")
        if isinstance(existing_raw.get("profile"), dict)
        else {}
    )
    _write_text(
        profile_settings_path(pid),
        _format_profile_settings_toml(
            label=existing.profile_label,
            ig_username=str(existing_profile.get("ig_username") or "").strip().lstrip(
                "@"
            ),
            username=existing.username,
            n=existing.n,
            watch_n=existing.watch_n,
            max_person_following=existing.max_person_following,
            page_sleep=existing.page_sleep,
            page_size=existing.page_size,
            schedule_interval_minutes=existing.schedule_interval_minutes,
            watch_following=existing.watch_following,
            refetch_mutuals=existing.refetch_mutuals,
            skip_unchanged_profiles=existing.skip_unchanged_profiles,
            partial_fetch=existing.partial_fetch,
            watch_blacklist=blacklist,
        ),
    )
    return blacklist


def save_session_credentials(sessionid: str, ds_user_id: str = "") -> None:
    """Enregistre la session Instagram du profil actif (gitignored)."""
    ensure_profiles_migrated()
    _write_text(
        profile_local_path(active_profile_id()),
        _format_local_toml(
            sessionid=sessionid.strip(),
            ds_user_id=ds_user_id.strip(),
        ),
    )
