"""CLI instree scan | instree serve."""
import argparse
import sys

from instree.scanner import run_scan
from instree.session import connect, session_user
from instree.store import init_db


def cmd_scan(args: argparse.Namespace) -> int:
    init_db()
    try:
        ig, source, note = connect()
    except RuntimeError as e:
        print(f"! Erreur session : {e}")
        return 1

    print(f"── scan abonnements close friends ──", flush=True)
    print(f"  compte  @{session_user(ig)}", flush=True)
    print(f"  source  {source}", flush=True)
    if note:
        print(f"  note    {note}", flush=True)
    if args.init:
        print("  mode    baseline (--init)")
    elif args.full:
        print("  mode    complet (--full)")
    else:
        print("  mode    incrémental")
    print()

    def progress(current, total, username):
        print(f"  [{current}/{total}] @{username}…", flush=True)

    try:
        summary = run_scan(
            ig,
            init=args.init,
            full=args.full,
            on_progress=progress if not args.quiet else None,
        )
    except RuntimeError as e:
        print(f"! {e}")
        return 1

    print()
    print(f"  scan #{summary.scan_id} terminé")
    print(f"  close friends : {summary.friends_total}")
    print(f"  changements   : {summary.changed}")
    print(f"  inchangés     : {summary.unchanged}")
    print(f"  ignorés       : {summary.skipped}")
    if summary.journal_path:
        print(f"  journal       : {summary.journal_path}")
    print()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    from instree.web.app import create_app

    init_db()
    app = create_app()
    print(f"── instree web ──")
    print(f"  http://{args.host}:{args.port}")
    print()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instree — scanner d'abonnements close friends",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="scanner les abonnements")
    p_scan.add_argument("--init", action="store_true", help="baseline complète")
    p_scan.add_argument("--full", action="store_true", help="re-télécharger toutes les listes")
    p_scan.add_argument("-q", "--quiet", action="store_true", help="sans progression")
    p_scan.set_defaults(func=cmd_scan)

    p_serve = sub.add_parser("serve", help="interface web")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
