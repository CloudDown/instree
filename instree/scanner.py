"""Logique de scan incrémental des abonnements close friends."""
import time
from dataclasses import dataclass

from instagrapi import Client

from instree.ig import (
    IgUser,
    can_view_following,
    close_friends,
    fetch_following,
    user_profile,
)
from instree.store import (
    FollowingEntry,
    FriendResult,
    has_scans,
    init_db,
    latest_snapshot,
    save_scan_with_following,
)


@dataclass
class ScanSummary:
    scan_id: int
    friends_total: int
    changed: int
    unchanged: int
    skipped: int
    journal_path: str | None


def _to_entry(u: IgUser) -> FollowingEntry:
    return FollowingEntry(username=u.username, pk=u.pk, full_name=u.full_name)


def _diff(
    stored: dict[str, FollowingEntry],
    live: list[FollowingEntry],
) -> tuple[list[FollowingEntry], list[FollowingEntry]]:
    live_map = {e.username: e for e in live}
    added = [live_map[u] for u in live_map if u not in stored]
    removed = [stored[u] for u in stored if u not in live_map]
    return added, removed


def scan_friend(
    ig: Client,
    friend: IgUser,
    *,
    force_full: bool = False,
    is_baseline: bool = False,
    friend_sleep: float = 1.0,
) -> tuple[FriendResult, list[FollowingEntry]] | None:
    """Scan un close friend. Retourne None si skip total (inaccessible)."""
    try:
        profile = user_profile(ig, friend.username)
    except Exception as e:
        return (
            FriendResult(
                friend_username=friend.username,
                friend_pk=friend.pk,
                old_count=None,
                new_count=0,
                added=[],
                removed=[],
                unchanged=False,
                skipped=True,
                skip_reason=str(e),
            ),
            [],
        )

    if profile.is_private and not can_view_following(ig, profile.pk):
        return (
            FriendResult(
                friend_username=profile.username,
                friend_pk=profile.pk,
                old_count=None,
                new_count=profile.following_count,
                added=[],
                removed=[],
                unchanged=False,
                skipped=True,
                skip_reason="compte privé — tu ne le suis pas",
            ),
            [],
        )

    old_count, stored = latest_snapshot(profile.username)
    need_full = (
        force_full
        or is_baseline
        or old_count is None
        or profile.following_count != old_count
    )

    if not need_full:
        return (
            FriendResult(
                friend_username=profile.username,
                friend_pk=profile.pk,
                old_count=old_count,
                new_count=profile.following_count,
                added=[],
                removed=[],
                unchanged=True,
                skipped=False,
            ),
            [],
        )

    time.sleep(friend_sleep)
    try:
        live_users = fetch_following(ig, profile.pk)
    except Exception as e:
        return (
            FriendResult(
                friend_username=profile.username,
                friend_pk=profile.pk,
                old_count=old_count,
                new_count=profile.following_count,
                added=[],
                removed=[],
                unchanged=False,
                skipped=True,
                skip_reason=f"erreur fetch abonnements: {e}",
            ),
            [],
        )

    live = [_to_entry(u) for u in live_users if u.username]
    if is_baseline or not stored:
        added, removed = [], []
    else:
        added, removed = _diff(stored, live)

    return (
        FriendResult(
            friend_username=profile.username,
            friend_pk=profile.pk,
            old_count=old_count,
            new_count=profile.following_count,
            added=added,
            removed=removed,
            unchanged=not added and not removed and old_count is not None,
            skipped=False,
        ),
        live,
    )


def run_scan(
    ig: Client,
    *,
    init: bool = False,
    full: bool = False,
    on_progress=None,
) -> ScanSummary:
    init_db()
    is_baseline = init or not has_scans()
    force_full = full or is_baseline

    friends = close_friends(ig)
    if not friends:
        raise RuntimeError("Aucun close friend trouvé (friendships/besties/)")

    results: list[tuple[FriendResult, list[FollowingEntry]]] = []
    changed = unchanged = skipped = 0

    for i, friend in enumerate(friends):
        if on_progress:
            on_progress(i + 1, len(friends), friend.username)
        item = scan_friend(
            ig,
            friend,
            force_full=force_full,
            is_baseline=is_baseline,
        )
        if item is None:
            continue
        r, live = item
        results.append((r, live))
        if r.skipped:
            skipped += 1
        elif r.unchanged:
            unchanged += 1
        else:
            changed += 1

    scan_id, journal_path = save_scan_with_following(results)

    return ScanSummary(
        scan_id=scan_id,
        friends_total=len(friends),
        changed=changed,
        unchanged=unchanged,
        skipped=skipped,
        journal_path=str(journal_path) if journal_path else None,
    )
