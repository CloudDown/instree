"""Stockage SQLite + journal texte."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from instree.core.config import db_path, journal_dir


@dataclass
class FollowingEntry:
    username: str
    pk: str
    full_name: str
    following_count: int = 0
    is_verified: bool = False


@dataclass
class PersonChange:
    subject_username: str
    subject_full_name: str
    username: str
    full_name: str
    op: str  # sub_add | sub_remove | sub_gone
    is_verified: bool = False


@dataclass
class PersonSnapshot:
    person_username: str
    following_count: int
    tracked_count: int
    is_complete: bool = True
    pagination_cursor: str = ""


@dataclass
class ScanDraft:
    account_username: str
    is_baseline: bool
    following_count: int
    follower_count: int
    phase: str  # mutuals_following | mutuals_followers | watch
    following_max_id: str = ""
    followers_max_id: str = ""


@dataclass
class ScanResult:
    username: str
    old_count: int | None
    following_count: int
    follower_count: int
    tracked_count: int
    added: list[FollowingEntry]
    removed: list[FollowingEntry]
    person_changes: list[PersonChange]
    unchanged: bool
    person_snapshots: list[tuple[str, list[FollowingEntry], int]] | None = None
    gone: list[FollowingEntry] | None = None


def _open_db() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _connect() -> sqlite3.Connection:
    """Connexion SQLite du profil actif (crée le schéma si besoin)."""
    conn = _open_db()
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='changes'"
    ).fetchone()
    if row:
        return conn
    conn.close()
    init_db()
    return _open_db()


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
    if "is_verified" not in cols:
        conn.execute(
            "ALTER TABLE following ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0"
        )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(changes)")}
    if "old_count" not in cols:
        conn.execute("ALTER TABLE changes ADD COLUMN old_count INTEGER")
    if "new_count" not in cols:
        conn.execute("ALTER TABLE changes ADD COLUMN new_count INTEGER")
    if "subject_username" not in cols:
        conn.execute("ALTER TABLE changes ADD COLUMN subject_username TEXT")
    if "is_verified" not in cols:
        conn.execute(
            "ALTER TABLE changes ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0"
        )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(person_following)")}
    if "is_verified" not in cols:
        conn.execute(
            "ALTER TABLE person_following ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0"
        )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(scans)")}
    if "follower_count" not in cols:
        conn.execute("ALTER TABLE scans ADD COLUMN follower_count INTEGER NOT NULL DEFAULT 0")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(person_snapshots)")}
    if "is_complete" not in cols:
        conn.execute(
            "ALTER TABLE person_snapshots ADD COLUMN is_complete INTEGER NOT NULL DEFAULT 1"
        )
    if "pagination_cursor" not in cols:
        conn.execute("ALTER TABLE person_snapshots ADD COLUMN pagination_cursor TEXT NOT NULL DEFAULT ''")


def init_db() -> None:
    with _open_db() as conn:
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
                is_verified INTEGER NOT NULL DEFAULT 0,
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
                is_verified INTEGER NOT NULL DEFAULT 0,
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
                is_verified INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (person_username, target_username)
            );
            CREATE TABLE IF NOT EXISTS account_flags (
                username TEXT PRIMARY KEY,
                is_verified INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS scan_drafts (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                account_username TEXT NOT NULL,
                is_baseline INTEGER NOT NULL,
                following_count INTEGER NOT NULL,
                follower_count INTEGER NOT NULL,
                phase TEXT NOT NULL,
                following_max_id TEXT NOT NULL DEFAULT '',
                followers_max_id TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS draft_friendships (
                kind TEXT NOT NULL,
                pk TEXT NOT NULL,
                username TEXT NOT NULL,
                full_name TEXT NOT NULL,
                following_count INTEGER NOT NULL DEFAULT 0,
                is_verified INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL,
                PRIMARY KEY (kind, pk)
            );
            CREATE INDEX IF NOT EXISTS idx_changes_scan ON changes(scan_id);
            CREATE INDEX IF NOT EXISTS idx_person_following ON person_following(person_username);
        """)
        _migrate(conn)


def _remember_verified_conn(conn: sqlite3.Connection, usernames: list[str]) -> None:
    """Mémorise des comptes vérifiés et propage le flag sur l'historique."""
    for username in usernames:
        u = (username or "").lstrip("@").strip()
        if not u:
            continue
        conn.execute(
            """
            INSERT INTO account_flags (username, is_verified) VALUES (?, 1)
            ON CONFLICT(username) DO UPDATE SET is_verified = 1
            """,
            (u,),
        )
        conn.execute(
            "UPDATE changes SET is_verified = 1 WHERE username = ? AND is_verified = 0",
            (u,),
        )
        conn.execute(
            """
            UPDATE person_following
            SET is_verified = 1
            WHERE target_username = ? AND is_verified = 0
            """,
            (u,),
        )
        conn.execute(
            "UPDATE following SET is_verified = 1 WHERE username = ? AND is_verified = 0",
            (u,),
        )


def remember_verified(usernames: list[str]) -> None:
    if not usernames:
        return
    with _connect() as conn:
        _remember_verified_conn(conn, usernames)
        conn.commit()


def known_verified_usernames() -> set[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT username FROM account_flags WHERE is_verified = 1"
        ).fetchall()
        return {r["username"] for r in rows}


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
            SELECT username, pk, full_name, following_count, is_verified
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
                is_verified=bool(r["is_verified"]),
            )
            for r in rows
        ]
        return row["following_count"], row["follower_count"], entries


def get_person_snapshot(person_username: str) -> PersonSnapshot | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT person_username, following_count, tracked_count,
                   is_complete, pagination_cursor
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
            is_complete=bool(row["is_complete"] if "is_complete" in row.keys() else 1),
            pagination_cursor=str(row["pagination_cursor"] or "")
            if "pagination_cursor" in row.keys()
            else "",
        )


def get_person_following(person_username: str) -> list[FollowingEntry]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT target_username AS username, target_pk AS pk, full_name,
                   0 AS following_count, is_verified
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
                is_verified=bool(r["is_verified"]),
            )
            for r in rows
        ]


def _save_person_snapshot_conn(
    conn: sqlite3.Connection,
    person_username: str,
    entries: list[FollowingEntry],
    following_count: int,
    scan_id: int,
    *,
    is_complete: bool = True,
    pagination_cursor: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO person_snapshots
        (person_username, following_count, tracked_count, updated_scan_id,
         is_complete, pagination_cursor)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(person_username) DO UPDATE SET
            following_count = excluded.following_count,
            tracked_count = excluded.tracked_count,
            updated_scan_id = excluded.updated_scan_id,
            is_complete = excluded.is_complete,
            pagination_cursor = excluded.pagination_cursor
        """,
        (
            person_username,
            following_count,
            len(entries),
            scan_id,
            1 if is_complete else 0,
            pagination_cursor or "",
        ),
    )
    conn.execute(
        "DELETE FROM person_following WHERE person_username = ?",
        (person_username,),
    )
    for i, e in enumerate(entries):
        conn.execute(
            """
            INSERT INTO person_following
            (person_username, target_username, target_pk, full_name, position, is_verified)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                person_username,
                e.username,
                e.pk,
                e.full_name,
                i,
                1 if e.is_verified else 0,
            ),
        )


def save_person_snapshot(
    person_username: str,
    entries: list[FollowingEntry],
    following_count: int,
    *,
    scan_id: int = 0,
    is_complete: bool = True,
    pagination_cursor: str = "",
) -> None:
    """Checkpoint immédiat (reprise après crash / cancel / rate-limit)."""
    with _connect() as conn:
        _save_person_snapshot_conn(
            conn,
            person_username,
            entries,
            following_count,
            scan_id,
            is_complete=is_complete,
            pagination_cursor=pagination_cursor,
        )
        verified = [e.username for e in entries if e.is_verified]
        if verified:
            _remember_verified_conn(conn, verified)
        conn.commit()


def clear_scan_draft() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM scan_drafts")
        conn.execute("DELETE FROM draft_friendships")
        conn.commit()


def clear_person_watch_data() -> None:
    """Efface snapshots et listes d'abonnements des mutuels suivis (baseline complète)."""
    with _connect() as conn:
        conn.execute("DELETE FROM person_following")
        conn.execute("DELETE FROM person_snapshots")
        conn.commit()


def reset_baseline_state() -> None:
    """Brouillon de reprise + données watch par mutuel — repartir de zéro."""
    clear_scan_draft()
    clear_person_watch_data()


def get_scan_draft() -> ScanDraft | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM scan_drafts WHERE id = 1").fetchone()
        if not row:
            return None
        return ScanDraft(
            account_username=row["account_username"],
            is_baseline=bool(row["is_baseline"]),
            following_count=int(row["following_count"]),
            follower_count=int(row["follower_count"]),
            phase=str(row["phase"]),
            following_max_id=str(row["following_max_id"] or ""),
            followers_max_id=str(row["followers_max_id"] or ""),
        )


def upsert_scan_draft(draft: ScanDraft) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO scan_drafts
            (id, account_username, is_baseline, following_count, follower_count,
             phase, following_max_id, followers_max_id, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                account_username = excluded.account_username,
                is_baseline = excluded.is_baseline,
                following_count = excluded.following_count,
                follower_count = excluded.follower_count,
                phase = excluded.phase,
                following_max_id = excluded.following_max_id,
                followers_max_id = excluded.followers_max_id,
                updated_at = excluded.updated_at
            """,
            (
                draft.account_username,
                1 if draft.is_baseline else 0,
                draft.following_count,
                draft.follower_count,
                draft.phase,
                draft.following_max_id,
                draft.followers_max_id,
                now,
            ),
        )
        conn.commit()


def _draft_kind_mutuals() -> str:
    return "mutuals"


def _draft_kind_following() -> str:
    return "following"


def _draft_kind_followers() -> str:
    return "followers"


def save_draft_friendships(kind: str, entries: list[FollowingEntry]) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM draft_friendships WHERE kind = ?", (kind,))
        for i, e in enumerate(entries):
            conn.execute(
                """
                INSERT INTO draft_friendships
                (kind, pk, username, full_name, following_count, is_verified, position)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    e.pk,
                    e.username,
                    e.full_name,
                    e.following_count,
                    1 if e.is_verified else 0,
                    i,
                ),
            )
        conn.commit()


def load_draft_friendships(kind: str) -> list[FollowingEntry]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT pk, username, full_name, following_count, is_verified
            FROM draft_friendships
            WHERE kind = ?
            ORDER BY position
            """,
            (kind,),
        ).fetchall()
        return [
            FollowingEntry(
                username=r["username"],
                pk=r["pk"],
                full_name=r["full_name"],
                following_count=int(r["following_count"] or 0),
                is_verified=bool(r["is_verified"]),
            )
            for r in rows
        ]


def has_draft_mutuals() -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM draft_friendships WHERE kind = ? LIMIT 1",
            (_draft_kind_mutuals(),),
        ).fetchone()
        return row is not None


def load_draft_mutuals() -> list[FollowingEntry]:
    return load_draft_friendships(_draft_kind_mutuals())


def save_draft_mutuals(entries: list[FollowingEntry]) -> None:
    save_draft_friendships(_draft_kind_mutuals(), entries)


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

        verified_names: list[str] = []
        for i, e in enumerate(following):
            conn.execute(
                """
                INSERT INTO following
                (scan_id, position, username, pk, full_name, following_count, is_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id,
                    i,
                    e.username,
                    e.pk,
                    e.full_name,
                    e.following_count,
                    1 if e.is_verified else 0,
                ),
            )
            if e.is_verified:
                verified_names.append(e.username)
        for c in result.added:
            conn.execute(
                """
                INSERT INTO changes (scan_id, op, username, full_name, is_verified)
                VALUES (?, 'add', ?, ?, ?)
                """,
                (scan_id, c.username, c.full_name, 1 if c.is_verified else 0),
            )
            if c.is_verified:
                verified_names.append(c.username)
        for c in result.removed:
            conn.execute(
                """
                INSERT INTO changes (scan_id, op, username, full_name, is_verified)
                VALUES (?, 'remove', ?, ?, ?)
                """,
                (scan_id, c.username, c.full_name, 1 if c.is_verified else 0),
            )
            if c.is_verified:
                verified_names.append(c.username)
        for c in result.gone or []:
            conn.execute(
                """
                INSERT INTO changes (scan_id, op, username, full_name, is_verified)
                VALUES (?, 'gone', ?, ?, ?)
                """,
                (scan_id, c.username, c.full_name, 1 if c.is_verified else 0),
            )
            if c.is_verified:
                verified_names.append(c.username)
        for c in result.person_changes:
            conn.execute(
                """
                INSERT INTO changes
                (scan_id, op, username, full_name, subject_username, is_verified)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id,
                    c.op,
                    c.username,
                    c.full_name,
                    c.subject_username,
                    1 if c.is_verified else 0,
                ),
            )
            if c.is_verified:
                verified_names.append(c.username)
        if result.person_snapshots:
            for person_username, entries, fc in result.person_snapshots:
                _save_person_snapshot_conn(conn, person_username, entries, fc, scan_id)
                for e in entries:
                    if e.is_verified:
                        verified_names.append(e.username)
        _remember_verified_conn(conn, verified_names)
        conn.execute("DELETE FROM scan_drafts")
        conn.execute("DELETE FROM draft_friendships")
        conn.commit()

    return scan_id, write_journal(scan_id, label, result)


def write_journal(scan_id: int, label: str, result: ScanResult) -> Path:
    JOURNAL_DIR = journal_dir()
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    safe = label.replace(":", "-").replace(" ", "T")
    path = JOURNAL_DIR / f"{safe}.log"
    lines = [f"=== Scan {label} (id={scan_id}) ===", ""]

    has_person = bool(result.person_changes)
    has_list = bool(result.added or result.removed or result.gone)

    if result.unchanged:
        lines.append(
            f"@{result.username}  inchangé "
            f"({result.tracked_count}/{result.following_count} abonnements suivis)"
        )
    elif not has_list and not has_person:
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
        for c in result.gone or []:
            lines.append(f"x @{c.username}  {c.full_name}")

        by_subject: dict[str, list[PersonChange]] = {}
        for c in result.person_changes:
            by_subject.setdefault(c.subject_username, []).append(c)

        for subject, changes in sorted(by_subject.items()):
            snap = next((c for c in changes), None)
            sub_name = snap.subject_full_name if snap else ""
            adds = [c for c in changes if c.op == "sub_add"]
            rems = [c for c in changes if c.op == "sub_remove"]
            gones = [c for c in changes if c.op == "sub_gone"]
            lines.append(f"~ @{subject}  {sub_name}".strip())
            for c in adds:
                lines.append(f"  + @{c.username}  {c.full_name}")
            for c in rems:
                lines.append(f"  - @{c.username}  {c.full_name}")
            for c in gones:
                lines.append(f"  x @{c.username}  {c.full_name}")

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


def get_changes_search_index() -> list[dict]:
    """Index léger pour la recherche (mutuels + abonnements de mutuels)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT scan_id, op, username, full_name, subject_username
            FROM changes
            ORDER BY scan_id, id
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_scan(scan_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        if not row:
            return None
        mutual_usernames = {
            r["username"]
            for r in conn.execute(
                "SELECT username FROM following WHERE scan_id = ?",
                (scan_id,),
            ).fetchall()
        }
        verified_usernames = {
            r["username"]
            for r in conn.execute(
                "SELECT username FROM account_flags WHERE is_verified = 1"
            ).fetchall()
        }
        changes = conn.execute(
            """
            SELECT op, username, full_name, old_count, new_count,
                   subject_username, is_verified
            FROM changes WHERE scan_id = ?
            ORDER BY
                CASE op
                    WHEN 'add' THEN 0
                    WHEN 'sub_add' THEN 1
                    WHEN 'count' THEN 2
                    WHEN 'sub_remove' THEN 3
                    WHEN 'remove' THEN 4
                    WHEN 'sub_gone' THEN 5
                    WHEN 'gone' THEN 6
                    ELSE 7
                END,
                COALESCE(subject_username, ''),
                username
            """,
            (scan_id,),
        ).fetchall()
        change_rows = []
        for c in changes:
            item = dict(c)
            item["is_verified"] = bool(item.get("is_verified")) or (
                item["username"] in verified_usernames
            )
            item["is_mutual"] = (
                item["op"] in ("sub_add", "sub_remove", "sub_gone")
                and item["username"] in mutual_usernames
            )
            change_rows.append(item)
        return {"scan": dict(row), "changes": change_rows}


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


# Couleurs de clusters (lisibles sur fond noir)
_CLUSTER_COLORS = (
    "#60a5fa",
    "#34d399",
    "#f472b6",
    "#fb923c",
    "#a78bfa",
    "#2dd4bf",
    "#f87171",
    "#fbbf24",
    "#38bdf8",
    "#c084fc",
    "#4ade80",
    "#e879f9",
    "#22d3ee",
    "#fdba74",
    "#86efac",
)
_ISOLATE_COLOR = "#6b7280"
_ROOT_COLOR = "#facc15"


def _build_mutual_graph(mutuals: set[str], directed: list[tuple[str, str]]):
    """Graphe non orienté des mutuels (réciproque fort, one-way faible)."""
    import networkx as nx

    edge_set = set(directed)
    graph = nx.Graph()
    graph.add_nodes_from(mutuals)
    for a, b in directed:
        if a not in mutuals or b not in mutuals:
            continue
        if a < b and (b, a) in edge_set:
            graph.add_edge(a, b, weight=2.0)
        elif (b, a) not in edge_set and not graph.has_edge(a, b):
            graph.add_edge(a, b, weight=0.5)
    return graph


def _inter_weight(graph, a: set[str], b: set[str]) -> float:
    total = 0.0
    for u in a:
        for _, v, data in graph.edges(u, data=True):
            if v in b:
                total += float(data.get("weight", 1.0))
    return total


def _merge_communities_to_k(graph, communities: list[set[str]], k: int) -> list[set[str]]:
    """Fusionne les communautés les plus liées jusqu'à exactement k groupes."""
    groups = [set(c) for c in communities]
    while len(groups) > k:
        best_i, best_j, best_w = 0, 1, -1.0
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                w = _inter_weight(graph, groups[i], groups[j])
                if w > best_w or (
                    w == best_w
                    and (
                        len(groups[i]) + len(groups[j])
                        < len(groups[best_i]) + len(groups[best_j])
                    )
                ):
                    best_i, best_j, best_w = i, j, w
        merged = groups[best_i] | groups[best_j]
        groups = [g for idx, g in enumerate(groups) if idx not in (best_i, best_j)]
        groups.append(merged)
    return groups


def _louvain_multis(graph, resolution: float) -> list[set[str]]:
    import networkx as nx

    communities = nx.community.louvain_communities(
        graph, weight="weight", resolution=resolution, seed=42
    )
    return [set(c) for c in communities if len(c) >= 2]


def _cluster_mutuals(
    mutuals: set[str],
    directed: list[tuple[str, str]],
    target_groups: int | None = None,
) -> tuple[dict[str, int], int]:
    """Communautés Louvain sur les mutuels.

    Retourne (cluster_of, max_groups).
    Isolés (communauté size 1) → cluster -1.
    Si target_groups ≥ 2 : force exactement ce nombre (clampé à max possible).
    """
    graph = _build_mutual_graph(mutuals, directed)
    if graph.number_of_nodes() == 0:
        return {}, 0

    multi = _louvain_multis(graph, 1.0)
    # Max théorique : mutuels avec au moins un lien (peuvent former des paires)
    linked = {n for n in graph.nodes if graph.degree(n) > 0}
    max_groups = max(1, min(20, len(linked) // 2)) if linked else 1
    # Affiner max avec une résolution haute (plus de communautés possibles)
    fine = _louvain_multis(graph, 3.0)
    if len(fine) > max_groups:
        max_groups = min(20, len(fine))
    max_groups = max(max_groups, len(multi), 1)

    if target_groups is not None and target_groups >= 2:
        k = min(max(2, target_groups), max_groups)
        if len(multi) < k:
            for res in (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0):
                candidate = _louvain_multis(graph, res)
                if len(candidate) >= k:
                    multi = candidate
                    break
                if len(candidate) > len(multi):
                    multi = candidate
            # Si encore insuffisant : chaque paire liée comme graine max
            if len(multi) < k:
                multi = fine if len(fine) >= len(multi) else multi
        if len(multi) > k:
            multi = _merge_communities_to_k(graph, multi, k)
        elif len(multi) < k:
            # Impossible d'atteindre k : on garde ce qu'on a
            pass

    assigned: set[str] = set()
    ranked = sorted(multi, key=len, reverse=True)
    cluster_of: dict[str, int] = {}
    for cid, members in enumerate(ranked):
        for u in members:
            cluster_of[u] = cid
            assigned.add(u)

    for u in mutuals:
        if u not in cluster_of:
            cluster_of[u] = -1

    return cluster_of, max_groups


def get_graph_data(groups: int | None = None) -> dict | None:
    """Graphe mutuels : groupes sociaux colorés distinctement.

    groups: nombre cible de groupes (≥2), ou None pour Louvain libre (auto).
    """
    with _connect() as conn:
        scan = conn.execute(
            """
            SELECT id, username, scanned_at, following_count, tracked_count
            FROM scans
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if not scan:
            return None

        root = scan["username"]
        mutual_rows = conn.execute(
            """
            SELECT username, pk, full_name, following_count
            FROM following
            WHERE scan_id = ?
            ORDER BY position
            """,
            (scan["id"],),
        ).fetchall()
        mutual_set = {r["username"] for r in mutual_rows}

        directed: list[tuple[str, str]] = []
        if mutual_set:
            placeholders = ",".join("?" for _ in mutual_set)
            params = list(mutual_set) + list(mutual_set)
            edge_sql = f"""
                SELECT person_username, target_username
                FROM person_following
                WHERE person_username IN ({placeholders})
                  AND target_username IN ({placeholders})
            """
            for r in conn.execute(edge_sql, params).fetchall():
                src, tgt = r["person_username"], r["target_username"]
                if src and tgt and src != tgt:
                    directed.append((src, tgt))

        target = groups if groups is not None and groups >= 2 else None
        cluster_of, max_groups = _cluster_mutuals(mutual_set, directed, target)
        social_clusters = {c for c in cluster_of.values() if c >= 0}
        groups_mode = "fixed" if target is not None else "auto"

        nodes: list[dict] = [
            {
                "id": root,
                "name": f"@{root}",
                "full_name": "",
                "group": "root",
                "cluster": -2,
                "color": _ROOT_COLOR,
                "val": 3,
            }
        ]
        for r in mutual_rows:
            u = r["username"]
            cluster = cluster_of.get(u, -1)
            if cluster < 0:
                color = _ISOLATE_COLOR
            else:
                color = _CLUSTER_COLORS[cluster % len(_CLUSTER_COLORS)]
            nodes.append(
                {
                    "id": u,
                    "name": f"@{u}",
                    "full_name": r["full_name"] or "",
                    "group": "isolate" if cluster < 0 else "cluster",
                    "cluster": cluster,
                    "color": color,
                    "val": 1 if cluster < 0 else 1.2,
                }
            )

        # Liens affichés : abonnements intra-groupe + ponts inter-groupes
        links: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for a, b in directed:
            if a not in mutual_set or b not in mutual_set:
                continue
            ca = cluster_of.get(a, -1)
            cb = cluster_of.get(b, -1)
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            if ca == cb:
                if ca < 0:
                    continue
                links.append({"source": key[0], "target": key[1], "kind": "social"})
            else:
                links.append({"source": key[0], "target": key[1], "kind": "bridge"})

        return {
            "scan": {
                "id": scan["id"],
                "username": root,
                "scanned_at": scan["scanned_at"],
                "following_count": scan["following_count"],
                "tracked_count": scan["tracked_count"],
            },
            "nodes": nodes,
            "links": links,
            "stats": {
                "nodes": len(nodes),
                "links": len(links),
                "mutuals": len(mutual_rows),
                "clusters": len(social_clusters),
                "max_groups": max(max_groups, len(social_clusters), 1),
                "groups_mode": groups_mode,
            },
        }
