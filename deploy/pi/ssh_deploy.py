#!/usr/bin/env python3
"""Déploiement Pi via SSH mot de passe (pty, sans dépendance externe)."""

from __future__ import annotations

import os
import pty
import select
import subprocess
import sys
from pathlib import Path

PI = os.environ.get("PI_HOST", "pi@192.168.2.170")


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"{name} manquant — export ou oeuil/secrets.env", file=sys.stderr)
        sys.exit(1)
    return val


PI_PASS = _require_env("PI_PASS")
ROOT = Path(__file__).resolve().parents[2]
PI_DIR = os.environ.get("PI_DIR", "/home/pi/instree")


def _rsync() -> None:
    excludes = [
        ".git",
        ".venv",
        "var/web/users",
        "var/web/accounts.db",
        "var/web/secret.key",
        "__pycache__",
    ]
    cmd = ["rsync", "-avz", "--delete"]
    for ex in excludes:
        cmd.extend(["--exclude", ex])
    cmd.extend([f"{ROOT}/", f"{PI}:{PI_DIR}/"])
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd)


def _ssh(script: str) -> None:
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-tt", PI, script]
    print(">>", " ".join(cmd))
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
        text=False,
    )
    os.close(slave)
    sent_pass = False
    buf = b""
    try:
        while proc.poll() is None:
            r, _, _ = select.select([master], [], [], 0.2)
            if not r:
                continue
            chunk = os.read(master, 4096)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            buf = (buf + chunk)[-512:]
            low = buf.lower()
            if not sent_pass and (b"password:" in low or b"mot de passe" in low):
                os.write(master, (PI_PASS + "\n").encode())
                sent_pass = True
        while True:
            r, _, _ = select.select([master], [], [], 0)
            if not r:
                break
            chunk = os.read(master, 4096)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
    finally:
        os.close(master)
    if proc.wait() != 0:
        raise SystemExit(proc.returncode)


def main() -> None:
    _rsync()
    _ssh(f"chmod +x {PI_DIR}/deploy/pi/setup-remote.sh && {PI_DIR}/deploy/pi/setup-remote.sh")


if __name__ == "__main__":
    main()
