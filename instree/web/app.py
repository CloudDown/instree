"""FastAPI — historique et gestion des scans."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from instree.config import config_for_api, load_settings, save_config
from instree.session import connect
from instree.store import get_scan, has_scans, init_db, list_scans, scan_neighbors
from instree.web.runner import cancel_scan, job_status, reset_job, start_scan

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"


class ScanRequest(BaseModel):
    init: bool = False


class ConfigUpdate(BaseModel):
    username: str = ""
    n: str | int = 100
    watch_n: str | int = "MAX"
    page_sleep: float = 0.6
    page_size: int = 200
    host: str = "127.0.0.1"
    port: int = 8765
    autostart_on_boot: bool = False
    schedule_times: list[str] = ["08:00", "20:00"]
    schedule_interval_minutes: int = 0
    sessionid: str = ""
    ds_user_id: str = ""


_session_cache: dict | None = None


def clear_session_cache() -> None:
    global _session_cache
    _session_cache = None


def _session_info() -> dict:
    global _session_cache
    if _session_cache is not None:
        return _session_cache
    settings = load_settings()
    try:
        ig, source, _note = connect()
        from instree.session import session_user

        target = settings.username or session_user(ig)
        _session_cache = {
            "ok": True,
            "source": source,
            "username": target,
            "note": _note,
        }
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
    for name in ("app.js", "style.css", "i18n.js"):
        f = STATIC_DIR / name
        if f.is_file():
            latest = max(latest, f.stat().st_mtime)
    locales = STATIC_DIR / "locales"
    if locales.is_dir():
        for f in locales.glob("*.json"):
            latest = max(latest, f.stat().st_mtime)
    return str(int(latest))


def create_app() -> FastAPI:
    init_db()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from instree.autostart import remove_legacy_systemd
        from instree.web.interval_scheduler import (
            start_interval_scheduler,
            stop_interval_scheduler,
        )

        remove_legacy_systemd()
        start_interval_scheduler()
        yield
        stop_interval_scheduler()

    app = FastAPI(title="Instree", docs_url=None, redoc_url=None, lifespan=lifespan)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/changes", status_code=307)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        return templates.TemplateResponse(
            request, "settings.html", {"v": _asset_version(), "page": "settings"}
        )

    @app.get("/changes", response_class=HTMLResponse)
    async def changes_page(request: Request):
        return templates.TemplateResponse(
            request, "changes.html", {"v": _asset_version(), "page": "changes"}
        )

    @app.get("/actions", include_in_schema=False)
    async def actions_redirect():
        return RedirectResponse("/changes", status_code=307)

    @app.get("/api/status")
    async def api_status():
        session = _session_info()
        return {
            "session": session,
            "config": config_for_api(),
            "has_scans": has_scans(),
            "job": job_status(),
        }

    @app.get("/api/config")
    async def api_config_get():
        return config_for_api()

    @app.put("/api/config")
    async def api_config_put(body: ConfigUpdate):
        if job_status().get("state") == "running":
            raise HTTPException(409, "Impossible de modifier la config pendant un scan")
        try:
            save_config(
                username=body.username,
                n=body.n,
                watch_n=body.watch_n,
                page_sleep=body.page_sleep,
                page_size=body.page_size,
                host=body.host,
                port=body.port,
                autostart_on_boot=body.autostart_on_boot,
                schedule_times=body.schedule_times,
                schedule_interval_minutes=body.schedule_interval_minutes,
                sessionid=body.sessionid or None,
                ds_user_id=body.ds_user_id or None,
            )
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e)) from e
        clear_session_cache()
        return {"ok": True, "config": config_for_api()}

    @app.post("/api/session/test")
    async def api_session_test():
        clear_session_cache()
        return _session_info()

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
        sub_adds = [c for c in data["changes"] if c["op"] == "sub_add"]
        sub_removes = [c for c in data["changes"] if c["op"] == "sub_remove"]

        person_groups: dict[str, dict] = {}
        for c in sub_adds + sub_removes:
            subject = c["subject_username"] or ""
            if subject not in person_groups:
                person_groups[subject] = {
                    "username": subject,
                    "old_count": None,
                    "new_count": None,
                    "adds": [],
                    "removes": [],
                }
            if c["op"] == "sub_add":
                person_groups[subject]["adds"].append(c)
            else:
                person_groups[subject]["removes"].append(c)

        old_count = None
        if adds or removes:
            old_count = scan["following_count"] - len(adds) + len(removes)
        return {
            **data,
            "adds": adds,
            "removes": removes,
            "counts": [],
            "sub_adds": sub_adds,
            "sub_removes": sub_removes,
            "person_changes": list(person_groups.values()),
            "old_count": old_count,
            "has_changes": bool(data["changes"]),
        }

    @app.get("/api/scans/{scan_id}/neighbors")
    async def api_neighbors(scan_id: int):
        return scan_neighbors(scan_id)

    @app.post("/api/scan")
    async def api_scan_start(body: ScanRequest):
        clear_session_cache()
        try:
            start_scan(init=body.init)
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

    @app.post("/api/scan/cancel")
    async def api_scan_cancel():
        if not cancel_scan():
            raise HTTPException(409, "Aucun scan en cours")
        return job_status()

    return app
