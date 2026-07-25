"""CLI Instree Desktop — `instree scan` | `instree serve`."""

from __future__ import annotations

import argparse
import sys


def cmd_scan(args: argparse.Namespace) -> int:
    from instree.core.config import format_limit, load_settings
    from instree.core.scan import run_scan
    from instree.core.session import connect, session_user
    from instree.core.store import init_db

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


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from instree.core.config import load_settings
    from instree.core.netinfo import print_serve_banner
    from instree.core.store import init_db
    from instree.web.app import create_app

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    init_db()

    app = create_app()
    print_serve_banner(host, port, product="Instree Desktop")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instree Desktop — suivi local des abonnements Instagram",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="scanner les abonnements")
    p_scan.add_argument("--init", action="store_true", help="baseline complète")
    p_scan.add_argument("-q", "--quiet", action="store_true", help="sans progression")
    p_scan.set_defaults(func=cmd_scan)

    p_serve = sub.add_parser("serve", help="lancer l'interface Desktop")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
