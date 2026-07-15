"""Scan incrémental : abonnements mutuels + évolution de leurs abonnements."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from instagrapi import Client

from instree.config import Settings
from instree.errors import ScanCancelled
from instree.ig import fetch_following, fetch_mutuals, try_user_by_pk, user_profile
from instree.session import session_user
from instree.store import (
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
        is_verified=bool(getattr(u, "is_verified", False)),
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


def _is_account_gone(ig: Client, entry: FollowingEntry) -> bool:
    """True si le compte est introuvable ou a changé de pseudo (pk)."""
    info = try_user_by_pk(ig, entry.pk)
    if info is None:
        return True
    return info.username.lstrip("@").lower() != entry.username.lstrip("@").lower()


def _split_removed_gone(
    ig: Client,
    removed: list[FollowingEntry],
    live: list[FollowingEntry],
    *,
    page_sleep: float,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[list[FollowingEntry], list[FollowingEntry], set[str]]:
    """Sépare désabonnements réels / comptes disparus ou renommés.

    Retourne (unfollows, gones, rename_pks encore présents dans live).
    """
    live_by_pk = {e.pk: e for e in live if e.pk}
    unfollows: list[FollowingEntry] = []
    gones: list[FollowingEntry] = []
    rename_pks: set[str] = set()

    for i, r in enumerate(removed):
        _check_cancel(should_cancel)
        if r.pk and r.pk in live_by_pk:
            rename_pks.add(r.pk)
            gones.append(r)
            continue
        if _is_account_gone(ig, r):
            gones.append(r)
        else:
            unfollows.append(r)
        if i + 1 < len(removed) and page_sleep > 0:
            time.sleep(page_sleep)

    return unfollows, gones, rename_pks


def _check_cancel(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel and should_cancel():
        raise ScanCancelled()


def _report(
    on_progress,
    current: int,
    total: int,
    username: str,
    phase: str,
    *,
    track: str = "profiles",
) -> None:
    if on_progress:
        on_progress(current, total, username, phase, track=track)


def _merge_added_snapshot(
    stored: list[FollowingEntry],
    added: list[FollowingEntry],
    watch_n: int,
) -> list[FollowingEntry]:
    """Nouveaux abonnements en tête + ancien snapshot, tronqué si watch_n limité."""
    added_names = {a.username for a in added}
    rest = [e for e in stored if e.username not in added_names]
    merged = added + rest
    if watch_n > 0:
        return merged[:watch_n]
    return merged


def _fetch_person_following(
    ig: Client,
    pk: str,
    *,
    limit: int,
    page_sleep: float,
    page_size: int,
    should_cancel: Callable[[], bool] | None = None,
    on_progress=None,
    username: str = "",
    total_hint: int = 0,
    known_usernames: set[str] | None = None,
    stop_after_new: int = 0,
) -> list[FollowingEntry]:
    target = limit if limit > 0 else total_hint

    def on_page(fetched: int, total: int) -> None:
        _report(on_progress, fetched, total or target, username, "page", track="watch")

    users = fetch_following(
        ig,
        pk,
        limit=limit,
        page_sleep=page_sleep,
        page_size=page_size,
        should_cancel=should_cancel,
        on_page=on_page if on_progress else None,
        total_hint=target,
        known_usernames=known_usernames,
        stop_after_new=stop_after_new,
    )
    return [_to_entry(u) for u in users]


def _apply_person_diff(
    ig: Client,
    profile_username: str,
    entry: FollowingEntry,
    stored: list[FollowingEntry],
    live: list[FollowingEntry],
    person_changes: list[PersonChange],
    *,
    page_sleep: float,
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    added, removed = _diff(stored, live)
    unfollows, gones, rename_pks = _split_removed_gone(
        ig,
        removed,
        live,
        page_sleep=page_sleep,
        should_cancel=should_cancel,
    )

    for a in added:
        if a.pk and a.pk in rename_pks:
            continue
        person_changes.append(
            PersonChange(
                subject_username=profile_username,
                subject_full_name=entry.full_name,
                username=a.username,
                full_name=a.full_name,
                op="sub_add",
                is_verified=a.is_verified,
            )
        )
    for r in unfollows:
        person_changes.append(
            PersonChange(
                subject_username=profile_username,
                subject_full_name=entry.full_name,
                username=r.username,
                full_name=r.full_name,
                op="sub_remove",
                is_verified=r.is_verified,
            )
        )
    for r in gones:
        person_changes.append(
            PersonChange(
                subject_username=profile_username,
                subject_full_name=entry.full_name,
                username=r.username,
                full_name=r.full_name,
                op="sub_gone",
                is_verified=r.is_verified,
            )
        )


def _watch_persons(
    ig: Client,
    entries: list[FollowingEntry],
    *,
    watch_n: int,
    page_sleep: float,
    page_size: int,
    is_baseline: bool,
    new_usernames: set[str],
    on_progress=None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[
    list[PersonChange],
    list[FollowingEntry],
    list[tuple[str, list[FollowingEntry], int]],
]:
    person_changes: list[PersonChange] = []
    updated: list[FollowingEntry] = []
    snapshots: list[tuple[str, list[FollowingEntry], int]] = []
    fetch_limit = watch_n if watch_n > 0 else 0

    for i, e in enumerate(entries):
        _check_cancel(should_cancel)
        _report(on_progress, i + 1, len(entries), e.username, "profile")

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
            is_verified=profile.is_verified or e.is_verified,
        )
        updated.append(entry)

        snapshot = get_person_snapshot(profile.username)
        need_baseline = (
            is_baseline
            or snapshot is None
            or profile.username in new_usernames
        )
        need_diff = (
            not need_baseline
            and snapshot is not None
            and profile.following_count != snapshot.following_count
        )

        if need_baseline or need_diff:
            phase = "baseline" if need_baseline else "fetch"
            total_hint = fetch_limit if fetch_limit > 0 else profile.following_count
            _report(
                on_progress,
                0,
                total_hint,
                profile.username,
                phase,
                track="watch",
            )
            try:
                live: list[FollowingEntry]
                if (
                    need_diff
                    and snapshot is not None
                    and profile.following_count > snapshot.following_count
                ):
                    stored = get_person_following(profile.username)
                    stored_set = {e.username for e in stored}
                    delta = profile.following_count - snapshot.following_count
                    partial = _fetch_person_following(
                        ig,
                        profile.pk,
                        limit=fetch_limit,
                        page_sleep=page_sleep,
                        page_size=page_size,
                        should_cancel=should_cancel,
                        on_progress=on_progress,
                        username=profile.username,
                        total_hint=total_hint,
                        known_usernames=stored_set,
                        stop_after_new=delta,
                    )
                    added = [e for e in partial if e.username not in stored_set]
                    if len(added) >= delta:
                        live = _merge_added_snapshot(stored, added, fetch_limit)
                        snapshots.append((profile.username, live, profile.following_count))
                        for a in added:
                            person_changes.append(
                                PersonChange(
                                    subject_username=profile.username,
                                    subject_full_name=entry.full_name,
                                    username=a.username,
                                    full_name=a.full_name,
                                    op="sub_add",
                                    is_verified=a.is_verified,
                                )
                            )
                    else:
                        live = _fetch_person_following(
                            ig,
                            profile.pk,
                            limit=fetch_limit,
                            page_sleep=page_sleep,
                            page_size=page_size,
                            should_cancel=should_cancel,
                            on_progress=on_progress,
                            username=profile.username,
                            total_hint=total_hint,
                        )
                        snapshots.append((profile.username, live, profile.following_count))
                        _apply_person_diff(
                            ig,
                            profile.username,
                            entry,
                            stored,
                            live,
                            person_changes,
                            page_sleep=page_sleep,
                            should_cancel=should_cancel,
                        )
                else:
                    live = _fetch_person_following(
                        ig,
                        profile.pk,
                        limit=fetch_limit,
                        page_sleep=page_sleep,
                        page_size=page_size,
                        should_cancel=should_cancel,
                        on_progress=on_progress,
                        username=profile.username,
                        total_hint=total_hint,
                    )
                    snapshots.append((profile.username, live, profile.following_count))
                    if need_diff and snapshot is not None:
                        stored = get_person_following(profile.username)
                        _apply_person_diff(
                            ig,
                            profile.username,
                            entry,
                            stored,
                            live,
                            person_changes,
                            page_sleep=page_sleep,
                            should_cancel=should_cancel,
                        )
            except Exception:
                if i + 1 < len(entries):
                    time.sleep(page_sleep)
                continue

        if i + 1 < len(entries):
            time.sleep(page_sleep)
            _check_cancel(should_cancel)

    return person_changes, updated, snapshots


def run_scan(
    ig: Client,
    settings: Settings,
    *,
    init: bool = False,
    on_progress=None,
    should_cancel: Callable[[], bool] | None = None,
) -> ScanSummary:
    init_db()
    _check_cancel(should_cancel)
    is_baseline = init or not has_scans()

    username = settings.username or session_user(ig)
    limit = settings.n

    try:
        profile = user_profile(ig, username)
    except Exception as e:
        raise RuntimeError(f"Impossible de charger @{username} : {e}") from e

    old_total, old_followers, stored_list = latest_following(profile.username)
    counts_changed = (
        old_total is None
        or profile.following_count != old_total
        or profile.follower_count != old_followers
    )
    need_list = is_baseline or not stored_list or counts_changed

    added: list[FollowingEntry] = []
    removed: list[FollowingEntry] = []
    gone: list[FollowingEntry] = []

    if need_list:
        _report(on_progress, 0, 0, "", "mutuals")
        try:
            live_users = fetch_mutuals(
                ig,
                profile.pk,
                limit=limit,
                page_sleep=settings.page_sleep,
                page_size=settings.page_size,
                should_cancel=should_cancel,
            )
        except Exception as e:
            raise RuntimeError(f"Erreur fetch abonnements mutuels : {e}") from e
        live = [_to_entry(u) for u in live_users]
        if is_baseline or not stored_list:
            added, removed, gone = [], [], []
        else:
            added, removed_raw = _diff(stored_list, live)
            removed, gone, rename_pks = _split_removed_gone(
                ig,
                removed_raw,
                live,
                page_sleep=settings.page_sleep,
                should_cancel=should_cancel,
            )
            if rename_pks:
                added = [a for a in added if not a.pk or a.pk not in rename_pks]
    else:
        live = list(stored_list)
        added, removed, gone = [], [], []

    for r in removed + gone:
        delete_person_snapshot(r.username)

    new_usernames = {a.username for a in added}

    person_changes, following, person_snapshots = _watch_persons(
        ig,
        live,
        watch_n=settings.watch_n,
        page_sleep=settings.page_sleep,
        page_size=settings.page_size,
        is_baseline=is_baseline,
        new_usernames=new_usernames,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )

    person_added = sum(1 for c in person_changes if c.op == "sub_add")
    person_removed = sum(1 for c in person_changes if c.op == "sub_remove")
    person_gone = sum(1 for c in person_changes if c.op == "sub_gone")

    if (
        not is_baseline
        and not need_list
        and not added
        and not removed
        and not gone
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
            person_added=0,
            person_removed=0,
            unchanged=True,
            journal_path=None,
        )

    result = ScanResult(
        username=profile.username,
        old_count=old_total,
        following_count=profile.following_count,
        follower_count=profile.follower_count,
        tracked_count=len(following),
        added=added,
        removed=removed,
        gone=gone,
        person_changes=person_changes,
        unchanged=(
            not added
            and not removed
            and not gone
            and not person_changes
            and not is_baseline
        ),
        person_snapshots=person_snapshots if person_snapshots else None,
    )
    scan_id, journal_path = save_scan(result, following)

    return ScanSummary(
        scan_id=scan_id,
        username=profile.username,
        tracked=len(following),
        following_count=profile.following_count,
        added=len(added),
        removed=len(removed) + len(gone),
        person_added=person_added,
        person_removed=person_removed + person_gone,
        unchanged=False,
        journal_path=str(journal_path),
    )
