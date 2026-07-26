"""Comptes utilisateurs — Instree Web uniquement."""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass

from instree.core.config import accounts_db_path, bootstrap_web_home, ensure_user_home

_USER_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]{1,31}$")
_PBKDF2_ROUNDS = 200_000


@dataclass(frozen=True)
class Account:
    id: str
    username: str
    created_at: float


def _connect() -> sqlite3.Connection:
    bootstrap_web_home()
    path = accounts_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            pending_baseline INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(accounts)")}
    if "pending_baseline" not in cols:
        conn.execute(
            "ALTER TABLE accounts ADD COLUMN pending_baseline INTEGER NOT NULL DEFAULT 0"
        )
    conn.commit()
    return conn


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ROUNDS,
    )
    return f"pbkdf2${_PBKDF2_ROUNDS}${salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds_s, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2":
            return False
        rounds = int(rounds_s)
    except (ValueError, AttributeError):
        return False
    check = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        rounds,
    ).hex()
    return secrets.compare_digest(check, digest)


def _normalize_username(username: str) -> str:
    u = (username or "").strip()
    if not _USER_RE.match(u):
        raise ValueError(
            "Nom d'utilisateur invalide (2–32 car., lettres/chiffres/_/./-)"
        )
    return u


def _new_user_id(username: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", username.lower()).strip("-")[:24] or "user"
    candidate = base
    n = 0
    with _connect() as conn:
        while conn.execute(
            "SELECT 1 FROM accounts WHERE id = ?", (candidate,)
        ).fetchone():
            n += 1
            candidate = f"{base}-{n}"
    return candidate


def register_account(username: str, password: str) -> Account:
    username = _normalize_username(username)
    if not password or len(password) < 8:
        raise ValueError("Mot de passe trop court (8 caractères minimum)")
    if len(password) > 200:
        raise ValueError("Mot de passe trop long")

    uid = _new_user_id(username)
    created = time.time()
    pw_hash = _hash_password(password)
    with _connect() as conn:
        try:
            conn.execute(
                "INSERT INTO accounts (id, username, password_hash, created_at, pending_baseline) "
                "VALUES (?, ?, ?, ?, 1)",
                (uid, username, pw_hash, created),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError("Ce nom d'utilisateur est déjà pris") from e

    ensure_user_home(uid)
    return Account(id=uid, username=username, created_at=created)


def authenticate(username: str, password: str) -> Account | None:
    username = (username or "").strip()
    if not username or not password:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, created_at FROM accounts "
            "WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
    if not row:
        return None
    if not _verify_password(password, row["password_hash"]):
        return None
    ensure_user_home(row["id"])
    return Account(
        id=row["id"],
        username=row["username"],
        created_at=float(row["created_at"]),
    )


def get_account(user_id: str) -> Account | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, created_at FROM accounts WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return Account(
        id=row["id"],
        username=row["username"],
        created_at=float(row["created_at"]),
    )


def list_user_ids() -> list[str]:
    """Ids comptes (mode public) pour les tâches périodiques."""
    with _connect() as conn:
        rows = conn.execute("SELECT id FROM accounts ORDER BY id").fetchall()
    return [str(r["id"]) for r in rows]


def get_pending_baseline(user_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT pending_baseline FROM accounts WHERE id = ?", (user_id,)
        ).fetchone()
    return bool(row and row["pending_baseline"])


def clear_pending_baseline(user_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE accounts SET pending_baseline = 0 WHERE id = ?", (user_id,)
        )
        conn.commit()
