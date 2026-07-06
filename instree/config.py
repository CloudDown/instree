"""Chemins et chargement instree.toml."""

from dataclasses import dataclass
from pathlib import Path
import tomllib

_PKG_DIR = Path(__file__).resolve().parent


def project_root() -> Path:
    """Racine du dépôt : cwd si instree.toml présent, sinon parent du package."""
    cwd = Path.cwd()
    if (cwd / "instree.toml").is_file():
        return cwd
    candidate = _PKG_DIR.parent
    if (candidate / "instree.toml").is_file():
        return candidate
    return cwd if (cwd / "pyproject.toml").is_file() else candidate


def main_config_path() -> Path:
    return project_root() / "instree.toml"


def local_config_path() -> Path:
    return project_root() / "instree.local.toml"


def db_path() -> Path:
    return project_root() / "data" / "watch.db"


def journal_dir() -> Path:
    return project_root() / "data" / "journal"


@dataclass(frozen=True)
class Settings:
    sessionid: str = ""
    ds_user_id: str = ""
    username: str = ""
    n: int = 100
    watch_n: int = 0
    page_sleep: float = 0.6
    host: str = "127.0.0.1"
    port: int = 8765
    schedule_times: tuple[str, ...] = ("08:00", "20:00")


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _parse_times(raw) -> tuple[str, ...]:
    if not raw:
        return ("08:00", "20:00")
    times = []
    for t in raw:
        part = str(t).strip()
        if not part:
            continue
        h, _, m = part.partition(":")
        if not h.isdigit() or not m.isdigit():
            continue
        times.append(f"{int(h):02d}:{int(m):02d}")
    return tuple(times) if times else ("08:00", "20:00")


def load_raw_config() -> dict:
    """Config fusionnée instree.toml + instree.local.toml."""
    main = _read_toml(main_config_path())
    local = _read_toml(local_config_path())
    merged: dict = {}
    for key in set(main) | set(local):
        section: dict = {}
        if isinstance(main.get(key), dict):
            section.update(main[key])
        if isinstance(local.get(key), dict):
            section.update(local[key])
        merged[key] = section
    return merged


def load_settings(path: Path | None = None) -> Settings:
    raw = load_raw_config() if path is None else _read_toml(path)

    ig = raw.get("instagram", {})
    scan = raw.get("scan", {})
    web = raw.get("web", {})
    schedule = raw.get("schedule", {})
    return Settings(
        sessionid=str(ig.get("sessionid", "")).strip(),
        ds_user_id=str(ig.get("ds_user_id", "")).strip(),
        username=str(scan.get("username", "")).strip().lstrip("@"),
        n=max(0, int(scan.get("n", 100))),
        watch_n=max(0, int(scan.get("watch_n", 0))),
        page_sleep=float(scan.get("page_sleep", 0.6)),
        host=str(web.get("host", "127.0.0.1")),
        port=int(web.get("port", 8765)),
        schedule_times=_parse_times(schedule.get("times")),
    )


def config_for_api() -> dict:
    """Config éditable pour l'interface web (sans exposer les secrets)."""
    s = load_settings()
    return {
        "username": s.username,
        "n": s.n,
        "watch_n": s.watch_n,
        "page_sleep": s.page_sleep,
        "host": s.host,
        "port": s.port,
        "schedule_times": list(s.schedule_times),
        "sessionid_set": bool(s.sessionid),
        "ds_user_id_set": bool(s.ds_user_id),
        "paths": {
            "main": str(main_config_path()),
            "local": str(local_config_path()),
        },
    }


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _format_main_toml(
    *,
    username: str,
    n: int,
    watch_n: int,
    page_sleep: float,
    host: str,
    port: int,
    schedule_times: tuple[str, ...],
) -> str:
    times = ", ".join(_toml_str(t) for t in schedule_times)
    return f"""# Instree — configuration (éditable via l'interface web)
# Secrets : instree.local.toml (gitignored)

[instagram]
sessionid = ""
ds_user_id = ""

[scan]
username = {_toml_str(username)}
n = {n}
watch_n = {watch_n}
page_sleep = {page_sleep}

[web]
host = {_toml_str(host)}
port = {port}

[schedule]
times = [{times}]
"""


def _format_local_toml(*, sessionid: str, ds_user_id: str) -> str:
    return f"""# Secrets Instagram — ne pas committer
# Surcharge instree.toml

[instagram]
sessionid = {_toml_str(sessionid)}
ds_user_id = {_toml_str(ds_user_id)}
"""


def save_config(
    *,
    username: str = "",
    n: int = 100,
    watch_n: int = 0,
    page_sleep: float = 0.6,
    host: str = "127.0.0.1",
    port: int = 8765,
    schedule_times: list[str] | tuple[str, ...] | None = None,
    sessionid: str | None = None,
    ds_user_id: str | None = None,
) -> None:
    """Écrit instree.toml + instree.local.toml."""
    root = project_root()
    root.mkdir(parents=True, exist_ok=True)

    existing = load_settings()
    times = _parse_times(list(schedule_times or existing.schedule_times))

    new_sessionid = existing.sessionid
    new_ds_user_id = existing.ds_user_id
    if sessionid is not None and sessionid.strip():
        new_sessionid = sessionid.strip()
    if ds_user_id is not None and ds_user_id.strip():
        new_ds_user_id = ds_user_id.strip()

    main_path = main_config_path()
    local_path = local_config_path()

    main_path.write_text(
        _format_main_toml(
            username=username.strip().lstrip("@"),
            n=max(0, n),
            watch_n=max(0, watch_n),
            page_sleep=max(0.0, float(page_sleep)),
            host=host.strip() or "127.0.0.1",
            port=max(1, min(65535, int(port))),
            schedule_times=times,
        ),
        encoding="utf-8",
    )

    if new_sessionid or new_ds_user_id:
        local_path.write_text(
            _format_local_toml(sessionid=new_sessionid, ds_user_id=new_ds_user_id),
            encoding="utf-8",
        )

