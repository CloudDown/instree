"""Scan incrémental : abonnements mutuels + évolution de leurs abonnements."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from instagrapi import Client

from instree.core.config import Settings
from instree.core.errors import ScanCancelled
from instree.core.ig import (
    IgUser,
    fetch_followers,
    fetch_following,
    interruptible_sleep,
    is_rate_limited,
    try_user_by_pk,
    user_profile,
)
from instree.core.session import session_user
from instree.core.store import (
    FollowingEntry,
    PersonChange,
    ScanDraft,
    ScanResult,
    clear_scan_draft,
    delete_person_snapshot,
    get_person_following,
    get_person_snapshot,
    get_scan_draft,
    has_draft_mutuals,
    has_scans,
    init_db,
    latest_following,
    load_draft_friendships,
    load_draft_mutuals,
    save_draft_friendships,
    save_draft_mutuals,
    save_person_snapshot,
    save_scan,
    upsert_scan_draft,
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


def _to_ig_user(e: FollowingEntry) -> IgUser:
    return IgUser(
        pk=e.pk,
        username=e.username,
        full_name=e.full_name,
        following_count=e.following_count,
        is_verified=e.is_verified,
    )


def _entries_to_ig(entries: list[FollowingEntry]) -> list[IgUser]:
    return [_to_ig_user(e) for e in entries]


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
            interruptible_sleep(page_sleep, should_cancel)

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


def _effective_fetch_limit(watch_n: int, max_person_following: int = 0) -> int:
    """watch_n > 0 = limite ; 0 / MAX = tous les abonnements.

    max_person_following est ignoré (ancien plafond UI retiré).
    """
    _ = max_person_following
    return watch_n if watch_n > 0 else 0


def _watch_total_hint(fetch_limit: int, following_count: int) -> int:
    """Total affiché dans la barre : vrai compte IG, éventuellement tronqué par watch_n."""
    if following_count > 0:
        if fetch_limit > 0:
            return min(fetch_limit, following_count)
        return following_count
    return fetch_limit if fetch_limit > 0 else 0


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


def _checkpoint(
    username: str,
    live: list[FollowingEntry],
    following_count: int,
    snapshots: list[tuple[str, list[FollowingEntry], int]],
    *,
    is_complete: bool = True,
    pagination_cursor: str = "",
) -> None:
    save_person_snapshot(
        username,
        live,
        following_count,
        scan_id=0,
        is_complete=is_complete,
        pagination_cursor=pagination_cursor,
    )
    if is_complete:
        snapshots.append((username, live, following_count))


def _fetch_person_following(
    ig: Client,
    pk: str,
    *,
    limit: int,
    page_sleep: float,
    page_size: int,
    should_cancel: Callable[[], bool] | None = None,
    on_progress=None,
    on_cooldown: Callable[[float], None] | None = None,
    username: str = "",
    total_hint: int = 0,
    known_usernames: set[str] | None = None,
    stop_after_new: int = 0,
    following_count: int = 0,
) -> list[FollowingEntry]:
    target = limit if limit > 0 else total_hint
    resume_users: list[IgUser] | None = None
    resume_max_id = ""
    snapshot = get_person_snapshot(username) if username else None
    if (
        username
        and snapshot
        and not snapshot.is_complete
        and snapshot.tracked_count > 0
    ):
        resume_users = _entries_to_ig(get_person_following(username))
        resume_max_id = snapshot.pagination_cursor or ""

    def on_page(fetched: int, total: int) -> None:
        _report(on_progress, fetched, total or target, username, "page", track="watch")

    def on_checkpoint(users: list[IgUser], cursor: str) -> None:
        if not username:
            return
        entries = [_to_entry(u) for u in users]
        complete = not cursor
        _checkpoint(
            username,
            entries,
            following_count or snapshot.following_count if snapshot else 0,
            [],
            is_complete=complete,
            pagination_cursor=cursor,
        )

    users = fetch_following(
        ig,
        pk,
        limit=limit,
        page_sleep=page_sleep,
        page_size=page_size,
        should_cancel=should_cancel,
        on_page=on_page if on_progress else None,
        on_cooldown=on_cooldown,
        total_hint=target,
        known_usernames=known_usernames,
        stop_after_new=stop_after_new,
        resume_max_id=resume_max_id,
        resume_users=resume_users,
        on_checkpoint=on_checkpoint if username else None,
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
    max_person_following: int,
    page_sleep: float,
    page_size: int,
    new_usernames: set[str],
    on_progress=None,
    should_cancel: Callable[[], bool] | None = None,
    on_cooldown: Callable[[float], None] | None = None,
) -> tuple[
    list[PersonChange],
    list[FollowingEntry],
    list[tuple[str, list[FollowingEntry], int]],
]:
    person_changes: list[PersonChange] = []
    updated: list[FollowingEntry] = []
    snapshots: list[tuple[str, list[FollowingEntry], int]] = []
    fetch_limit = _effective_fetch_limit(watch_n, max_person_following)

    for i, e in enumerate(entries):
        _check_cancel(should_cancel)
        _report(on_progress, i + 1, len(entries), e.username, "profile")

        try:
            profile = user_profile(
                ig,
                e.username,
                should_cancel=should_cancel,
                on_cooldown=on_cooldown,
            )
        except ScanCancelled:
            raise
        except Exception as exc:
            if is_rate_limited(exc):
                raise RuntimeError(
                    f"Instagram rate-limit sur @{e.username} : {exc}"
                ) from exc
            updated.append(e)
            if i + 1 < len(entries):
                interruptible_sleep(page_sleep, should_cancel)
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
        # Reprise : snapshot complet → skip ; incomplet → reprendre le fetch
        need_baseline = (
            snapshot is None
            or profile.username in new_usernames
            or (snapshot is not None and not snapshot.is_complete)
        )
        need_diff = (
            not need_baseline
            and snapshot is not None
            and snapshot.is_complete
            and profile.following_count != snapshot.following_count
        )

        if need_baseline or need_diff:
            phase = "baseline" if need_baseline else "fetch"
            total_hint = _watch_total_hint(fetch_limit, profile.following_count)
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
                        on_cooldown=on_cooldown,
                        username=profile.username,
                        total_hint=total_hint,
                        known_usernames=stored_set,
                        stop_after_new=delta,
                        following_count=profile.following_count,
                    )
                    added = [e for e in partial if e.username not in stored_set]
                    if len(added) >= delta:
                        live = _merge_added_snapshot(stored, added, fetch_limit)
                        _checkpoint(
                            profile.username, live, profile.following_count, snapshots
                        )
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
                            on_cooldown=on_cooldown,
                            username=profile.username,
                            total_hint=total_hint,
                            following_count=profile.following_count,
                        )
                        _checkpoint(
                            profile.username, live, profile.following_count, snapshots
                        )
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
                        on_cooldown=on_cooldown,
                        username=profile.username,
                        total_hint=total_hint,
                        following_count=profile.following_count,
                    )
                    _checkpoint(
                        profile.username, live, profile.following_count, snapshots
                    )
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
            except ScanCancelled:
                raise
            except Exception as exc:
                if is_rate_limited(exc):
                    raise RuntimeError(
                        f"Instagram rate-limit pendant le fetch @{profile.username} : {exc}"
                    ) from exc
                if i + 1 < len(entries):
                    interruptible_sleep(page_sleep, should_cancel)
                continue

        if i + 1 < len(entries):
            interruptible_sleep(page_sleep, should_cancel)

    return person_changes, updated, snapshots


def _fetch_mutuals_with_draft(
    ig: Client,
    account_username: str,
    account_pk: str,
    *,
    following_count: int,
    follower_count: int,
    limit: int,
    is_baseline: bool,
    page_sleep: float,
    page_size: int,
    draft: ScanDraft | None,
    should_cancel: Callable[[], bool] | None = None,
    on_progress=None,
    on_cooldown: Callable[[float], None] | None = None,
) -> list[FollowingEntry]:
    """Fetch mutuels avec checkpoint (following → followers → intersection)."""
    _report(on_progress, 0, 0, "", "mutuals")
    phase = draft.phase if draft else "mutuals_following"
    following_max_id = draft.following_max_id if draft else ""
    followers_max_id = draft.followers_max_id if draft else ""

    if phase == "mutuals_following":
        following_entries = load_draft_friendships("following")
        resume_users = _entries_to_ig(following_entries) if following_entries else None

        def on_following_checkpoint(users: list[IgUser], cursor: str) -> None:
            entries = [_to_entry(u) for u in users]
            save_draft_friendships("following", entries)
            upsert_scan_draft(
                ScanDraft(
                    account_username=account_username,
                    is_baseline=is_baseline,
                    following_count=following_count,
                    follower_count=follower_count,
                    phase="mutuals_following" if cursor else "mutuals_followers",
                    following_max_id=cursor,
                    followers_max_id=followers_max_id,
                )
            )

        following_users = fetch_following(
            ig,
            account_pk,
            page_sleep=page_sleep,
            page_size=page_size,
            should_cancel=should_cancel,
            on_cooldown=on_cooldown,
            resume_max_id=following_max_id,
            resume_users=resume_users,
            on_checkpoint=on_following_checkpoint,
        )
        following_entries = [_to_entry(u) for u in following_users]
    else:
        following_entries = load_draft_friendships("following")

    _check_cancel(should_cancel)

    follower_entries = load_draft_friendships("followers")
    if phase in ("mutuals_following", "mutuals_followers"):
        resume_users = _entries_to_ig(follower_entries) if follower_entries else None

        def on_followers_checkpoint(users: list[IgUser], cursor: str) -> None:
            entries = [_to_entry(u) for u in users]
            save_draft_friendships("followers", entries)
            upsert_scan_draft(
                ScanDraft(
                    account_username=account_username,
                    is_baseline=is_baseline,
                    following_count=following_count,
                    follower_count=follower_count,
                    phase="mutuals_followers" if cursor else "watch",
                    following_max_id="",
                    followers_max_id=cursor,
                )
            )

        follower_users = fetch_followers(
            ig,
            account_pk,
            page_sleep=page_sleep,
            page_size=page_size,
            should_cancel=should_cancel,
            on_cooldown=on_cooldown,
            resume_max_id=followers_max_id if phase == "mutuals_followers" else "",
            resume_users=resume_users,
            on_checkpoint=on_followers_checkpoint,
        )
        follower_entries = [_to_entry(u) for u in follower_users]

    follower_pks = {e.pk for e in follower_entries}
    mutuals = [e for e in following_entries if e.pk in follower_pks]
    if limit > 0:
        mutuals = mutuals[:limit]

    save_draft_mutuals(mutuals)
    upsert_scan_draft(
        ScanDraft(
            account_username=account_username,
            is_baseline=is_baseline,
            following_count=following_count,
            follower_count=follower_count,
            phase="watch",
            following_max_id="",
            followers_max_id="",
        )
    )
    return mutuals


def run_scan(
    ig: Client,
    settings: Settings,
    *,
    init: bool = False,
    on_progress=None,
    should_cancel: Callable[[], bool] | None = None,
    on_cooldown: Callable[[float], None] | None = None,
) -> ScanSummary:
    init_db()
    _check_cancel(should_cancel)

    username = settings.username or session_user(ig)
    limit = settings.n

    try:
        profile = user_profile(
            ig,
            username,
            should_cancel=should_cancel,
            on_cooldown=on_cooldown,
        )
    except ScanCancelled:
        raise
    except Exception as e:
        raise RuntimeError(f"Impossible de charger @{username} : {e}") from e

    if init:
        clear_scan_draft()

    draft = get_scan_draft()
    if draft and draft.account_username != profile.username:
        clear_scan_draft()
        draft = None
    if draft and (
        draft.following_count != profile.following_count
        or draft.follower_count != profile.follower_count
    ):
        clear_scan_draft()
        draft = None

    if draft:
        is_baseline = draft.is_baseline
    elif init or not has_scans():
        is_baseline = True
    else:
        is_baseline = False

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

    if draft and draft.phase == "watch" and has_draft_mutuals():
        live = load_draft_mutuals()
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
    elif need_list:
        if not draft:
            upsert_scan_draft(
                ScanDraft(
                    account_username=profile.username,
                    is_baseline=is_baseline,
                    following_count=profile.following_count,
                    follower_count=profile.follower_count,
                    phase="mutuals_following",
                )
            )
            draft = get_scan_draft()
        try:
            live = _fetch_mutuals_with_draft(
                ig,
                profile.username,
                profile.pk,
                following_count=profile.following_count,
                follower_count=profile.follower_count,
                limit=limit,
                is_baseline=is_baseline,
                page_sleep=settings.page_sleep,
                page_size=settings.page_size,
                draft=draft,
                should_cancel=should_cancel,
                on_progress=on_progress,
                on_cooldown=on_cooldown,
            )
        except ScanCancelled:
            raise
        except Exception as e:
            raise RuntimeError(f"Erreur fetch abonnements mutuels : {e}") from e
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
        max_person_following=settings.max_person_following,
        page_sleep=settings.page_sleep,
        page_size=settings.page_size,
        new_usernames=new_usernames,
        on_progress=on_progress,
        should_cancel=should_cancel,
        on_cooldown=on_cooldown,
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
        # Déjà checkpointés au fil de l'eau — éviter double écriture
        person_snapshots=None,
    )
    scan_id, journal_path = save_scan(result, following)

    # Mettre à jour updated_scan_id des snapshots déjà présents
    if person_snapshots:
        for person_username, entries, fc in person_snapshots:
            save_person_snapshot(
                person_username, entries, fc, scan_id=scan_id or 0
            )

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
