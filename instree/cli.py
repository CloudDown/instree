"""CLI instree scan | instree serve."""

import argparse
import sys

from instree.config import load_settings
from instree.scan import run_scan
from instree.session import connect, session_user
from instree.store import init_db


def cmd_scan(args: argparse.Namespace) -> int:
    settings = load_settings()
    init_db()
    try:
        ig, source, note = connect()
    except RuntimeError as e:
        print(f"! Erreur session : {e}")
        return 1

    target = settings.username or session_user(ig)
    n_label = str(settings.n) if settings.n > 0 else "tous"

    print("── scan abonnements ──", flush=True)
    print(f"  compte   @{target}", flush=True)
    print(f"  suivis   {n_label}", flush=True)
    print(f"  source   {source}", flush=True)
    if note:
        print(f"  note     {note}", flush=True)
    if args.init:
        print("  mode     baseline (--init)")
    elif args.full:
        print("  mode     complet (--full)")
    else:
        print("  mode     incrémental")
    print()

    def _progress(current, total, username):
        print(f"  [{current}/{total}] @{username}…", flush=True)

    try:
        summary = run_scan(
            ig,
            settings,
            init=args.init,
            full=args.full,
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
        print(f"  évolutions    : {summary.counts}")
        if summary.journal_path:
            print(f"  journal       : {summary.journal_path}")
    print()
    return 0


def cmd_schedule_install(args: argparse.Namespace) -> int:
    from instree.schedule import install_systemd

    settings = load_settings()
    try:
        unit_dir, root, exec_start = install_systemd(settings)
    except RuntimeError as e:
        print(f"! {e}")
        return 1

    print("── planification systemd ──")
    print(f"  dépôt     {root}")
    print(f"  commande  {exec_start}")
    print(f"  heures    {', '.join(settings.schedule_times)}")
    print(f"  unités    {unit_dir}/")
    print()
    print("  systemctl --user daemon-reload")
    print("  systemctl --user enable --now instree-scan.timer")
    print("  systemctl --user list-timers instree-scan.timer")
    print()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    from instree.web.app import create_app

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    init_db()
    app = create_app()
    print("── instree web ──")
    print(f"  http://{host}:{port}")
    print()
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instree — suivi des abonnements Instagram",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="scanner les abonnements")
    p_scan.add_argument("--init", action="store_true", help="baseline complète")
    p_scan.add_argument("--full", action="store_true", help="re-télécharger la liste")
    p_scan.add_argument("-q", "--quiet", action="store_true", help="sans progression")
    p_scan.set_defaults(func=cmd_scan)

    p_serve = sub.add_parser("serve", help="interface web")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.set_defaults(func=cmd_serve)

    p_schedule = sub.add_parser("schedule", help="planification systemd")
    p_schedule_sub = p_schedule.add_subparsers(dest="schedule_cmd", required=True)
    p_install = p_schedule_sub.add_parser(
        "install", help="génère le timer depuis instree.toml"
    )
    p_install.set_defaults(func=cmd_schedule_install)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
