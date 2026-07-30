#!/usr/bin/env python3
"""Définit le mot de passe maître Instree Web (hash dans INSTREE_HOME/master.key)."""

from __future__ import annotations

import argparse
import os
import secrets
import string
import sys


def _generate_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%&*-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def main() -> int:
    parser = argparse.ArgumentParser(description="Mot de passe maître Instree Web")
    parser.add_argument(
        "--generate",
        action="store_true",
        help="génère un mot de passe aléatoire (32 car.)",
    )
    parser.add_argument(
        "password",
        nargs="?",
        help="mot de passe (sinon INSTREE_MASTER_PASSWORD)",
    )
    args = parser.parse_args()

    from instree.core.config import enable_web_mode
    from instree.web.accounts import set_master_password

    enable_web_mode()
    if args.generate:
        password = _generate_password()
    else:
        password = args.password or os.environ.get("INSTREE_MASTER_PASSWORD", "")
    if not password:
        print("Mot de passe requis (argument, --generate ou INSTREE_MASTER_PASSWORD)", file=sys.stderr)
        return 1
    set_master_password(password)
    if args.generate:
        print(password)
    else:
        print("OK — master.key mis à jour")
    return 0


if __name__ == "__main__":
    sys.exit(main())
