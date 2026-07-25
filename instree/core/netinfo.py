"""Infos réseau pour les banners de lancement."""

from __future__ import annotations

import socket
import subprocess


def is_usable_lan_ip(ip: str) -> bool:
    if not ip or ip.startswith(("127.", "0.", "169.254.")):
        return False
    if ip.startswith(("172.17.", "172.18.", "172.19.")):
        return False
    return True


def lan_ipv4() -> str | None:
    """IP IPv4 du réseau local (Wi‑Fi / Ethernet)."""
    try:
        out = subprocess.check_output(
            ["ip", "-4", "route", "get", "1.1.1.1"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        parts = out.split()
        if "src" in parts:
            ip = parts[parts.index("src") + 1]
            if is_usable_lan_ip(ip):
                return ip
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("1.1.1.1", 80))
            ip = s.getsockname()[0]
        if is_usable_lan_ip(ip):
            return ip
    except OSError:
        pass

    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        for line in out.splitlines():
            cols = line.split()
            if "inet" not in cols:
                continue
            iface = cols[1] if len(cols) > 1 else ""
            if iface.startswith(("docker", "br-", "veth", "virbr", "waydroid")):
                continue
            ip = cols[cols.index("inet") + 1].split("/", 1)[0]
            if is_usable_lan_ip(ip):
                return ip
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return None


def print_serve_banner(
    host: str,
    port: int,
    *,
    product: str = "Instree Desktop",
    ngrok: bool = False,
) -> None:
    print(f"{product.lower().replace(' ', '-')}  http://{host}:{port}", flush=True)
    if host in ("0.0.0.0", "::", "[::]"):
        lan = lan_ipv4()
        if lan:
            print(f"  wifi     http://{lan}:{port}", flush=True)
            if "Web" in product:
                print(
                    "  tip      autres appareils : même Wi‑Fi que ce PC "
                    "(pas 4G, pas Wi‑Fi invité). Hors Wi‑Fi : --ngrok",
                    flush=True,
                )
        print(f"  local    http://127.0.0.1:{port}", flush=True)
    if ngrok:
        print("  mode     Instree Web + ngrok", flush=True)
    elif "Web" in product:
        print("  mode     Instree Web (auth requise)", flush=True)
    else:
        print("  mode     Instree Desktop", flush=True)
