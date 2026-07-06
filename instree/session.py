"""Connexion Instagram (instree.toml ou cookies navigateur)."""
from instagrapi import Client
from instagrapi.exceptions import LoginRequired

from instree.config import CONFIG_PATH, load_settings


def _login(jar: dict) -> Client:
    c = Client()
    c.set_settings({
        "cookies": jar,
        "authorization_data": {
            "sessionid": jar["sessionid"],
            "ds_user_id": jar.get("ds_user_id", ""),
        },
    })
    c.account_info()
    return c


def connect() -> tuple[Client, str, str | None]:
    """Retourne (client, source, note)."""
    settings = load_settings()
    toml_present = CONFIG_PATH.is_file()
    toml_empty = False

    if toml_present and settings.sessionid:
        try:
            client = _login({
                "sessionid": settings.sessionid,
                "ds_user_id": settings.ds_user_id,
            })
            return client, "instree.toml", None
        except (LoginRequired, Exception):
            toml_empty = True
    elif toml_present:
        toml_empty = True

    import browser_cookie3
    for b in ("firefox", "chrome", "chromium", "brave", "edge", "opera", "vivaldi", "librewolf"):
        try:
            jar = {
                c.name: c.value
                for c in getattr(browser_cookie3, b)(domain_name="instagram.com")
                if c.name in ("sessionid", "ds_user_id")
            }
            if jar.get("sessionid"):
                client = _login(jar)
                note = None
                if toml_empty:
                    note = (
                        "instree.toml présent mais vide — cookies navigateur utilisés "
                        "(voir instree.toml.example)"
                    )
                return client, f"navigateur ({b})", note
        except Exception:
            pass

    if toml_empty:
        raise RuntimeError(
            "instree.toml vide et aucun cookie Instagram dans le navigateur — "
            "remplis instree.toml ou connecte-toi sur instagram.com"
        )
    raise RuntimeError(
        "Pas de session — copie instree.toml.example → instree.toml, "
        "ou connecte-toi à instagram.com dans ton navigateur"
    )


def session_user(ig: Client) -> str:
    return ig.account_info().username
