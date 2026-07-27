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
    if not os.environ.get("INSTREE_HTTPS", "").strip():
        return True
    return os.environ.get("INSTREE_HTTPS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


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
        if session_https_only():
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
