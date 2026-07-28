"""CLI Instree Web — `instree-web` (multi-utilisateurs + auth)."""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time


def _serve_with_tunnel(host: str, port: int, app) -> int:
    import uvicorn

    from instree.core.netinfo import print_serve_banner
    from instree.web.public_tunnel import (
        cloudflared_available,
        ngrok_available,
        start_public_tunnel,
    )

    if not cloudflared_available() and not ngrok_available():
        print(
            "! Aucun tunnel public trouvé.\n"
            "  Recommandé : cloudflared (pas de page d'avertissement)\n"
            "    https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/\n"
            "  Sinon : ngrok — https://ngrok.com/download puis authtoken",
            flush=True,
        )
        return 1

    # Garder 0.0.0.0 pour l'accès LAN ; le tunnel pointe déjà sur 127.0.0.1:port.
    bind_host = host or "0.0.0.0"

    def _run_uvicorn() -> None:
        uvicorn.run(app, host=bind_host, port=port, log_level="warning")

    thread = threading.Thread(target=_run_uvicorn, name="instree-uvicorn", daemon=True)
    thread.start()
    time.sleep(0.6)

    print_serve_banner(bind_host, port, product="Instree Web", ngrok=True)
    prefer = "cloudflare" if cloudflared_available() else "ngrok"
    print(f"  […] ouverture du tunnel ({prefer})…", flush=True)

    try:
        tunnel = start_public_tunnel(port)
    except RuntimeError as e:
        print(f"! {e}", flush=True)
        return 1

    if tunnel.url:
        print(f"  public   {tunnel.url}", flush=True)
        print(f"  login    {tunnel.url.rstrip('/')}/login", flush=True)
        if tunnel.kind in ("cloudflare-named", "cloudflare"):
            if tunnel.kind == "cloudflare-named":
                print("  note     Cloudflare nommé — URL fixe, sans avertissement", flush=True)
            else:
                print("  note     Cloudflare — pas de page d'avertissement navigateur", flush=True)
        else:
            print(
                "  note     ngrok free — page d'avertissement possible "
                "(installe cloudflared pour l'éviter)",
                flush=True,
            )
    else:
        print(
            "  ! URL publique indisponible. "
            "Vérifie les logs du tunnel (cloudflared / ngrok 4040).",
            flush=True,
        )

    try:
        code = tunnel.process.wait()
    except KeyboardInterrupt:
        print("\narrêt…", flush=True)
        tunnel.process.terminate()
        try:
            tunnel.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            tunnel.process.kill()
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
    if args.port:
        port = args.port

    print(f"instree-web  home={root}", flush=True)
    app = create_app()

    use_tunnel = args.ngrok and not args.no_ngrok
    if use_tunnel:
        return _serve_with_tunnel(host, port, app)

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
        help="exposer via tunnel public (Cloudflare si dispo, sinon ngrok)",
    )
    parser.add_argument(
        "--no-ngrok",
        action="store_true",
        help="LAN seulement, sans tunnel public",
    )
    args = parser.parse_args()
    sys.exit(cmd_serve(args))


if __name__ == "__main__":
    main()
