"""FastAPI — historique et gestion des scans."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from instree.config import config_for_api, load_settings, save_config
from instree.session import connect
from instree.store import get_scan, has_scans, init_db, list_scans, scan_neighbors
from instree.web.runner import job_status, reset_job, start_scan

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"


class ScanRequest(BaseModel):
    init: bool = False
    full: bool = False


class ConfigUpdate(BaseModel):
    username: str = ""
    n: int = 100
    watch_n: int = 0
    page_sleep: float = 0.6
    host: str = "127.0.0.1"
    port: int = 8765
    schedule_times: list[str] = ["08:00", "20:00"]
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

    @app.get("/actions", response_class=HTMLResponse)
    async def actions_page(request: Request):
        return templates.TemplateResponse(
            request, "actions.html", {"v": _asset_version(), "page": "actions"}
        )

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
                host=body.host,
                port=body.port,
                schedule_times=body.schedule_times,
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

    @app.post("/api/schedule/install")
    async def api_schedule_install():
        from instree.schedule import install_systemd

        settings = load_settings()
        try:
            unit_dir, root, exec_start = install_systemd(settings)
        except RuntimeError as e:
            raise HTTPException(400, str(e)) from e
        return {
            "ok": True,
            "unit_dir": str(unit_dir),
            "root": str(root),
            "exec_start": exec_start,
            "times": list(settings.schedule_times),
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
        sub_adds = [c for c in data["changes"] if c["op"] == "sub_add"]
        sub_removes = [c for c in data["changes"] if c["op"] == "sub_remove"]

        person_groups: dict[str, dict] = {}
        for c in sub_adds + sub_removes:
            subject = c["subject_username"] or ""
            if subject not in person_groups:
                count_info = next((x for x in counts if x["username"] == subject), None)
                person_groups[subject] = {
                    "username": subject,
                    "old_count": count_info["old_count"] if count_info else None,
                    "new_count": count_info["new_count"] if count_info else None,
                    "adds": [],
                    "removes": [],
                }
            if c["op"] == "sub_add":
                person_groups[subject]["adds"].append(c)
            else:
                person_groups[subject]["removes"].append(c)

        subjects_with_detail = set(person_groups)
        counts_fallback = [c for c in counts if c["username"] not in subjects_with_detail]

        old_count = None
        if adds or removes:
            old_count = scan["following_count"] - len(adds) + len(removes)
        return {
            **data,
            "adds": adds,
            "removes": removes,
            "counts": counts_fallback,
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
