"""Scan incrémental : abonnements mutuels + évolution de leurs abonnements."""

import time
from dataclasses import dataclass

from instagrapi import Client

from instree.config import Settings
from instree.ig import fetch_following, fetch_mutuals, user_profile
from instree.session import session_user
from instree.store import (
    CountChange,
    FollowingEntry,
    PersonChange,
    ScanResult,
    delete_person_snapshot,
    get_person_following,
    get_person_snapshot,
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
    person_added: int
    person_removed: int
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


def _fetch_person_following(
    ig: Client,
    pk: str,
    *,
    limit: int,
    page_sleep: float,
) -> list[FollowingEntry]:
    users = fetch_following(ig, pk, limit=limit, page_sleep=page_sleep)
    return [_to_entry(u) for u in users]


def _watch_persons(
    ig: Client,
    entries: list[FollowingEntry],
    *,
    watch_n: int,
    page_sleep: float,
    is_baseline: bool,
    force_full: bool,
    new_usernames: set[str],
    on_progress=None,
) -> tuple[
    list[CountChange],
    list[PersonChange],
    list[FollowingEntry],
    list[tuple[str, list[FollowingEntry], int]],
]:
    count_changes: list[CountChange] = []
    person_changes: list[PersonChange] = []
    updated: list[FollowingEntry] = []
    snapshots: list[tuple[str, list[FollowingEntry], int]] = []
    fetch_limit = watch_n if watch_n > 0 else 0

    for i, e in enumerate(entries):
        if on_progress:
            on_progress(i + 1, len(entries), e.username, "profile")

        try:
            profile = user_profile(ig, e.username)
        except Exception:
            updated.append(e)
            if i + 1 < len(entries):
                time.sleep(page_sleep)
            continue

        entry = FollowingEntry(
            username=profile.username,
            pk=profile.pk,
            full_name=profile.full_name or e.full_name,
            following_count=profile.following_count,
        )
        updated.append(entry)

        snapshot = get_person_snapshot(profile.username)
        need_baseline = (
            force_full
            or is_baseline
            or snapshot is None
            or profile.username in new_usernames
        )
        need_diff = (
            not need_baseline
            and snapshot is not None
            and profile.following_count != snapshot.following_count
        )

        if need_baseline or need_diff:
            if on_progress:
                phase = "baseline" if need_baseline else "fetch"
                on_progress(i + 1, len(entries), profile.username, phase)
            try:
                live = _fetch_person_following(
                    ig,
                    profile.pk,
                    limit=fetch_limit,
                    page_sleep=page_sleep,
                )
            except Exception:
                if need_diff and snapshot is not None:
                    count_changes.append(
                        CountChange(
                            username=profile.username,
                            full_name=entry.full_name,
                            old_count=snapshot.following_count,
                            new_count=profile.following_count,
                        )
                    )
                if i + 1 < len(entries):
                    time.sleep(page_sleep)
                continue

            snapshots.append((profile.username, live, profile.following_count))

            if need_diff and snapshot is not None:
                stored = get_person_following(profile.username)
                added, removed = _diff(stored, live)
                for a in added:
                    person_changes.append(
                        PersonChange(
                            subject_username=profile.username,
                            subject_full_name=entry.full_name,
                            username=a.username,
                            full_name=a.full_name,
                            op="sub_add",
                        )
                    )
                for r in removed:
                    person_changes.append(
                        PersonChange(
                            subject_username=profile.username,
                            subject_full_name=entry.full_name,
                            username=r.username,
                            full_name=r.full_name,
                            op="sub_remove",
                        )
                    )
                if not added and not removed:
                    count_changes.append(
                        CountChange(
                            username=profile.username,
                            full_name=entry.full_name,
                            old_count=snapshot.following_count,
                            new_count=profile.following_count,
                        )
                    )

        if i + 1 < len(entries):
            time.sleep(page_sleep)

    return count_changes, person_changes, updated, snapshots


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

    old_total, old_followers, stored_list = latest_following(profile.username)
    stored_map = {e.username: e for e in stored_list}
    counts_changed = (
        old_total is None
        or profile.following_count != old_total
        or profile.follower_count != old_followers
    )
    need_list = force_full or not stored_list or counts_changed

    added: list[FollowingEntry] = []
    removed: list[FollowingEntry] = []

    if need_list:
        try:
            live_users = fetch_mutuals(
                ig,
                profile.pk,
                limit=limit,
                page_sleep=settings.page_sleep,
            )
        except Exception as e:
            raise RuntimeError(f"Erreur fetch abonnements mutuels : {e}") from e
        live = [_to_entry(u) for u in live_users]
        if is_baseline or not stored_list:
            added, removed = [], []
        else:
            added, removed = _diff(stored_list, live)
    else:
        live = list(stored_list)

    for r in removed:
        delete_person_snapshot(r.username)

    new_usernames = {a.username for a in added}

    count_changes, person_changes, following, person_snapshots = _watch_persons(
        ig,
        live,
        watch_n=settings.watch_n,
        page_sleep=settings.page_sleep,
        is_baseline=is_baseline,
        force_full=force_full,
        new_usernames=new_usernames,
        on_progress=on_progress,
    )

    person_added = sum(1 for c in person_changes if c.op == "sub_add")
    person_removed = sum(1 for c in person_changes if c.op == "sub_remove")

    if (
        not is_baseline
        and not need_list
        and not added
        and not removed
        and not count_changes
        and not person_changes
        and not person_snapshots
    ):
        return ScanSummary(
            scan_id=None,
            username=profile.username,
            tracked=len(stored_list),
            following_count=profile.following_count,
            added=0,
            removed=0,
            counts=0,
            person_added=0,
            person_removed=0,
            unchanged=True,
            journal_path=None,
        )

    result = ScanResult(
        username=profile.username,
        user_pk=profile.pk,
        old_count=old_total,
        following_count=profile.following_count,
        follower_count=profile.follower_count,
        tracked_count=len(following),
        added=added,
        removed=removed,
        count_changes=count_changes,
        person_changes=person_changes,
        unchanged=(
            not added
            and not removed
            and not count_changes
            and not person_changes
            and not is_baseline
        ),
        skipped=False,
        person_snapshots=person_snapshots if person_snapshots else None,
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
        person_added=person_added,
        person_removed=person_removed,
        unchanged=False,
        journal_path=str(journal_path),
    )
