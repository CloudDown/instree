"""CLI Instree Web — `instree-web` (multi-utilisateurs + auth)."""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time


def _serve_with_ngrok(host: str, port: int, app) -> int:
    import uvicorn

    from instree.core.netinfo import print_serve_banner
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

    print_serve_banner(bind_host, port, product="Instree Web", ngrok=True)
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

    from instree.core.config import enable_web_mode, load_server_web_settings
    from instree.core.netinfo import print_serve_banner
    from instree.web.app import create_app

    root = enable_web_mode()
    host, port = load_server_web_settings()
    if args.host:
        host = args.host
    elif args.ngrok and not args.no_ngrok:
        host = "127.0.0.1"
    if args.port:
        port = args.port

    print(f"instree-web  home={root}", flush=True)
    app = create_app()

    use_ngrok = args.ngrok and not args.no_ngrok
    if use_ngrok:
        return _serve_with_ngrok(host, port, app)

    print_serve_banner(host, port, product="Instree Web")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instree Web — serveur multi-utilisateurs (auth)",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--ngrok",
        action="store_true",
        help="exposer via ngrok (HTTPS temporaire ; défaut avec ./bin/run-web)",
    )
    parser.add_argument(
        "--no-ngrok",
        action="store_true",
        help="LAN seulement, sans tunnel ngrok",
    )
    args = parser.parse_args()
    sys.exit(cmd_serve(args))


if __name__ == "__main__":
    main()
