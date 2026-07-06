"""Chemins et chargement instree.toml."""
from dataclasses import dataclass
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "instree.toml"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "watch.db"
JOURNAL_DIR = DATA_DIR / "journal"


@dataclass(frozen=True)
class Settings:
    sessionid: str = ""
    ds_user_id: str = ""
    username: str = ""
    n: int = 0
    page_sleep: float = 0.6
    host: str = "127.0.0.1"
    port: int = 8765


def load_settings(path: Path | None = None) -> Settings:
    path = path or CONFIG_PATH
    if not path.is_file():
        return Settings()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    ig = raw.get("instagram", {})
    scan = raw.get("scan", {})
    web = raw.get("web", {})
    return Settings(
        sessionid=str(ig.get("sessionid", "")).strip(),
        ds_user_id=str(ig.get("ds_user_id", "")).strip(),
        username=str(scan.get("username", "")).strip().lstrip("@"),
        n=max(0, int(scan.get("n", 0))),
        page_sleep=float(scan.get("page_sleep", 0.6)),
        host=str(web.get("host", "127.0.0.1")),
        port=int(web.get("port", 8765)),
    )
