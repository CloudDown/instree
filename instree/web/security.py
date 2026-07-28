"""Durcissement Instree Web (public / ngrok)."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

_RATE_BUCKETS: dict[str, list[float]] = defaultdict(list)
_RATE_PATHS = frozenset({"/api/auth/login", "/api/auth/register"})
_RATE_LIMIT = 10
_RATE_WINDOW = 300.0  # 5 min


def allow_register() -> bool:
    raw = os.environ.get("INSTREE_ALLOW_REGISTER", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def session_https_only() -> bool:
    """Cookie Secure uniquement si explicitement forcé.

    Sur la Pi on sert à la fois le LAN en HTTP et Cloudflare en HTTPS :
    un cookie Secure casserait la connexion locale (navigateur l'ignore).
    """
    raw = os.environ.get("INSTREE_HTTPS_ONLY", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    # Ancien flag INSTREE_HTTPS=1 ne force plus Secure (compat dual HTTP/HTTPS).
    return False


def request_is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return proto == "https"


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def check_auth_rate_limit(request: Request) -> JSONResponse | None:
    path = request.url.path
    if request.method != "POST" or path not in _RATE_PATHS:
        return None
    ip = _client_ip(request)
    now = time.time()
    bucket = _RATE_BUCKETS[ip]
    _RATE_BUCKETS[ip] = bucket = [t for t in bucket if now - t < _RATE_WINDOW]
    if len(bucket) >= _RATE_LIMIT:
        return JSONResponse(
            {"detail": "Trop de tentatives — réessaie dans quelques minutes."},
            status_code=429,
        )
    bucket.append(now)
    return None


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        # HSTS seulement sur une vraie requête HTTPS (pas sur le LAN HTTP).
        if request_is_https(request):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        blocked = check_auth_rate_limit(request)
        if blocked is not None:
            return blocked
        return await call_next(request)
