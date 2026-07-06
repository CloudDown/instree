"""FastAPI — historique des scans."""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from instree.store import get_scan, init_db, list_scans, scan_neighbors

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="Instree", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html")

    @app.get("/api/scans")
    async def api_scans():
        return list_scans()

    @app.get("/api/scans/{scan_id}")
    async def api_scan(scan_id: int):
        data = get_scan(scan_id)
        if not data:
            raise HTTPException(404, "Scan introuvable")
        enriched = []
        for snap in data["snapshots"]:
            friend = snap["friend_username"]
            friend_changes = [c for c in data["changes"] if c["friend_username"] == friend]
            adds = [c for c in friend_changes if c["op"] == "add"]
            removes = [c for c in friend_changes if c["op"] == "remove"]
            old = None
            if adds or removes:
                old = snap["following_count"] - len(adds) + len(removes)
            enriched.append({
                **snap,
                "old_count": old,
                "adds": adds,
                "removes": removes,
            })
        return {
            **data,
            "snapshots_enriched": enriched,
            "has_changes": len(data["changes"]) > 0,
        }

    @app.get("/api/scans/{scan_id}/neighbors")
    async def api_neighbors(scan_id: int):
        return scan_neighbors(scan_id)

    return app
