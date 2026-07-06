"""Appels Instagram : profil et abonnements."""

import time
from dataclasses import dataclass

from instagrapi import Client


@dataclass
class IgUser:
    pk: str
    username: str
    full_name: str
    following_count: int = 0
    follower_count: int = 0


def user_profile(ig: Client, username: str) -> IgUser:
    u = ig.user_info_by_username(username.lstrip("@"))
    return IgUser(
        pk=str(u.pk),
        username=u.username,
        full_name=u.full_name or "",
        following_count=int(u.following_count or 0),
        follower_count=int(u.follower_count or 0),
    )


def _paginate_friendships(
    ig: Client,
    pk: str,
    endpoint: str,
    *,
    limit: int = 0,
    page_sleep: float = 0.6,
) -> list[IgUser]:
    users: list[IgUser] = []
    max_id = ""
    seen: set[str] = set()

    while True:
        params = {
            "count": 200,
            "rank_token": ig.rank_token,
            "search_surface": "follow_list_page",
            "query": "",
            "enable_groups": "true",
        }
        if max_id:
            params["max_id"] = max_id
        result = ig.private_request(f"friendships/{pk}/{endpoint}/", params=params)
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
                )
            )
            if limit > 0 and len(users) >= limit:
                return users[:limit]
        max_id = result.get("next_max_id")
        if not max_id:
            break
        time.sleep(page_sleep)

    return users


def fetch_following(
    ig: Client,
    pk: str,
    *,
    limit: int = 0,
    page_sleep: float = 0.6,
) -> list[IgUser]:
    """Paginer friendships/{pk}/following/ (limit=0 → tous)."""
    return _paginate_friendships(ig, pk, "following", limit=limit, page_sleep=page_sleep)


def fetch_followers(
    ig: Client,
    pk: str,
    *,
    limit: int = 0,
    page_sleep: float = 0.6,
) -> list[IgUser]:
    """Paginer friendships/{pk}/followers/ (limit=0 → tous)."""
    return _paginate_friendships(ig, pk, "followers", limit=limit, page_sleep=page_sleep)


def fetch_mutuals(
    ig: Client,
    pk: str,
    *,
    limit: int = 0,
    page_sleep: float = 0.6,
) -> list[IgUser]:
    """Abonnements mutuels : intersection following ∩ followers."""
    following = fetch_following(ig, pk, limit=0, page_sleep=page_sleep)
    followers = fetch_followers(ig, pk, limit=0, page_sleep=page_sleep)
    follower_pks = {u.pk for u in followers}
    mutuals = [u for u in following if u.pk in follower_pks]
    if limit > 0:
        return mutuals[:limit]
    return mutuals
