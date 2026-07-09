"""Connexion Instagram (config/instree.toml ou cookies navigateur)."""

from instagrapi import Client
from instagrapi.exceptions import LoginRequired

from instree.config import load_settings, save_session_credentials

_BROWSERS = (
    "chromium",
    "chrome",
    "brave",
    "edge",
    "firefox",
    "opera",
    "vivaldi",
    "librewolf",
)


def _login(jar: dict) -> Client:
    c = Client()
    c.set_settings(
        {
            "cookies": jar,
            "authorization_data": {
                "sessionid": jar["sessionid"],
                "ds_user_id": jar.get("ds_user_id", ""),
            },
        }
    )
    c.account_info()
    return c


def _cookies_from_browser() -> tuple[str, dict] | None:
    import browser_cookie3

    for browser in _BROWSERS:
        try:
            jar = {
                c.name: c.value
                for c in getattr(browser_cookie3, browser)(domain_name="instagram.com")
                if c.name in ("sessionid", "ds_user_id")
            }
            if jar.get("sessionid"):
                return browser, jar
        except Exception:
            continue
    return None


def connect() -> tuple[Client, str, str | None]:
    """Retourne (client, source, note)."""
    settings = load_settings()

    if settings.sessionid:
        try:
            client = _login(
                {
                    "sessionid": settings.sessionid,
                    "ds_user_id": settings.ds_user_id,
                }
            )
            return client, "config/instree.local.toml", None
        except (LoginRequired, Exception) as e:
            raise RuntimeError(
                "Session TOML invalide ou expirée — mets à jour sessionid "
                "dans Settings ou vide config/instree.local.toml pour relire le navigateur"
            ) from e

    found = _cookies_from_browser()
    if not found:
        raise RuntimeError(
            "Pas de session configurée — remplis sessionid dans Settings, "
            "ou connecte-toi sur instagram.com dans Chromium/Chrome"
        )

    browser, jar = found
    client = _login(jar)
    save_session_credentials(jar["sessionid"], jar.get("ds_user_id", ""))
    return (
        client,
        f"navigateur ({browser})",
        "Session enregistrée dans config/instree.local.toml",
    )


def session_user(ig: Client) -> str:
    return ig.account_info().username
