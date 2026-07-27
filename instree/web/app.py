"""FastAPI — historique et gestion des scans."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from instree.web.accounts import authenticate, get_pending_baseline, register_account
from instree.core.config import (
    config_for_api,
    create_profile,
    current_user_id,
    delete_profile,
    is_web_mode,
    list_profiles,
    load_server_schedule_settings,
    load_settings,
    profile_ig_username,
    remember_profile_ig_username,
    rename_profile,
    save_config,
    set_active_profile,
)
from instree.core.session import connect
from instree.core.store import (
    get_changes_search_index,
    get_graph_data,
    get_scan,
    init_db,
    list_scans,
    scan_neighbors,
    scan_resume_info,
)
from instree.core.transfer import export_profile_zip, import_profile_zip
from instree.web.auth import (
    WebAuthMiddleware,
    install_session_middleware,
    login_user,
    logout_user,
    session_user,
)
from instree.web.runner import cancel_scan, job_status, reset_job, start_scan
from instree.web.security import (
    allow_register,
    AuthRateLimitMiddleware,
    SecurityHeadersMiddleware,
)

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"


class ScanRequest(BaseModel):
    init: bool = False


class ConfigUpdate(BaseModel):
    username: str = ""
    n: str | int = "MAX"
    watch_n: str | int = "MAX"
    max_person_following: str | int = "MAX"
    page_sleep: float = 0.6
    page_size: int = 200
    host: str = "127.0.0.1"
    port: int = 1488
    autostart_on_boot: bool = False
    schedule_interval_minutes: int = 0
    sessionid: str = ""
    ds_user_id: str = ""
    profile_label: str = ""
    watch_following: bool = True
    refetch_mutuals: bool = False
    skip_unchanged_profiles: bool = True
    partial_fetch: bool = True


class ProfileCreate(BaseModel):
    label: str = ""


class ProfileActivate(BaseModel):
    id: str


class ProfileRename(BaseModel):
    label: str


class AuthBody(BaseModel):
    username: str
    password: str


_session_cache: dict[str, dict] = {}


def _cache_key() -> str:
    return current_user_id() or "local"


def clear_session_cache() -> None:
    _session_cache.pop(_cache_key(), None)


def _session_info(*, verify: bool = False) -> dict:
    """État session pour l'UI.

    Par défaut : lecture locale uniquement (instantané).
    verify=True : login Instagram (+ cookies navigateur si besoin).
    """
    key = _cache_key()
    if not verify and key in _session_cache:
        return _session_cache[key]
    settings = load_settings()
    local_label = f"config/profiles/{settings.profile_id}/local.toml"

    if not verify:
        if settings.sessionid:
            username = (
                profile_ig_username(settings.profile_id)
                or settings.username
                or None
            )
            _session_cache[key] = {
                "ok": True,
                "source": local_label,
                "username": username,
                "note": None,
            }
        else:
            _session_cache[key] = {
                "ok": False,
                "source": None,
                "username": settings.username or None,
                "error": (
                    "Pas de session configurée — colle sessionid / user id, "
                    "ou utilise « Tester la connexion »"
                ),
            }
        return _session_cache[key]

    try:
        ig, source, _note = connect()
        from instree.core.session import session_user as ig_session_user

        target = settings.username or ig_session_user(ig)
        if target:
            try:
                remember_profile_ig_username(target)
            except (OSError, ValueError):
                pass
        _session_cache[key] = {
            "ok": True,
            "source": source,
            "username": target,
            "note": _note,
        }
    except RuntimeError as e:
        _session_cache[key] = {
            "ok": False,
            "source": None,
            "username": settings.username or None,
            "error": str(e),
        }
    return _session_cache[key]


def _asset_version() -> str:
    """Empreinte basée sur la date de modification des fichiers statiques."""
    latest = 0.0
    for name in ("app.js", "style.css", "i18n.js", "graph.js"):
        f = STATIC_DIR / name
        if f.is_file():
            latest = max(latest, f.stat().st_mtime)
    locales = STATIC_DIR / "locales"
    if locales.is_dir():
        for f in locales.glob("*.json"):
            latest = max(latest, f.stat().st_mtime)
    return str(int(latest))


def _page_ctx(request: Request, page: str) -> dict:
    """Contexte template commun. auth_user n'est renseigné qu'en mode public connecté."""
    user = None
    if is_web_mode():
        user = getattr(request.state, "user", None) or session_user(request)
    return {
        "v": _asset_version(),
        "page": page,
        "auth_user": user,
        "web_mode": is_web_mode(),
        "allow_register": allow_register() if is_web_mode() else True,
    }


def create_app() -> FastAPI:
    # Local : une seule base. Public : init au premier request authentifié.
    if not is_web_mode():
        init_db()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from instree.desktop.autostart import remove_legacy_systemd
        from instree.web.interval_scheduler import (
            start_interval_scheduler,
            stop_interval_scheduler,
        )
        from instree.web.web_scheduler import start_web_scheduler, stop_web_scheduler

        if not is_web_mode():
            remove_legacy_systemd()
        start_interval_scheduler()
        if is_web_mode():
            start_web_scheduler()
        yield
        if is_web_mode():
            stop_web_scheduler()
        stop_interval_scheduler()

    app = FastAPI(title="Instree", docs_url=None, redoc_url=None, lifespan=lifespan)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    if is_web_mode():
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        app.add_middleware(SecurityHeadersMiddleware)
        app.add_middleware(AuthRateLimitMiddleware)
        app.add_middleware(
            ProxyHeadersMiddleware,
            trusted_hosts=["127.0.0.1", "::1", "localhost"],
        )
        app.add_middleware(WebAuthMiddleware)
        install_session_middleware(app)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/changes", status_code=307)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if not is_web_mode():
            return RedirectResponse("/changes", status_code=307)
        if session_user(request):
            return RedirectResponse("/changes", status_code=307)
        return templates.TemplateResponse(
            request, "login.html", _page_ctx(request, "login")
        )

    @app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request):
        if not is_web_mode():
            return RedirectResponse("/changes", status_code=307)
        if not allow_register():
            return RedirectResponse("/login", status_code=307)
        if session_user(request):
            return RedirectResponse("/changes", status_code=307)
        return templates.TemplateResponse(
            request, "register.html", _page_ctx(request, "register")
        )

    @app.post("/api/auth/register")
    async def api_auth_register(request: Request, body: AuthBody):
        if not is_web_mode():
            raise HTTPException(404, "Indisponible en mode local")
        if not allow_register():
            raise HTTPException(403, "Inscription désactivée")
        try:
            account = register_account(body.username, body.password)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        login_user(request, account.id, account.username)
        from instree.core.config import set_current_user

        token = set_current_user(account.id)
        try:
            init_db()
        finally:
            from instree.core.config import reset_current_user

            reset_current_user(token)
        return {"ok": True, "user": {"id": account.id, "username": account.username}}

    @app.post("/api/auth/login")
    async def api_auth_login(request: Request, body: AuthBody):
        if not is_web_mode():
            raise HTTPException(404, "Indisponible en mode local")
        account = authenticate(body.username, body.password)
        if not account:
            raise HTTPException(401, "Identifiants incorrects")
        login_user(request, account.id, account.username)
        return {"ok": True, "user": {"id": account.id, "username": account.username}}

    @app.post("/api/auth/logout")
    async def api_auth_logout(request: Request):
        logout_user(request)
        return {"ok": True}

    @app.get("/api/auth/me")
    async def api_auth_me(request: Request):
        user = session_user(request)
        if not user:
            raise HTTPException(401, "Authentification requise")
        return {"ok": True, "user": user, "web_mode": is_web_mode()}

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        if is_web_mode():
            init_db()
        return templates.TemplateResponse(
            request, "settings.html", _page_ctx(request, "settings")
        )

    @app.get("/changes", response_class=HTMLResponse)
    async def changes_page(request: Request):
        if is_web_mode():
            init_db()
        return templates.TemplateResponse(
            request, "changes.html", _page_ctx(request, "changes")
        )

    @app.get("/graph", response_class=HTMLResponse)
    async def graph_page(request: Request):
        if is_web_mode():
            init_db()
        return templates.TemplateResponse(
            request, "graph.html", _page_ctx(request, "graph")
        )

    @app.get("/help", response_class=HTMLResponse)
    async def help_page(request: Request):
        if is_web_mode():
            init_db()
        return templates.TemplateResponse(
            request, "help.html", _page_ctx(request, "help")
        )

    @app.get("/actions", include_in_schema=False)
    async def actions_redirect():
        return RedirectResponse("/changes", status_code=307)

    @app.get("/api/status")
    async def api_status(request: Request):
        if is_web_mode():
            init_db()
        session = _session_info()
        user = getattr(request.state, "user", None)
        payload = {
            "session": session,
            "config": config_for_api(),
            "job": job_status(),
            "profiles": list_profiles(),
            "web_mode": is_web_mode(),
            "auth_user": user,
            "scan_resume": scan_resume_info(),
        }
        if is_web_mode():
            uid = current_user_id()
            payload["scan_schedule"] = load_server_schedule_settings()
            payload["pending_baseline"] = bool(uid and get_pending_baseline(uid))
        return payload

    @app.get("/api/profiles")
    async def api_profiles_list():
        return {"active": load_settings().profile_id, "profiles": list_profiles()}

    @app.post("/api/profiles")
    async def api_profiles_create(body: ProfileCreate):
        if job_status().get("state") in ("running", "stopping"):
            raise HTTPException(409, "Impossible pendant un scan")
        try:
            # Ne pas activer tout de suite : chaque session a sa propre base ;
            # basculer viderait l'historique affiché (scans de la session courante).
            pid = create_profile(label=body.label)
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e)) from e
        return {
            "ok": True,
            "id": pid,
            "profiles": list_profiles(),
            "config": config_for_api(),
            "session": _session_info(),
        }

    @app.put("/api/profiles/active")
    async def api_profiles_activate(body: ProfileActivate):
        if job_status().get("state") in ("running", "stopping"):
            raise HTTPException(409, "Impossible pendant un scan")
        try:
            set_active_profile(body.id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        clear_session_cache()
        init_db()
        return {
            "ok": True,
            "profiles": list_profiles(),
            "config": config_for_api(),
            "session": _session_info(),
        }

    @app.patch("/api/profiles/{profile_id}")
    async def api_profiles_rename(profile_id: str, body: ProfileRename):
        try:
            rename_profile(profile_id, body.label)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "profiles": list_profiles(), "config": config_for_api()}

    @app.delete("/api/profiles/{profile_id}")
    async def api_profiles_delete(profile_id: str):
        if job_status().get("state") in ("running", "stopping"):
            raise HTTPException(409, "Impossible pendant un scan")
        try:
            delete_profile(profile_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "profiles": list_profiles()}

    @app.get("/api/profiles/{profile_id}/export")
    async def api_profiles_export(
        profile_id: str, secrets: bool = False
    ):
        if job_status().get("state") in ("running", "stopping"):
            raise HTTPException(409, "Impossible pendant un scan")
        try:
            data, filename = export_profile_zip(
                profile_id, include_secrets=secrets
            )
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
        return Response(
            content=data,
            media_type="application/zip",
            headers=headers,
        )

    @app.post("/api/profiles/import")
    async def api_profiles_import(
        file: UploadFile = File(...),
        label: str = Form(""),
        activate: bool = Form(True),
    ):
        if job_status().get("state") in ("running", "stopping"):
            raise HTTPException(409, "Impossible pendant un scan")
        raw = await file.read()
        try:
            result = import_profile_zip(
                raw, label=label or None, activate=bool(activate)
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        clear_session_cache()
        init_db()
        return {
            "ok": True,
            **result,
            "profiles": list_profiles(),
            "config": config_for_api(),
            "session": _session_info(),
        }

    @app.get("/api/config")
    async def api_config_get():
        return config_for_api()

    @app.put("/api/config")
    async def api_config_put(body: ConfigUpdate):
        if job_status().get("state") in ("running", "stopping"):
            raise HTTPException(409, "Impossible de modifier la config pendant un scan")
        try:
            save_config(
                username=body.username,
                n=body.n,
                watch_n=body.watch_n,
                max_person_following=body.max_person_following,
                page_sleep=body.page_sleep,
                page_size=body.page_size,
                host=body.host,
                port=body.port,
                autostart_on_boot=body.autostart_on_boot,
                schedule_interval_minutes=body.schedule_interval_minutes,
                sessionid=body.sessionid or None,
                ds_user_id=body.ds_user_id or None,
                profile_label=body.profile_label or None,
                watch_following=body.watch_following,
                refetch_mutuals=body.refetch_mutuals,
                skip_unchanged_profiles=body.skip_unchanged_profiles,
                partial_fetch=body.partial_fetch,
            )
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e)) from e
        clear_session_cache()
        if is_web_mode():
            from instree.web.web_scheduler import try_start_pending_baseline

            uid = current_user_id()
            if uid:
                try_start_pending_baseline(uid)
        return {"ok": True, "config": config_for_api()}

    @app.post("/api/session/test")
    async def api_session_test():
        clear_session_cache()
        return _session_info(verify=True)

    @app.get("/api/scans")
    async def api_scans():
        return list_scans()

    @app.delete("/api/scans/{scan_id}")
    async def api_scan_delete(scan_id: int):
        if job_status().get("state") in ("running", "stopping"):
            raise HTTPException(409, "Impossible pendant un scan")
        try:
            from instree.core.store import compact_scan_ids, delete_scan

            delete_scan(scan_id)
            compact_scan_ids()
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        reset_job()
        return list_scans()

    @app.get("/api/search-index")
    async def api_search_index():
        return get_changes_search_index()

    @app.get("/api/scans/{scan_id}")
    async def api_scan(scan_id: int):
        data = get_scan(scan_id)
        if not data:
            raise HTTPException(404, "Scan introuvable")
        scan = data["scan"]
        adds = [c for c in data["changes"] if c["op"] == "add"]
        removes = [c for c in data["changes"] if c["op"] == "remove"]
        gones = [c for c in data["changes"] if c["op"] == "gone"]
        sub_changes = [
            c
            for c in data["changes"]
            if c["op"] in ("sub_add", "sub_remove", "sub_gone")
        ]

        person_groups: dict[str, dict] = {}
        for c in sub_changes:
            subject = c["subject_username"] or ""
            if subject not in person_groups:
                person_groups[subject] = {
                    "username": subject,
                    "adds": [],
                    "removes": [],
                    "gones": [],
                }
            if c["op"] == "sub_add":
                person_groups[subject]["adds"].append(c)
            elif c["op"] == "sub_gone":
                person_groups[subject]["gones"].append(c)
            else:
                person_groups[subject]["removes"].append(c)

        old_count = None
        if adds or removes or gones:
            old_count = scan["following_count"] - len(adds) + len(removes) + len(gones)
        return {
            **data,
            "adds": adds,
            "removes": removes,
            "gones": gones,
            "person_changes": list(person_groups.values()),
            "old_count": old_count,
            "has_changes": bool(adds or removes or gones or sub_changes),
        }

    @app.get("/api/scans/{scan_id}/neighbors")
    async def api_neighbors(scan_id: int):
        return scan_neighbors(scan_id)

    @app.get("/api/graph")
    async def api_graph(groups: int | None = None):
        target = groups if groups is not None and groups >= 2 else None
        data = get_graph_data(groups=target)
        if not data:
            return {
                "nodes": [],
                "links": [],
                "scan": None,
                "stats": {
                    "nodes": 0,
                    "links": 0,
                    "mutuals": 0,
                    "clusters": 0,
                    "max_groups": 1,
                    "groups_mode": "auto",
                },
            }
        return data

    @app.post("/api/scan")
    async def api_scan_start(body: ScanRequest):
        if is_web_mode():
            sched = load_server_schedule_settings()
            hour = sched["daily_hour"]
            raise HTTPException(
                403,
                f"Scans manuels désactivés sur le serveur web "
                f"(scan automatique chaque nuit à {hour}h).",
            )
        clear_session_cache()
        try:
            start_scan(init=body.init)
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
        return job_status()

    @app.post("/api/scan/reset")
    async def api_scan_reset():
        reset_job()
        return job_status()

    @app.post("/api/scan/cancel")
    async def api_scan_cancel():
        if is_web_mode():
            raise HTTPException(
                403,
                "Impossible d'arrêter un scan sur le serveur web.",
            )
        if not cancel_scan():
            raise HTTPException(409, "Aucun scan en cours")
        return job_status()

    return app
