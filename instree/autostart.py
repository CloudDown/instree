"""Démarrage automatique de instree serve à la connexion."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

from instree.config import project_root


DESKTOP_NAME = "instree.desktop"
WINDOWS_BAT_NAME = "instree-serve.bat"
MAC_PLIST_NAME = "com.instree.serve.plist"


def _quote(path: Path | str) -> str:
    s = str(path)
    if any(c in s for c in ' \t"\\$'):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def resolve_serve_command(root: Path) -> str:
    """Commande absolue pour lancer instree serve."""
    candidates = [
        root / ".venv" / "bin" / "instree",
        root / ".venv" / "Scripts" / "instree.exe",
        Path(sys.executable).parent / "instree",
        Path(sys.executable).parent / "instree.exe",
    ]
    for binary in candidates:
        if binary.is_file():
            return f"{_quote(binary)} serve"

    on_path = shutil.which("instree")
    if on_path:
        return f"{_quote(on_path)} serve"

    for py in (
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    ):
        if py.is_file():
            return f"{_quote(py)} -m instree.cli serve"

    raise RuntimeError(
        "instree introuvable — depuis le dépôt : uv sync (ou pip install -e .)"
    )


def _linux_desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / DESKTOP_NAME


def _windows_bat_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("variable APPDATA introuvable")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / WINDOWS_BAT_NAME


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / MAC_PLIST_NAME


def autostart_path() -> Path | None:
    system = platform.system()
    if system == "Linux":
        return _linux_desktop_path()
    if system == "Windows":
        return _windows_bat_path()
    if system == "Darwin":
        return _mac_plist_path()
    return None


def remove_legacy_systemd() -> None:
    """Supprime d'anciennes unités systemd si présentes."""
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    for name in ("instree-scan.service", "instree-scan.timer"):
        path = unit_dir / name
        if path.is_file():
            path.unlink()


def _write_linux(root: Path, exec_cmd: str) -> Path:
    path = _linux_desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""[Desktop Entry]
Type=Application
Name=Instree
Comment=Suivi des abonnements Instagram
Exec={exec_cmd}
Path={root}
Terminal=false
X-GNOME-Autostart-enabled=true
"""
    path.write_text(content, encoding="utf-8")
    return path


def _write_windows(root: Path, exec_cmd: str) -> Path:
    path = _windows_bat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log = root / "data" / "serve.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    content = f"""@echo off
cd /d {_quote(root)}
{exec_cmd} >> {_quote(log)} 2>&1
"""
    path.write_text(content, encoding="utf-8")
    return path


def _write_macos(root: Path, exec_cmd: str) -> Path:
    path = _mac_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log = root / "data" / "serve.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.instree.serve</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>{exec_cmd} &gt;&gt; {log} 2&gt;&amp;1</string>
  </array>
  <key>WorkingDirectory</key>
  <string>{root}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
</dict>
</plist>
"""
    path.write_text(content, encoding="utf-8")
    return path


def enable() -> Path:
    root = project_root().resolve()
    if not (root / "config" / "instree.toml").is_file() and not (
        root / "instree.toml"
    ).is_file():
        raise RuntimeError(
            f"config/instree.toml introuvable dans {root} — lance la commande depuis le dépôt cloné"
        )
    exec_cmd = resolve_serve_command(root)
    system = platform.system()
    if system == "Linux":
        return _write_linux(root, exec_cmd)
    if system == "Windows":
        return _write_windows(root, exec_cmd)
    if system == "Darwin":
        return _write_macos(root, exec_cmd)
    raise RuntimeError(f"démarrage automatique non pris en charge sur {system}")


def disable() -> None:
    path = autostart_path()
    if path is not None and path.is_file():
        path.unlink()


def sync_autostart(enabled: bool) -> Path | None:
    """Active ou désactive le démarrage automatique."""
    remove_legacy_systemd()
    if enabled:
        return enable()
    disable()
    return None
