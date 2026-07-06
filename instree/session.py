"""Connexion Instagram (session.toml ou cookies navigateur)."""
from instagrapi import Client
from instagrapi.exceptions import LoginRequired

from instree.config import CONFIG


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
    toml_present = CONFIG.is_file()
    toml_empty = False

    if toml_present:
        try:
            import tomllib
            ig_cfg = tomllib.loads(CONFIG.read_text()).get("instagram", {})
            sid = str(ig_cfg.get("sessionid", "")).strip()
            if sid:
                client = _login({
                    "sessionid": sid,
                    "ds_user_id": str(ig_cfg.get("ds_user_id", "")).strip(),
                })
                return client, "session.toml", None
            toml_empty = True
        except (LoginRequired, Exception):
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
                        "session.toml présent mais vide — cookies navigateur utilisés "
                        "(voir session.toml.example)"
                    )
                return client, f"navigateur ({b})", note
        except Exception:
            pass

    if toml_empty:
        raise RuntimeError(
            "session.toml vide et aucun cookie Instagram dans le navigateur — "
            "remplis session.toml ou connecte-toi sur instagram.com"
        )
    raise RuntimeError(
        "Pas de session — copie session.toml.example → session.toml, "
        "ou connecte-toi à instagram.com dans ton navigateur"
    )


def session_user(ig: Client) -> str:
    return ig.account_info().username
