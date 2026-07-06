"""Scan incrémental des N abonnements d'un compte."""
from dataclasses import dataclass

from instagrapi import Client

from instree.config import Settings
from instree.ig import IgUser, fetch_following, user_profile
from instree.session import session_user
from instree.store import (
    FollowingEntry,
    ScanResult,
    has_scans,
    init_db,
    latest_following,
    save_scan,
)


@dataclass
class ScanSummary:
    scan_id: int | None
    username: str
    tracked: int
    following_count: int
    added: int
    removed: int
    unchanged: bool
    journal_path: str | None


def _to_entry(u: IgUser) -> FollowingEntry:
    return FollowingEntry(username=u.username, pk=u.pk, full_name=u.full_name)


def _diff(
    stored: list[FollowingEntry],
    live: list[FollowingEntry],
) -> tuple[list[FollowingEntry], list[FollowingEntry]]:
    stored_set = {e.username for e in stored}
    live_set = {e.username for e in live}
    added = [e for e in live if e.username not in stored_set]
    removed = [e for e in stored if e.username not in live_set]
    return added, removed


def run_scan(
    ig: Client,
    settings: Settings,
    *,
    init: bool = False,
    full: bool = False,
) -> ScanSummary:
    init_db()
    is_baseline = init or not has_scans()
    force_full = full or is_baseline

    username = settings.username or session_user(ig)
    limit = settings.n

    try:
        profile = user_profile(ig, username)
    except Exception as e:
        raise RuntimeError(f"Impossible de charger @{username} : {e}") from e

    old_count, stored = latest_following(profile.username)
    need_full = (
        force_full
        or old_count is None
        or profile.following_count != old_count
    )

    if not need_full:
        tracked = len(stored)
        return ScanSummary(
            scan_id=None,
            username=profile.username,
            tracked=tracked,
            following_count=profile.following_count,
            added=0,
            removed=0,
            unchanged=True,
            journal_path=None,
        )

    try:
        live_users = fetch_following(
            ig,
            profile.pk,
            limit=limit,
            page_sleep=settings.page_sleep,
        )
    except Exception as e:
        raise RuntimeError(f"Erreur fetch abonnements : {e}") from e

    live = [_to_entry(u) for u in live_users]
    if is_baseline or not stored:
        added, removed = [], []
    else:
        added, removed = _diff(stored, live)

    result = ScanResult(
        username=profile.username,
        user_pk=profile.pk,
        old_count=old_count,
        following_count=profile.following_count,
        tracked_count=len(live),
        added=added,
        removed=removed,
        unchanged=not added and not removed and old_count is not None,
        skipped=False,
    )
    scan_id, journal_path = save_scan(result, live)

    return ScanSummary(
        scan_id=scan_id,
        username=profile.username,
        tracked=len(live),
        following_count=profile.following_count,
        added=len(added),
        removed=len(removed),
        unchanged=False,
        journal_path=str(journal_path),
    )
