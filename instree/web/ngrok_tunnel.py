"""Compat : tunnel public (Cloudflare préféré, sinon ngrok)."""

from __future__ import annotations

import subprocess

from instree.web.public_tunnel import (
    cloudflared_available,
    ngrok_available,
    start_public_tunnel,
    wait_for_ngrok_url,
)

__all__ = [
    "cloudflared_available",
    "ngrok_available",
    "start_ngrok",
    "start_public_tunnel",
    "wait_for_ngrok_url",
]


def start_ngrok(port: int) -> subprocess.Popen:
    """Démarre un tunnel public (Cloudflare si dispo, sinon ngrok)."""
    return start_public_tunnel(port).process
