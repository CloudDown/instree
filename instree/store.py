"""Stockage SQLite + journal texte."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from instree.config import db_path, journal_dir


@dataclass
class FollowingEntry:
    username: str
    pk: str
    full_name: str
    following_count: int = 0


@dataclass
class CountChange:
    username: str
    full_name: str
    old_count: int
    new_count: int


@dataclass
class PersonChange:
    subject_username: str
    subject_full_name: str
    username: str
    full_name: str
    op: str  # sub_add | sub_remove


@dataclass
class PersonSnapshot:
    person_username: str
    following_count: int
    tracked_count: int


@dataclass
class ScanResult:
    username: str
    user_pk: str
    old_count: int | None
    following_count: int
    follower_count: int
    tracked_count: int
    added: list[FollowingEntry]
    removed: list[FollowingEntry]
    count_changes: list[CountChange]
    person_changes: list[PersonChange]
    unchanged: bool
    skipped: bool
    skip_reason: str = ""
    person_snapshots: list[tuple[str, list[FollowingEntry], int]] | None = None


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _drop_legacy(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='snapshots'"
    ).fetchone()
    if row and row[0] and "friend_username" in row[0]:
        conn.executescript("""
            DROP TABLE IF EXISTS changes;
            DROP TABLE IF EXISTS following;
            DROP TABLE IF EXISTS snapshots;
            DROP TABLE IF EXISTS scans;
        """)


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(following)")}
    if "following_count" not in cols:
        conn.execute(
            "ALTER TABLE following ADD COLUMN following_count INTEGER NOT NULL DEFAULT 0"
        )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(changes)")}
    if "old_count" not in cols:
        conn.execute("ALTER TABLE changes ADD COLUMN old_count INTEGER")
    if "new_count" not in cols:
        conn.execute("ALTER TABLE changes ADD COLUMN new_count INTEGER")
    if "subject_username" not in cols:
        conn.execute("ALTER TABLE changes ADD COLUMN subject_username TEXT")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(scans)")}
    if "follower_count" not in cols:
        conn.execute("ALTER TABLE scans ADD COLUMN follower_count INTEGER NOT NULL DEFAULT 0")


def init_db() -> None:
    with _connect() as conn:
        _drop_legacy(conn)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scanned_at TEXT NOT NULL,
                label TEXT NOT NULL,
                username TEXT NOT NULL,
                following_count INTEGER NOT NULL,
                tracked_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS following (
                scan_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                username TEXT NOT NULL,
                pk TEXT NOT NULL,
                full_name TEXT NOT NULL,
                following_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (scan_id, username),
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            );
            CREATE TABLE IF NOT EXISTS changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                op TEXT NOT NULL,
                username TEXT NOT NULL,
                full_name TEXT NOT NULL,
                old_count INTEGER,
                new_count INTEGER,
                subject_username TEXT,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            );
            CREATE TABLE IF NOT EXISTS person_snapshots (
                person_username TEXT PRIMARY KEY,
                following_count INTEGER NOT NULL,
                tracked_count INTEGER NOT NULL,
                updated_scan_id INTEGER NOT NULL,
                FOREIGN KEY (updated_scan_id) REFERENCES scans(id)
            );
            CREATE TABLE IF NOT EXISTS person_following (
                person_username TEXT NOT NULL,
                target_username TEXT NOT NULL,
                target_pk TEXT NOT NULL,
                full_name TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (person_username, target_username)
            );
            CREATE INDEX IF NOT EXISTS idx_changes_scan ON changes(scan_id);
            CREATE INDEX IF NOT EXISTS idx_person_following ON person_following(person_username);
        """)
        _migrate(conn)


def has_scans() -> bool:
    with _connect() as conn:
        return conn.execute("SELECT 1 FROM scans LIMIT 1").fetchone() is not None


def latest_following(username: str) -> tuple[int | None, int | None, list[FollowingEntry]]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT s.id, s.following_count, s.follower_count
            FROM scans s
            WHERE s.username = ?
            ORDER BY s.id DESC LIMIT 1
            """,
            (username,),
        ).fetchone()
        if not row:
            return None, None, []
        rows = conn.execute(
            """
            SELECT username, pk, full_name, following_count
            FROM following
            WHERE scan_id = ?
            ORDER BY position
            """,
            (row["id"],),
        ).fetchall()
        entries = [
            FollowingEntry(
                username=r["username"],
                pk=r["pk"],
                full_name=r["full_name"],
                following_count=int(r["following_count"] or 0),
            )
            for r in rows
        ]
        return row["following_count"], row["follower_count"], entries


def get_person_snapshot(person_username: str) -> PersonSnapshot | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT person_username, following_count, tracked_count
            FROM person_snapshots WHERE person_username = ?
            """,
            (person_username,),
        ).fetchone()
        if not row:
            return None
        return PersonSnapshot(
            person_username=row["person_username"],
            following_count=int(row["following_count"]),
            tracked_count=int(row["tracked_count"]),
        )


def get_person_following(person_username: str) -> list[FollowingEntry]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT target_username AS username, target_pk AS pk, full_name, 0 AS following_count
            FROM person_following
            WHERE person_username = ?
            ORDER BY position
            """,
            (person_username,),
        ).fetchall()
        return [
            FollowingEntry(
                username=r["username"],
                pk=r["pk"],
                full_name=r["full_name"],
                following_count=0,
            )
            for r in rows
        ]


def _save_person_snapshot_conn(
    conn: sqlite3.Connection,
    person_username: str,
    entries: list[FollowingEntry],
    following_count: int,
    scan_id: int,
) -> None:
    conn.execute(
        """
        INSERT INTO person_snapshots
        (person_username, following_count, tracked_count, updated_scan_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(person_username) DO UPDATE SET
            following_count = excluded.following_count,
            tracked_count = excluded.tracked_count,
            updated_scan_id = excluded.updated_scan_id
        """,
        (person_username, following_count, len(entries), scan_id),
    )
    conn.execute(
        "DELETE FROM person_following WHERE person_username = ?",
        (person_username,),
    )
    for i, e in enumerate(entries):
        conn.execute(
            """
            INSERT INTO person_following
            (person_username, target_username, target_pk, full_name, position)
            VALUES (?, ?, ?, ?, ?)
            """,
            (person_username, e.username, e.pk, e.full_name, i),
        )


def delete_person_snapshot(person_username: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM person_following WHERE person_username = ?",
            (person_username,),
        )
        conn.execute(
            "DELETE FROM person_snapshots WHERE person_username = ?",
            (person_username,),
        )
        conn.commit()


def save_scan(result: ScanResult, following: list[FollowingEntry]) -> tuple[int, Path]:
    now = datetime.now()
    label = now.strftime("%Y-%m-%d %H:%M:%S")
    scanned_at = now.isoformat(timespec="seconds")

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO scans (scanned_at, label, username, following_count, follower_count, tracked_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scanned_at,
                label,
                result.username,
                result.following_count,
                result.follower_count,
                result.tracked_count,
            ),
        )
        scan_id = cur.lastrowid

        for i, e in enumerate(following):
            conn.execute(
                """
                INSERT INTO following
                (scan_id, position, username, pk, full_name, following_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (scan_id, i, e.username, e.pk, e.full_name, e.following_count),
            )
        for c in result.added:
            conn.execute(
                "INSERT INTO changes (scan_id, op, username, full_name) VALUES (?, 'add', ?, ?)",
                (scan_id, c.username, c.full_name),
            )
        for c in result.removed:
            conn.execute(
                "INSERT INTO changes (scan_id, op, username, full_name) VALUES (?, 'remove', ?, ?)",
                (scan_id, c.username, c.full_name),
            )
        for c in result.count_changes:
            conn.execute(
                """
                INSERT INTO changes (scan_id, op, username, full_name, old_count, new_count)
                VALUES (?, 'count', ?, ?, ?, ?)
                """,
                (scan_id, c.username, c.full_name, c.old_count, c.new_count),
            )
        for c in result.person_changes:
            conn.execute(
                """
                INSERT INTO changes
                (scan_id, op, username, full_name, subject_username)
                VALUES (?, ?, ?, ?, ?)
                """,
                (scan_id, c.op, c.username, c.full_name, c.subject_username),
            )
        if result.person_snapshots:
            for person_username, entries, fc in result.person_snapshots:
                _save_person_snapshot_conn(conn, person_username, entries, fc, scan_id)
        conn.commit()

    return scan_id, write_journal(scan_id, label, result)


def write_journal(scan_id: int, label: str, result: ScanResult) -> Path:
    JOURNAL_DIR = journal_dir()
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    safe = label.replace(":", "-").replace(" ", "T")
    path = JOURNAL_DIR / f"{safe}.log"
    lines = [f"=== Scan {label} (id={scan_id}) ===", ""]

    has_person = bool(result.person_changes)
    has_list = bool(result.added or result.removed)
    has_count = bool(result.count_changes)

    if result.skipped:
        lines.append(f"@{result.username}  ignoré ({result.skip_reason})")
    elif result.unchanged:
        lines.append(
            f"@{result.username}  inchangé "
            f"({result.tracked_count}/{result.following_count} abonnements suivis)"
        )
    elif not has_list and not has_count and not has_person:
        old = result.old_count if result.old_count is not None else "?"
        lines.append(
            f"@{result.username}  baseline "
            f"({result.tracked_count} abonnements, total {old} → {result.following_count})"
        )
    else:
        old = result.old_count if result.old_count is not None else "?"
        lines.append(f"@{result.username}  ({old} → {result.following_count})")
        for c in result.added:
            lines.append(f"+ @{c.username}  {c.full_name}")
        for c in result.removed:
            lines.append(f"- @{c.username}  {c.full_name}")

        by_subject: dict[str, list[PersonChange]] = {}
        for c in result.person_changes:
            by_subject.setdefault(c.subject_username, []).append(c)

        for subject, changes in sorted(by_subject.items()):
            snap = next((c for c in changes), None)
            sub_name = snap.subject_full_name if snap else ""
            adds = [c for c in changes if c.op == "sub_add"]
            rems = [c for c in changes if c.op == "sub_remove"]
            lines.append(f"~ @{subject}  {sub_name}".strip())
            for c in adds:
                lines.append(f"  + @{c.username}  {c.full_name}")
            for c in rems:
                lines.append(f"  - @{c.username}  {c.full_name}")

    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def list_scans() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.scanned_at, s.label, s.username,
                   s.following_count, s.tracked_count,
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
            SELECT op, username, full_name, old_count, new_count, subject_username
            FROM changes WHERE scan_id = ?
            ORDER BY
                CASE op
                    WHEN 'add' THEN 0
                    WHEN 'sub_add' THEN 1
                    WHEN 'count' THEN 2
                    WHEN 'sub_remove' THEN 3
                    WHEN 'remove' THEN 4
                    ELSE 5
                END,
                COALESCE(subject_username, ''),
                username
            """,
            (scan_id,),
        ).fetchall()
        return {"scan": dict(row), "changes": [dict(c) for c in changes]}


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
