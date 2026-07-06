"""Appels Instagram : close friends, abonnements."""
import time
from dataclasses import dataclass

from instagrapi import Client


@dataclass
class IgUser:
    pk: str
    username: str
    full_name: str
    is_private: bool
    following_count: int


def close_friends(ig: Client) -> list[IgUser]:
    """Liste des close friends via friendships/besties/."""
    result = ig.private_request("friendships/besties/")
    users = []
    for u in result.get("users") or []:
        if not u.get("username"):
            continue
        users.append(IgUser(
            pk=str(u["pk"]),
            username=u["username"],
            full_name=u.get("full_name") or "",
            is_private=bool(u.get("is_private")),
            following_count=int(u.get("following_count") or 0),
        ))
    return users


def user_profile(ig: Client, username: str) -> IgUser:
    u = ig.user_info_by_username(username.lstrip("@"))
    return IgUser(
        pk=str(u.pk),
        username=u.username,
        full_name=u.full_name or "",
        is_private=bool(u.is_private),
        following_count=int(u.following_count or 0),
    )


def can_view_following(ig: Client, pk: str) -> bool:
    rel = ig.user_friendship_v1(pk)
    return bool(rel.following)


def fetch_following(ig: Client, pk: str, *, page_sleep: float = 0.6) -> list[IgUser]:
    """Paginer friendships/{pk}/following/."""
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
        result = ig.private_request(f"friendships/{pk}/following/", params=params)
        for u in result.get("users") or []:
            upk = str(u.get("pk", ""))
            if not upk or upk in seen:
                continue
            seen.add(upk)
            users.append(IgUser(
                pk=upk,
                username=u.get("username", ""),
                full_name=u.get("full_name") or "",
                is_private=bool(u.get("is_private")),
                following_count=0,
            ))
        max_id = result.get("next_max_id")
        if not max_id:
            break
        time.sleep(page_sleep)

    return users
