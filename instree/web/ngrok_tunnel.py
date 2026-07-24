"""Lancement d'un tunnel ngrok devant le serveur public."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request


def ngrok_available() -> bool:
    return shutil.which("ngrok") is not None


def wait_for_ngrok_url(*, timeout: float = 15.0) -> str | None:
    """Lit l'URL publique HTTPS via l'API locale ngrok (port 4040)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:4040/api/tunnels", timeout=1.5
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            tunnels = data.get("tunnels") or []
            https = next(
                (
                    t.get("public_url")
                    for t in tunnels
                    if str(t.get("public_url") or "").startswith("https://")
                ),
                None,
            )
            if https:
                return https
            http = next(
                (
                    t.get("public_url")
                    for t in tunnels
                    if str(t.get("public_url") or "").startswith("http://")
                ),
                None,
            )
            if http:
                return http
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            pass
        time.sleep(0.4)
    return None


def start_ngrok(port: int) -> subprocess.Popen:
    """Démarre `ngrok http <port>` (processus enfant)."""
    if not ngrok_available():
        raise RuntimeError(
            "ngrok introuvable dans le PATH — installe-le depuis https://ngrok.com/download "
            "puis `ngrok config add-authtoken <token>`"
        )
    return subprocess.Popen(
        ["ngrok", "http", str(port), "--log=stdout", "--log-format=logfmt"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
