"""Tunnel public HTTPS devant Instree Web (Cloudflare, sinon ngrok)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_CF_URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com")


@dataclass
class PublicTunnel:
    kind: str  # "cloudflare" | "ngrok"
    process: subprocess.Popen
    url: str | None
    _log_path: Path | None = None


def cloudflared_available() -> bool:
    return shutil.which("cloudflared") is not None


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


def _wait_for_cloudflared_url(log_path: Path, proc: subprocess.Popen, *, timeout: float = 45.0) -> str | None:
    """Parse l'URL trycloudflare.com depuis le fichier de log cloudflared."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None and not log_path.is_file():
            break
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        match = _CF_URL_RE.search(text)
        if match:
            return match.group(0)
        if proc.poll() is not None:
            break
        time.sleep(0.3)
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _CF_URL_RE.search(text)
    return match.group(0) if match else None


def start_public_tunnel(port: int) -> PublicTunnel:
    """Préfère Cloudflare (pas d'interstitial) ; sinon ngrok."""
    if cloudflared_available():
        log_file = tempfile.NamedTemporaryFile(
            prefix="instree-cloudflared-",
            suffix=".log",
            delete=False,
        )
        log_path = Path(log_file.name)
        log_file.close()
        proc = subprocess.Popen(
            [
                "cloudflared",
                "tunnel",
                "--url",
                f"http://127.0.0.1:{port}",
                "--no-autoupdate",
                "--logfile",
                str(log_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        url = _wait_for_cloudflared_url(log_path, proc)
        return PublicTunnel(kind="cloudflare", process=proc, url=url, _log_path=log_path)

    if ngrok_available():
        proc = subprocess.Popen(
            ["ngrok", "http", str(port), "--log=stdout", "--log-format=logfmt"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        url = wait_for_ngrok_url()
        return PublicTunnel(kind="ngrok", process=proc, url=url)

    raise RuntimeError(
        "Aucun tunnel public : installe cloudflared (recommandé, sans page d'avertissement) "
        "ou ngrok (https://ngrok.com/download)."
    )
