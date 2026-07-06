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


def load_settings(path: Path | None = None) -> Settings:
    root = project_root()
    path = path or root / "instree.toml"
    local_path = root / "instree.local.toml"
    raw: dict = {}
    if path.is_file():
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if local_path.is_file():
        local = tomllib.loads(local_path.read_text(encoding="utf-8"))
        for section, values in local.items():
            raw.setdefault(section, {})
            if isinstance(values, dict):
                raw[section].update(values)

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
