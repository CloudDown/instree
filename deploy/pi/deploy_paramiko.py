#!/usr/bin/env python3
"""Déploiement Instree sur Raspberry Pi via Paramiko (mot de passe SSH)."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import paramiko

PI_HOST = os.environ.get("PI_HOST", "192.168.2.170")
PI_USER = os.environ.get("PI_USER", "pi")
PI_PASS = os.environ.get("PI_PASS", "pi")
PI_DIR = os.environ.get("PI_DIR", "/home/pi/instree")
DATA_DIR = os.environ.get("PI_DATA", "/var/lib/instree")
ROOT = Path(__file__).resolve().parents[2]

EXCLUDES = {
    ".git",
    ".venv",
    "__pycache__",
    "var/web/users",
    "var/web/accounts.db",
    "var/web/secret.key",
}


def _should_skip(rel: Path) -> bool:
    if ".git" in rel.parts:
        return True
    if rel.parts[:1] == (".venv",) or ".venv" in rel.parts:
        return True
    if "__pycache__" in rel.parts or rel.suffix == ".pyc":
        return True
    s = rel.as_posix()
    return s.startswith("var/web/users") or s in (
        "var/web/accounts.db",
        "var/web/secret.key",
    )


def _make_tar() -> Path:
    tmp = Path(tempfile.mkstemp(suffix=".tar.gz")[1])
    print(f"==> Archive {tmp}")
    with tarfile.open(tmp, "w:gz") as tar:
        for item in ROOT.rglob("*"):
            rel = item.relative_to(ROOT)
            if _should_skip(rel):
                continue
            tar.add(item, arcname=str(rel))
    return tmp


def _run(client: paramiko.SSHClient, cmd: str, *, sudo: bool = False) -> None:
    if sudo:
        cmd = f"echo '{PI_PASS}' | sudo -S bash -lc {repr(cmd)}"
    print(f"\n>> {cmd[:140]}{'…' if len(cmd) > 140 else ''}")
    _, stdout, stderr = client.exec_command(cmd, get_pty=True)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if code != 0:
        if err.strip():
            print(err.rstrip(), file=sys.stderr)
        raise SystemExit(f"Command failed ({code}): {cmd[:80]}")


def main() -> None:
    tar_path = _make_tar()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"==> Connexion {PI_USER}@{PI_HOST}")
    client.connect(
        PI_HOST,
        username=PI_USER,
        password=PI_PASS,
        timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )

    sftp = client.open_sftp()
    remote_tar = f"/home/{PI_USER}/instree-deploy.tar.gz"
    print(f"==> Upload {remote_tar}")
    sftp.put(str(tar_path), remote_tar)
    sftp.close()
    tar_path.unlink(missing_ok=True)

    _run(client, f"mkdir -p {PI_DIR} && tar xzf {remote_tar} -C {PI_DIR}")
    _run(client, f"rm -f {remote_tar}")

    _run(client, "rm -f /etc/apt/sources.list.d/ngrok.list /etc/apt/trusted.gpg.d/ngrok.asc", sudo=True)

    # Fallback ngrok si cloudflared indisponible (installé dans setup-remote.sh).
    _run(
        client,
        "command -v ngrok >/dev/null || npm install -g ngrok",
        sudo=True,
    )

    local_ngrok = Path.home() / ".config/ngrok/ngrok.yml"
    if local_ngrok.is_file():
        _run(client, "mkdir -p ~/.config/ngrok")
        sftp = client.open_sftp()
        sftp.put(str(local_ngrok), f"/home/{PI_USER}/.config/ngrok/ngrok.yml")
        sftp.close()
        print("==> Config ngrok copiée (fallback)")

    _run(client, f"chmod +x {PI_DIR}/deploy/pi/setup-remote.sh")
    _run(
        client,
        f"SUDO_PASS={PI_PASS} INSTREE_DIR={PI_DIR} INSTREE_DATA={DATA_DIR} SERVICE_USER={PI_USER} "
        f"bash {PI_DIR}/deploy/pi/setup-remote.sh",
    )

    _run(client, "systemctl is-active instree-web && systemctl is-enabled instree-web")
    _run(
        client,
        "sleep 3 && journalctl -u instree-web -n 25 --no-pager",
        sudo=True,
    )

    client.close()
    print("\n==> Déploiement terminé")
    print(f"    LAN : http://{PI_HOST}:1488/login")
    print("    URL publique : voir les logs ci-dessus (journalctl -u instree-web -f)")


if __name__ == "__main__":
    main()
