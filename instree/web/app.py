"""FastAPI — historique et gestion des scans."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from instree.config import load_settings
from instree.session import connect
from instree.store import get_scan, has_scans, init_db, list_scans, scan_neighbors
from instree.web.runner import job_status, reset_job, start_scan

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"


class ScanRequest(BaseModel):
    init: bool = False
    full: bool = False


_session_cache: dict | None = None


def _session_info() -> dict:
    global _session_cache
    if _session_cache is not None:
        return _session_cache
    settings = load_settings()
    try:
        ig, source, _note = connect()
        from instree.session import session_user

        target = settings.username or session_user(ig)
        _session_cache = {"ok": True, "source": source, "username": target}
    except RuntimeError as e:
        _session_cache = {
            "ok": False,
            "source": None,
            "username": settings.username or None,
            "error": str(e),
        }
    return _session_cache


def _asset_version() -> str:
    """Empreinte basée sur la date de modification des fichiers statiques."""
    latest = 0.0
    for name in ("app.js", "style.css"):
        f = STATIC_DIR / name
        if f.is_file():
            latest = max(latest, f.stat().st_mtime)
    return str(int(latest))


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="Instree", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request, "index.html", {"v": _asset_version()}
        )

    @app.get("/api/status")
    async def api_status():
        settings = load_settings()
        session = _session_info()
        return {
            "session": session,
            "config": {
                "n": settings.n,
                "schedule_times": list(settings.schedule_times),
                "page_sleep": settings.page_sleep,
            },
            "has_scans": has_scans(),
            "job": job_status(),
        }

    @app.get("/api/scans")
    async def api_scans():
        return list_scans()

    @app.get("/api/scans/{scan_id}")
    async def api_scan(scan_id: int):
        data = get_scan(scan_id)
        if not data:
            raise HTTPException(404, "Scan introuvable")
        scan = data["scan"]
        adds = [c for c in data["changes"] if c["op"] == "add"]
        removes = [c for c in data["changes"] if c["op"] == "remove"]
        counts = [c for c in data["changes"] if c["op"] == "count"]
        old_count = None
        if adds or removes:
            old_count = scan["following_count"] - len(adds) + len(removes)
        return {
            **data,
            "adds": adds,
            "removes": removes,
            "counts": counts,
            "old_count": old_count,
            "has_changes": bool(data["changes"]),
        }

    @app.get("/api/scans/{scan_id}/neighbors")
    async def api_neighbors(scan_id: int):
        return scan_neighbors(scan_id)

    @app.post("/api/scan")
    async def api_scan_start(body: ScanRequest):
        global _session_cache
        _session_cache = None
        try:
            start_scan(init=body.init, full=body.full)
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
        return job_status()

    @app.get("/api/scan/job")
    async def api_scan_job():
        return job_status()

    @app.post("/api/scan/reset")
    async def api_scan_reset():
        reset_job()
        return job_status()

    return app
