"""Scan incrémental : ta liste d'abonnements + évolution des comptes suivis."""
import time
from dataclasses import dataclass

from instagrapi import Client

from instree.config import Settings
from instree.ig import fetch_following, user_profile
from instree.session import session_user
from instree.store import (
    CountChange,
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
    counts: int
    unchanged: bool
    journal_path: str | None


def _to_entry(u) -> FollowingEntry:
    return FollowingEntry(
        username=u.username,
        pk=u.pk,
        full_name=u.full_name,
        following_count=getattr(u, "following_count", 0) or 0,
    )


def _diff(
    stored: list[FollowingEntry],
    live: list[FollowingEntry],
) -> tuple[list[FollowingEntry], list[FollowingEntry]]:
    stored_set = {e.username for e in stored}
    live_set = {e.username for e in live}
    added = [e for e in live if e.username not in stored_set]
    removed = [e for e in stored if e.username not in live_set]
    return added, removed


def _poll_counts(
    ig: Client,
    entries: list[FollowingEntry],
    stored_map: dict[str, FollowingEntry],
    *,
    sleep: float,
    is_baseline: bool,
    on_progress=None,
) -> tuple[list[CountChange], list[FollowingEntry]]:
    changes: list[CountChange] = []
    updated: list[FollowingEntry] = []

    for i, e in enumerate(entries):
        if on_progress:
            on_progress(i + 1, len(entries), e.username)
        try:
            profile = user_profile(ig, e.username)
        except Exception:
            updated.append(e)
            continue

        entry = FollowingEntry(
            username=profile.username,
            pk=profile.pk,
            full_name=profile.full_name or e.full_name,
            following_count=profile.following_count,
        )
        updated.append(entry)

        if not is_baseline and e.username in stored_map:
            old_fc = stored_map[e.username].following_count
            if old_fc > 0 and profile.following_count != old_fc:
                changes.append(CountChange(
                    username=profile.username,
                    full_name=entry.full_name,
                    old_count=old_fc,
                    new_count=profile.following_count,
                ))

        if i + 1 < len(entries):
            time.sleep(sleep)

    return changes, updated


def run_scan(
    ig: Client,
    settings: Settings,
    *,
    init: bool = False,
    full: bool = False,
    on_progress=None,
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

    old_total, stored_list = latest_following(profile.username)
    stored_map = {e.username: e for e in stored_list}
    need_list = (
        force_full
        or old_total is None
        or profile.following_count != old_total
    )

    added: list[FollowingEntry] = []
    removed: list[FollowingEntry] = []

    if need_list:
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
        if is_baseline or not stored_list:
            added, removed = [], []
        else:
            added, removed = _diff(stored_list, live)
    else:
        live = list(stored_list)

    count_changes, following = _poll_counts(
        ig,
        live,
        stored_map,
        sleep=settings.page_sleep,
        is_baseline=is_baseline,
        on_progress=on_progress,
    )

    if (
        not is_baseline
        and not need_list
        and not added
        and not removed
        and not count_changes
    ):
        return ScanSummary(
            scan_id=None,
            username=profile.username,
            tracked=len(stored_list),
            following_count=profile.following_count,
            added=0,
            removed=0,
            counts=0,
            unchanged=True,
            journal_path=None,
        )

    result = ScanResult(
        username=profile.username,
        user_pk=profile.pk,
        old_count=old_total,
        following_count=profile.following_count,
        tracked_count=len(following),
        added=added,
        removed=removed,
        count_changes=count_changes,
        unchanged=not added and not removed and not count_changes and not is_baseline,
        skipped=False,
    )
    scan_id, journal_path = save_scan(result, following)

    return ScanSummary(
        scan_id=scan_id,
        username=profile.username,
        tracked=len(following),
        following_count=profile.following_count,
        added=len(added),
        removed=len(removed),
        counts=len(count_changes),
        unchanged=False,
        journal_path=str(journal_path),
    )
