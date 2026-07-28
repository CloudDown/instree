"""Tunnel public HTTPS devant Instree Web (Cloudflare nommé, quick, sinon ngrok)."""

from __future__ import annotations

import json
import os
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
_DEFAULT_NAMED_HOST = "https://instree.org"


@dataclass
class PublicTunnel:
    kind: str  # "cloudflare-named" | "cloudflare" | "ngrok"
    process: subprocess.Popen
    url: str | None
    _log_path: Path | None = None


def cloudflared_available() -> bool:
    return shutil.which("cloudflared") is not None


def ngrok_available() -> bool:
    return shutil.which("ngrok") is not None


def _cloudflared_home() -> Path:
    env = os.environ.get("CLOUDFLARED_CONFIG", "").strip()
    if env:
        return Path(env).expanduser().resolve().parent
    return Path.home() / ".cloudflared"


def named_cloudflare_config() -> Path | None:
    """Config tunnel nommé (`~/.cloudflared/config.yml`) si présente."""
    path = _cloudflared_home() / "config.yml"
    return path if path.is_file() else None


def named_cloudflare_public_url() -> str:
    """URL publique stable (override possible via INSTREE_PUBLIC_URL)."""
    env = os.environ.get("INSTREE_PUBLIC_URL", "").strip().rstrip("/")
    if env:
        return env
    return _DEFAULT_NAMED_HOST


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


def _wait_named_tunnel_ready(proc: subprocess.Popen, log_path: Path, *, timeout: float = 30.0) -> bool:
    """Attend que le tunnel nommé soit connecté (ou le process encore vivant)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            text = ""
        if "registered tunnel connection" in text or "connIndex" in text:
            return True
        if "error" in text and "failed to" in text:
            # laisser une chance : parfois des retries
            pass
        time.sleep(0.4)
    return proc.poll() is None


def start_public_tunnel(port: int) -> PublicTunnel:
    """Préfère tunnel Cloudflare nommé (URL fixe), sinon quick tunnel, sinon ngrok."""
    if cloudflared_available():
        named = named_cloudflare_config()
        if named is not None:
            log_file = tempfile.NamedTemporaryFile(
                prefix="instree-cloudflared-named-",
                suffix=".log",
                delete=False,
            )
            log_path = Path(log_file.name)
            log_file.close()
            # --no-autoupdate doit être avant `run` (option de `tunnel`, pas de `run`)
            proc = subprocess.Popen(
                [
                    "cloudflared",
                    "tunnel",
                    "--config",
                    str(named),
                    "--no-autoupdate",
                    "run",
                ],
                stdout=subprocess.DEVNULL,
                stderr=open(log_path, "w", encoding="utf-8"),
                env={**os.environ, "HOME": str(Path.home())},
            )
            ok = _wait_named_tunnel_ready(proc, log_path)
            url = named_cloudflare_public_url() if (ok or proc.poll() is None) else None
            return PublicTunnel(
                kind="cloudflare-named",
                process=proc,
                url=url,
                _log_path=log_path,
            )

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
