"""Auth cookie + middleware — couche propre à Instree Web.

Le reste de l'app (scans, settings, graph) est partagé avec Desktop.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from instree.web.accounts import get_account
from instree.core.config import (
    current_user_id,
    is_web_mode,
    load_secret_key,
    reset_current_user,
    set_current_user,
)
from instree.web.security import session_https_only

SESSION_COOKIE = "instree_session"
_PUBLIC_OPEN_PREFIXES = (
    "/static",
    "/login",
    "/register",
    "/api/auth/login",
    "/api/auth/register",
)


def install_session_middleware(app) -> None:
    app.add_middleware(
        SessionMiddleware,
        secret_key=load_secret_key(),
        session_cookie=SESSION_COOKIE,
        max_age=60 * 60 * 24 * 30,
        same_site="lax",
        https_only=session_https_only() if is_web_mode() else False,
    )


def login_user(
    request: Request,
    user_id: str,
    username: str,
    *,
    via_master: bool = False,
) -> None:
    request.session.clear()
    request.session["user_id"] = user_id
    request.session["username"] = username
    if via_master:
        request.session["via_master"] = True


def logout_user(request: Request) -> None:
    request.session.clear()


def session_user(request: Request) -> dict | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    account = get_account(str(uid))
    if not account:
        request.session.clear()
        return None
    return {"id": account.id, "username": account.username}


class WebAuthMiddleware(BaseHTTPMiddleware):
    """Exige une session pour Instree Web ; injecte current_user_id."""

    async def dispatch(self, request: Request, call_next: Callable):
        if not is_web_mode():
            return await call_next(request)

        path = request.url.path
        open_path = path == "/" or any(
            path == p or path.startswith(p + "/") for p in _PUBLIC_OPEN_PREFIXES
        )
        # Exact open API paths
        if path in ("/api/auth/login", "/api/auth/register", "/api/auth/logout"):
            open_path = True
        if path in ("/login", "/register"):
            open_path = True

        user = session_user(request)
        token = None
        if user:
            token = set_current_user(user["id"])
            request.state.user = user
        else:
            request.state.user = None

        try:
            if not user and not open_path:
                if path.startswith("/api/"):
                    return JSONResponse(
                        {"detail": "Authentification requise"},
                        status_code=401,
                    )
                return RedirectResponse(
                    f"/login?next={path}",
                    status_code=307,
                )
            return await call_next(request)
        finally:
            if token is not None:
                reset_current_user(token)


def job_user_key() -> str:
    if is_web_mode():
        uid = current_user_id()
        if not uid:
            raise RuntimeError("utilisateur requis")
        return uid
    return "local"
