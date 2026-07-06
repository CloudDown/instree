"""Stockage SQLite + journal texte."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from instree.config import DB_PATH, JOURNAL_DIR


@dataclass
class FollowingEntry:
    username: str
    pk: str
    full_name: str


@dataclass
class FriendChange:
    friend_username: str
    op: str  # add | remove
    target_username: str
    full_name: str


@dataclass
class FriendResult:
    friend_username: str
    friend_pk: str
    old_count: int | None
    new_count: int
    added: list[FollowingEntry]
    removed: list[FollowingEntry]
    unchanged: bool
    skipped: bool
    skip_reason: str = ""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scanned_at TEXT NOT NULL,
                label TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                scan_id INTEGER NOT NULL,
                friend_username TEXT NOT NULL,
                friend_pk TEXT NOT NULL,
                following_count INTEGER NOT NULL,
                PRIMARY KEY (scan_id, friend_username),
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            );
            CREATE TABLE IF NOT EXISTS following (
                scan_id INTEGER NOT NULL,
                friend_username TEXT NOT NULL,
                target_username TEXT NOT NULL,
                target_pk TEXT NOT NULL,
                full_name TEXT NOT NULL,
                PRIMARY KEY (scan_id, friend_username, target_username),
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            );
            CREATE TABLE IF NOT EXISTS changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                friend_username TEXT NOT NULL,
                op TEXT NOT NULL,
                target_username TEXT NOT NULL,
                full_name TEXT NOT NULL,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            );
            CREATE INDEX IF NOT EXISTS idx_changes_scan ON changes(scan_id);
            CREATE INDEX IF NOT EXISTS idx_following_friend ON following(friend_username, scan_id);
        """)


def has_scans() -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM scans LIMIT 1").fetchone()
        return row is not None


def latest_snapshot(friend_username: str) -> tuple[int | None, dict[str, FollowingEntry]]:
    """Retourne (following_count, {username: entry}) du dernier scan."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT sn.scan_id, sn.following_count
            FROM snapshots sn
            JOIN scans s ON s.id = sn.scan_id
            WHERE sn.friend_username = ?
            ORDER BY s.id DESC LIMIT 1
            """,
            (friend_username,),
        ).fetchone()
        if not row:
            return None, {}
        scan_id = row["scan_id"]
        count = row["following_count"]
        rows = conn.execute(
            """
            SELECT target_username, target_pk, full_name
            FROM following
            WHERE scan_id = ? AND friend_username = ?
            """,
            (scan_id, friend_username),
        ).fetchall()
        entries = {
            r["target_username"]: FollowingEntry(
                username=r["target_username"],
                pk=r["target_pk"],
                full_name=r["full_name"],
            )
            for r in rows
        }
        return count, entries


def save_scan_with_following(
    results: list[tuple[FriendResult, list[FollowingEntry]]],
) -> tuple[int, Path]:
    now = datetime.now()
    label = now.strftime("%Y-%m-%d %H:%M:%S")
    scanned_at = now.isoformat(timespec="seconds")

    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO scans (scanned_at, label) VALUES (?, ?)",
            (scanned_at, label),
        )
        scan_id = cur.lastrowid

        for r, following_list in results:
            if r.skipped:
                continue
            conn.execute(
                """
                INSERT INTO snapshots (scan_id, friend_username, friend_pk, following_count)
                VALUES (?, ?, ?, ?)
                """,
                (scan_id, r.friend_username, r.friend_pk, r.new_count),
            )
            for e in following_list:
                conn.execute(
                    """
                    INSERT INTO following
                    (scan_id, friend_username, target_username, target_pk, full_name)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (scan_id, r.friend_username, e.username, e.pk, e.full_name),
                )
            for c in r.added:
                conn.execute(
                    """
                    INSERT INTO changes (scan_id, friend_username, op, target_username, full_name)
                    VALUES (?, ?, 'add', ?, ?)
                    """,
                    (scan_id, r.friend_username, c.username, c.full_name),
                )
            for c in r.removed:
                conn.execute(
                    """
                    INSERT INTO changes (scan_id, friend_username, op, target_username, full_name)
                    VALUES (?, ?, 'remove', ?, ?)
                    """,
                    (scan_id, r.friend_username, c.username, c.full_name),
                )
        conn.commit()

    journal_path = write_journal(scan_id, label, results)
    return scan_id, journal_path


def write_journal(
    scan_id: int,
    label: str,
    results: list[tuple[FriendResult, list[FollowingEntry]]],
) -> Path:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    safe = label.replace(":", "-").replace(" ", "T")
    path = JOURNAL_DIR / f"{safe}.log"
    lines = [f"=== Scan {label} (id={scan_id}) ===", ""]

    for r, _ in results:
        if r.skipped:
            lines.append(f"@{r.friend_username}  ignoré ({r.skip_reason})")
            continue
        if r.unchanged:
            lines.append(f"@{r.friend_username}  inchangé ({r.new_count} abonnements)")
            continue
        old = r.old_count if r.old_count is not None else "?"
        lines.append(f"@{r.friend_username}  ({old} → {r.new_count})")
        for c in r.added:
            lines.append(f"+ @{c.username}  {c.full_name}")
        for c in r.removed:
            lines.append(f"- @{c.username}  {c.full_name}")
        lines.append("")

    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def list_scans() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.scanned_at, s.label,
                   (SELECT COUNT(*) FROM changes c WHERE c.scan_id = s.id) AS change_count
            FROM scans s
            ORDER BY s.id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_scan(scan_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        if not row:
            return None
        changes = conn.execute(
            """
            SELECT friend_username, op, target_username, full_name
            FROM changes WHERE scan_id = ?
            ORDER BY friend_username, op, target_username
            """,
            (scan_id,),
        ).fetchall()
        snapshots = conn.execute(
            """
            SELECT friend_username, friend_pk, following_count
            FROM snapshots WHERE scan_id = ?
            """,
            (scan_id,),
        ).fetchall()
        return {
            "scan": dict(row),
            "changes": [dict(c) for c in changes],
            "snapshots": [dict(s) for s in snapshots],
        }


def scan_neighbors(scan_id: int) -> dict:
    scans = list_scans()
    ids = [s["id"] for s in scans]
    if scan_id not in ids:
        return {"prev_id": None, "next_id": None, "index": -1, "total": len(ids)}
    idx = ids.index(scan_id)
    return {
        "prev_id": ids[idx - 1] if idx > 0 else None,
        "next_id": ids[idx + 1] if idx < len(ids) - 1 else None,
        "index": idx,
        "total": len(ids),
    }
