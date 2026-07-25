"""CLI instree scan | instree serve."""

import argparse
import socket
import subprocess
import sys
import threading
import time


def _is_usable_lan_ip(ip: str) -> bool:
    if not ip or ip.startswith(("127.", "0.", "169.254.")):
        return False
    if ip.startswith(("172.17.", "172.18.", "172.19.")):
        return False
    return True


def _lan_ipv4() -> str | None:
    """IP IPv4 du réseau local (Wi‑Fi / Ethernet), pour y accéder depuis un autre appareil."""
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
            if _is_usable_lan_ip(ip):
                return ip
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("1.1.1.1", 80))
            ip = s.getsockname()[0]
        if _is_usable_lan_ip(ip):
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
            if _is_usable_lan_ip(ip):
                return ip
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return None


def _print_serve_banner(
    host: str,
    port: int,
    *,
    public: bool = False,
    ngrok: bool = False,
) -> None:
    print(f"instree web  http://{host}:{port}", flush=True)
    if host in ("0.0.0.0", "::", "[::]"):
        lan = _lan_ipv4()
        if lan:
            print(f"  wifi     http://{lan}:{port}", flush=True)
            print(
                "  tip      autres téléphones : même Wi‑Fi que ce PC "
                "(pas 4G, pas Wi‑Fi invité). Hors Wi‑Fi : --ngrok",
                flush=True,
            )
        print(f"  local    http://127.0.0.1:{port}", flush=True)
    if ngrok:
        print("  mode     Instree Web + ngrok", flush=True)
    elif public:
        print("  mode     Instree Web (auth requise)", flush=True)


def cmd_scan(args: argparse.Namespace) -> int:
    from instree.config import format_limit, load_settings
    from instree.scan import run_scan
    from instree.session import connect, session_user
    from instree.store import init_db

    settings = load_settings()
    init_db()
    try:
        ig, source, note = connect()
    except RuntimeError as e:
        print(f"! Erreur session : {e}")
        return 1

    target = settings.username or session_user(ig)
    n_label = format_limit(settings.n)
    watch_label = format_limit(settings.watch_n)

    print("── scan abonnements ──", flush=True)
    print(f"  compte   @{target}", flush=True)
    print(f"  mutuels      {n_label}", flush=True)
    print(f"  watch_n  {watch_label}", flush=True)
    print(f"  source   {source}", flush=True)
    if note:
        print(f"  note     {note}", flush=True)
    if args.init:
        print("  mode     baseline (--init)")
    else:
        print("  mode     incrémental")
    print()

    def _progress(current, total, username, phase="profile", track="profiles"):
        if track == "watch" and phase == "page":
            print(f"  @{username} abonnements [{current}/{total or '?'}]…", flush=True)
            return
        labels = {
            "profile": "profil",
            "baseline": "baseline",
            "fetch": "liste",
            "mutuals": "mutuels",
        }
        label = labels.get(phase, phase)
        prefix = "profils" if track == "profiles" else "abos"
        if phase == "mutuals":
            print(f"  ({prefix}) chargement mutuels…", flush=True)
        elif username:
            print(f"  ({prefix}) [{current}/{total}] @{username} ({label})…", flush=True)

    try:
        summary = run_scan(
            ig,
            settings,
            init=args.init,
            on_progress=_progress if not args.quiet else None,
        )
    except RuntimeError as e:
        print(f"! {e}")
        return 1

    print()
    if summary.unchanged:
        print(
            f"  @{summary.username} inchangé ({summary.tracked}/{summary.following_count})"
        )
        print("  aucun nouveau scan enregistré")
    else:
        print(f"  scan #{summary.scan_id} terminé")
        print(f"  suivis        : {summary.tracked}/{summary.following_count}")
        print(f"  ajouts        : {summary.added}")
        print(f"  retraits      : {summary.removed}")
        print(f"  abos +        : {summary.person_added}")
        print(f"  abos −        : {summary.person_removed}")
        if summary.journal_path:
            print(f"  journal       : {summary.journal_path}")
    print()
    return 0


def _serve_with_ngrok(host: str, port: int, app) -> int:
    import uvicorn

    from instree.web.ngrok_tunnel import (
        ngrok_available,
        start_ngrok,
        wait_for_ngrok_url,
    )

    if not ngrok_available():
        print(
            "! ngrok introuvable dans le PATH.\n"
            "  1. Installe : https://ngrok.com/download\n"
            "  2. ngrok config add-authtoken <ton-token>",
            flush=True,
        )
        return 1

    bind_host = host if host not in ("0.0.0.0", "::") else "127.0.0.1"

    def _run_uvicorn() -> None:
        uvicorn.run(app, host=bind_host, port=port, log_level="warning")

    thread = threading.Thread(target=_run_uvicorn, name="instree-uvicorn", daemon=True)
    thread.start()
    time.sleep(0.6)

    _print_serve_banner(bind_host, port, public=True, ngrok=True)
    print("  […] ouverture du tunnel ngrok…", flush=True)

    try:
        ngrok_proc = start_ngrok(port)
    except RuntimeError as e:
        print(f"! {e}", flush=True)
        return 1

    url = wait_for_ngrok_url()
    if url:
        print(f"  public   {url}", flush=True)
        print(f"  login    {url.rstrip('/')}/login", flush=True)
    else:
        print(
            "  ! URL ngrok indisponible (authtoken manquant ?). "
            "Vérifie http://127.0.0.1:4040",
            flush=True,
        )

    try:
        code = ngrok_proc.wait()
    except KeyboardInterrupt:
        print("\narrêt…", flush=True)
        ngrok_proc.terminate()
        try:
            ngrok_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            ngrok_proc.kill()
        return 0
    return int(code or 0)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from instree.config import (
        enable_public_mode,
        is_public_mode,
        load_server_web_settings,
        load_settings,
    )
    from instree.store import init_db
    from instree.web.app import create_app

    use_ngrok = bool(args.ngrok)
    use_public = bool(args.public) or use_ngrok

    if use_public:
        root = enable_public_mode()
        host, port = load_server_web_settings()
        if args.host:
            host = args.host
        elif use_ngrok:
            host = "127.0.0.1"
        if args.port:
            port = args.port
        print(f"instree public  home={root}", flush=True)
    else:
        settings = load_settings()
        host = args.host or settings.host
        port = args.port or settings.port
        init_db()

    app = create_app()

    if use_ngrok:
        return _serve_with_ngrok(host, port, app)

    _print_serve_banner(host, port, public=is_public_mode())
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instree — suivi des abonnements Instagram",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="scanner les abonnements")
    p_scan.add_argument("--init", action="store_true", help="baseline complète")
    p_scan.add_argument("-q", "--quiet", action="store_true", help="sans progression")
    p_scan.set_defaults(func=cmd_scan)

    p_serve = sub.add_parser("serve", help="interface web")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument(
        "--public",
        action="store_true",
        help="mode serveur public multi-utilisateurs (données dans serveur/)",
    )
    p_serve.add_argument(
        "--ngrok",
        action="store_true",
        help="expose le mode public via ngrok (active --public, bind 127.0.0.1)",
    )
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
