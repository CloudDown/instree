"""Connexion Instagram (config/instree.toml ou cookies navigateur)."""

import logging

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


def _quiet_instagrapi_logs() -> None:
    for name in ("instagrapi", "public_request", "private_request"):
        log = logging.getLogger(name)
        log.setLevel(logging.CRITICAL)
        log.propagate = False


_quiet_instagrapi_logs()


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
    from instree.config import active_profile_id

    settings = load_settings()
    local_label = f"config/profiles/{active_profile_id()}/local.toml"

    if settings.sessionid:
        try:
            client = _login(
                {
                    "sessionid": settings.sessionid,
                    "ds_user_id": settings.ds_user_id,
                }
            )
            return client, local_label, None
        except (LoginRequired, Exception) as e:
            raise RuntimeError(
                "Session TOML invalide ou expirée — mets à jour sessionid "
                f"dans Settings ou vide {local_label} pour relire le navigateur"
            ) from e

    from instree.config import is_public_mode

    # En public : ne pas lire les cookies du navigateur *du serveur*.
    if not is_public_mode():
        found = _cookies_from_browser()
        if found:
            browser, jar = found
            client = _login(jar)
            save_session_credentials(jar["sessionid"], jar.get("ds_user_id", ""))
            return (
                client,
                f"navigateur ({browser})",
                f"Session enregistrée dans {local_label}",
            )

    raise RuntimeError(
        "Pas de session configurée — colle sessionid et user id dans Paramètres, "
        "ou utilise « Tester la connexion »"
    )


def session_user(ig: Client) -> str:
    return ig.account_info().username
