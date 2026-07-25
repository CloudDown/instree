"""Appels Instagram : profil et abonnements."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from instagrapi import Client

from instree.core.errors import ScanCancelled

# Backoff rate-limit : 5 min → 15 min → 60 min
_RATE_LIMIT_BACKOFFS = (300, 900, 3600)
_RATE_LIMIT_MAX_RETRIES = 3


@dataclass
class IgUser:
    pk: str
    username: str
    full_name: str
    following_count: int = 0
    follower_count: int = 0
    is_verified: bool = False


def _user_verified(u) -> bool:
    if isinstance(u, dict):
        return bool(u.get("is_verified"))
    return bool(getattr(u, "is_verified", False))


def interruptible_sleep(
    seconds: float,
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    """Sleep annulable (pas de blocage long sans check cancel)."""
    if seconds <= 0:
        return
    end = time.monotonic() + seconds
    while True:
        if should_cancel and should_cancel():
            raise ScanCancelled()
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.5, remaining))


def is_rate_limited(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in (
        "FeedbackRequired",
        "PleaseWaitFewMinutes",
        "RateLimitError",
        "ClientThrottledError",
    ):
        return True
    msg = str(exc).lower()
    return any(
        s in msg
        for s in (
            "feedback_required",
            "please wait a few minutes",
            "wait a few minutes",
            "rate limit",
            "we limit how often",
        )
    )


def _with_rate_limit_retry(
    fn: Callable[[], object],
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_cooldown: Callable[[float], None] | None = None,
):
    last: BaseException | None = None
    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        if should_cancel and should_cancel():
            raise ScanCancelled()
        try:
            return fn()
        except ScanCancelled:
            raise
        except Exception as e:
            if not is_rate_limited(e) or attempt >= _RATE_LIMIT_MAX_RETRIES:
                raise
            last = e
            wait = _RATE_LIMIT_BACKOFFS[min(attempt, len(_RATE_LIMIT_BACKOFFS) - 1)]
            until = time.time() + wait
            if on_cooldown:
                on_cooldown(until)
            interruptible_sleep(wait, should_cancel)
            if on_cooldown:
                on_cooldown(0.0)
    assert last is not None
    raise last


def user_profile(
    ig: Client,
    username: str,
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_cooldown: Callable[[float], None] | None = None,
) -> IgUser:
    def _load() -> IgUser:
        u = ig.user_info_by_username(username.lstrip("@"))
        return IgUser(
            pk=str(u.pk),
            username=u.username,
            full_name=u.full_name or "",
            following_count=int(u.following_count or 0),
            follower_count=int(u.follower_count or 0),
            is_verified=_user_verified(u),
        )

    return _with_rate_limit_retry(
        _load, should_cancel=should_cancel, on_cooldown=on_cooldown
    )


def try_user_by_pk(ig: Client, pk: str) -> IgUser | None:
    """Profil par pk, ou None si le compte est introuvable / supprimé."""
    try:
        u = ig.user_info(str(pk))
    except Exception:
        return None
    if not u or not getattr(u, "username", None):
        return None
    return IgUser(
        pk=str(u.pk),
        username=u.username,
        full_name=u.full_name or "",
        following_count=int(getattr(u, "following_count", 0) or 0),
        follower_count=int(getattr(u, "follower_count", 0) or 0),
        is_verified=_user_verified(u),
    )


def _paginate_friendships(
    ig: Client,
    pk: str,
    endpoint: str,
    *,
    limit: int = 0,
    page_sleep: float = 0.6,
    page_size: int = 200,
    should_cancel: Callable[[], bool] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_cooldown: Callable[[float], None] | None = None,
    total_hint: int = 0,
    known_usernames: set[str] | None = None,
    stop_after_new: int = 0,
    resume_max_id: str = "",
    resume_users: list[IgUser] | None = None,
    on_checkpoint: Callable[[list[IgUser], str], None] | None = None,
) -> list[IgUser]:
    users: list[IgUser] = list(resume_users or [])
    max_id = resume_max_id or ""
    seen: set[str] = {u.pk for u in users if u.pk}
    target = limit if limit > 0 else total_hint
    new_found = 0

    while True:
        if should_cancel and should_cancel():
            raise ScanCancelled()
        params = {
            "count": page_size,
            "rank_token": ig.rank_token,
            "search_surface": "follow_list_page",
            "query": "",
            "enable_groups": "true",
        }
        if max_id:
            params["max_id"] = max_id

        def _request():
            return ig.private_request(f"friendships/{pk}/{endpoint}/", params=params)

        result = _with_rate_limit_retry(
            _request, should_cancel=should_cancel, on_cooldown=on_cooldown
        )
        for u in result.get("users") or []:
            upk = str(u.get("pk", ""))
            username = u.get("username", "")
            if not upk or not username or upk in seen:
                continue
            seen.add(upk)
            users.append(
                IgUser(
                    pk=upk,
                    username=username,
                    full_name=u.get("full_name") or "",
                    is_verified=_user_verified(u),
                )
            )
            if known_usernames is not None and username not in known_usernames:
                new_found += 1
                if stop_after_new > 0 and new_found >= stop_after_new:
                    if on_page:
                        on_page(len(users), target or len(users))
                    if on_checkpoint:
                        on_checkpoint(users, "")
                    return users
            if limit > 0 and len(users) >= limit:
                if on_page:
                    on_page(len(users), target or len(users))
                if on_checkpoint:
                    on_checkpoint(users, "")
                return users[:limit]
        if on_page:
            on_page(len(users), target)
        next_max_id = result.get("next_max_id") or ""
        if on_checkpoint:
            on_checkpoint(users, next_max_id)
        if not next_max_id:
            break
        max_id = next_max_id
        interruptible_sleep(page_sleep, should_cancel)

    return users


def fetch_following(
    ig: Client,
    pk: str,
    *,
    limit: int = 0,
    page_sleep: float = 0.6,
    page_size: int = 200,
    should_cancel: Callable[[], bool] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_cooldown: Callable[[float], None] | None = None,
    total_hint: int = 0,
    known_usernames: set[str] | None = None,
    stop_after_new: int = 0,
    resume_max_id: str = "",
    resume_users: list[IgUser] | None = None,
    on_checkpoint: Callable[[list[IgUser], str], None] | None = None,
) -> list[IgUser]:
    """Paginer friendships/{pk}/following/ (limit=0 → tous)."""
    return _paginate_friendships(
        ig,
        pk,
        "following",
        limit=limit,
        page_sleep=page_sleep,
        page_size=page_size,
        should_cancel=should_cancel,
        on_page=on_page,
        on_cooldown=on_cooldown,
        total_hint=total_hint,
        known_usernames=known_usernames,
        stop_after_new=stop_after_new,
        resume_max_id=resume_max_id,
        resume_users=resume_users,
        on_checkpoint=on_checkpoint,
    )


def fetch_followers(
    ig: Client,
    pk: str,
    *,
    limit: int = 0,
    page_sleep: float = 0.6,
    page_size: int = 200,
    should_cancel: Callable[[], bool] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_cooldown: Callable[[float], None] | None = None,
    resume_max_id: str = "",
    resume_users: list[IgUser] | None = None,
    on_checkpoint: Callable[[list[IgUser], str], None] | None = None,
) -> list[IgUser]:
    """Paginer friendships/{pk}/followers/ (limit=0 → tous)."""
    return _paginate_friendships(
        ig,
        pk,
        "followers",
        limit=limit,
        page_sleep=page_sleep,
        page_size=page_size,
        should_cancel=should_cancel,
        on_page=on_page,
        on_cooldown=on_cooldown,
        resume_max_id=resume_max_id,
        resume_users=resume_users,
        on_checkpoint=on_checkpoint,
    )


def fetch_mutuals(
    ig: Client,
    pk: str,
    *,
    limit: int = 0,
    page_sleep: float = 0.6,
    page_size: int = 200,
    should_cancel: Callable[[], bool] | None = None,
    on_cooldown: Callable[[float], None] | None = None,
) -> list[IgUser]:
    """Abonnements mutuels : intersection following ∩ followers."""
    following = fetch_following(
        ig,
        pk,
        limit=0,
        page_sleep=page_sleep,
        page_size=page_size,
        should_cancel=should_cancel,
        on_cooldown=on_cooldown,
    )
    if should_cancel and should_cancel():
        raise ScanCancelled()
    followers = fetch_followers(
        ig,
        pk,
        limit=0,
        page_sleep=page_sleep,
        page_size=page_size,
        should_cancel=should_cancel,
        on_cooldown=on_cooldown,
    )
    follower_pks = {u.pk for u in followers}
    mutuals = [u for u in following if u.pk in follower_pks]
    if limit > 0:
        return mutuals[:limit]
    return mutuals
