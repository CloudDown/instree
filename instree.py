"""Instree — OSINT Instagram : noms + comptes clés."""
import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes


# -------config-------

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "session.toml"
CACHE_DIR = ROOT / ".cache"
CACHE_TTL = 24 * 3600  # recherches
ACCOUNT_TTL = 7 * 86400  # métadonnées compte
TTY = sys.stdout.isatty()
RESET = "\033[0m" if TTY else ""
DIM = "\033[2m" if TTY else ""
BOLD = "\033[1m" if TTY else ""
BLUE = "\033[94m" if TTY else ""
GREEN = "\033[92m" if TTY else ""
YELLOW = "\033[93m" if TTY else ""
PINK = "\033[38;5;213m" if TTY else ""

BANNER = r"""
 _____          _                 
|_   _|        | |                
  | | _ __  ___| |_ _ __ ___  ___ 
  | || '_ \/ __| __| '__/ _ \/ _ \
 _| || | | \__ \ |_| | |  __/  __/
 \___/_| |_|___/\__|_|  \___|\___|                     
"""


def _pink(s):
    return f"{PINK}{s}{RESET}"


def _dim(s):
    return f"{DIM}{s}{RESET}"


def _bold(s):
    return f"{BOLD}{s}{RESET}"


def _titre(label: str, color: str) -> None:
    """Titre de section coloré, contenu en dessous en blanc."""
    print(f"\n{color}── {label} ──{RESET}")


# -------cache-------

def _cache_file(*parts: str) -> Path:
    safe = [re.sub(r"[^\w.-]+", "_", p) for p in parts]
    return CACHE_DIR.joinpath(*safe).with_suffix(".json")


def _cache_load(path: Path, ttl: int | None) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if ttl is not None and time.time() - data.get("ts", 0) > ttl:
        return None
    return data


def _cache_load_any(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _cache_save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["ts"] = time.time()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# -------session-------

def _login(jar: dict) -> Client:
    """Connecte instagrapi avec des cookies sessionid / ds_user_id."""
    c = Client()
    c.set_settings({
        "cookies": jar,
        "authorization_data": {
            "sessionid": jar["sessionid"],
            "ds_user_id": jar.get("ds_user_id", ""),
        },
    })
    c.account_info()  # vérifie que la session est valide
    return c


def connect() -> Client:
    """Récupère une session : session.toml d'abord, sinon cookies navigateur."""
    if CONFIG.is_file():
        try:
            import tomllib
            ig_cfg = tomllib.loads(CONFIG.read_text()).get("instagram", {})
            sid = str(ig_cfg.get("sessionid", "")).strip()
            if sid:
                return _login({"sessionid": sid, "ds_user_id": str(ig_cfg.get("ds_user_id", "")).strip()})
        except (LoginRequired, Exception):
            pass

    import browser_cookie3
    for b in ("firefox", "chrome", "chromium", "brave", "edge", "opera", "vivaldi", "librewolf"):
        try:
            jar = {
                c.name: c.value
                for c in getattr(browser_cookie3, b)(domain_name="instagram.com")
                if c.name in ("sessionid", "ds_user_id")
            }
            if jar.get("sessionid"):
                return _login(jar)
        except Exception:
            pass

    raise RuntimeError("Pas de session — remplis session.toml ou connecte-toi à instagram.com")


def session_user(ig: Client) -> str:
    """Username du compte connecté."""
    return ig.account_info().username


# -------comptes-------

def _u(x):
    """Convertit un profil instagrapi en dict simple."""
    return {
        "pk": str(x.pk),
        "username": x.username,
        "full_name": x.full_name or "",
    }


def _ig_call(label: str, fn, *args, **kwargs):
    """Appel API avec message clair en cas de rate limit Instagram."""
    try:
        return fn(*args, **kwargs)
    except PleaseWaitFewMinutes:
        raise RuntimeError(f"{label} : rate limit Instagram") from None
    except Exception as e:
        msg = str(e)
        if "feedback_required" in msg:
            raise RuntimeError(f"{label} : rate limit Instagram") from None
        raise


def _rate_limited(err: Exception) -> bool:
    return "rate limit" in str(err).lower()


class ComptePublic:
    """Compte public : recherche native dans abonnés ou abonnements (1 requête)."""

    def __init__(self, pk, username, ig, follower_count=0, following_count=0):
        self.pk, self.username, self._ig = pk, username, ig
        self.follower_count = follower_count
        self.following_count = following_count

    def _source(self) -> str:
        return "abonnés" if self.follower_count >= self.following_count else "abonnements"

    def _cache_path(self, nom: str) -> Path:
        return _cache_file("search", self.username, self._source(), _norm(nom) or nom)

    def chercher(self, nom: str, *, refresh: bool = False) -> tuple[str, list, str]:
        """Retourne (source, users, origine) — origine : api | cache | cache expiré."""
        source = self._source()
        path = self._cache_path(nom)

        if not refresh:
            hit = _cache_load(path, CACHE_TTL)
            if hit:
                return source, hit["users"], "cache"

        label = f"@{self.username} / {source}"
        try:
            if source == "abonnés":
                raw = _ig_call(label, self._ig.search_followers, self.pk, nom)
            else:
                raw = _ig_call(label, self._ig.search_following, self.pk, nom)
            users = [_u(x) for x in raw]
            _cache_save(path, {"source": source, "users": users})
            return source, users, "api"
        except RuntimeError as e:
            if not _rate_limited(e):
                raise
            stale = _cache_load_any(path)
            if stale:
                return source, stale["users"], "cache expiré"
            raise RuntimeError(
                f"{label} : rate limit — aucune entrée en cache. "
                "Attends 15–30 min ou relance quand une recherche aura réussi une fois."
            ) from None


class ComptePrive:
    """Compte privé : recommandations filtrées localement."""

    def __init__(self, pk, username, ig):
        self.pk, self.username, self._ig = pk, username, ig

    def _cache_path(self) -> Path:
        return _cache_file("recos", self.username)

    def chercher(self, nom: str, *, refresh: bool = False) -> tuple[str, list, str]:
        path = self._cache_path()

        def _filter(users: list) -> list:
            return [u for u in users if _match(nom, u)]

        if not refresh:
            hit = _cache_load(path, CACHE_TTL)
            if hit:
                return "recommandations", _filter(hit["users"]), "cache"

        label = f"@{self.username} / recommandations"
        try:
            raw = _ig_call(label, self._ig.user_similar_accounts, self.pk)
            users = [_u(x) for x in raw]
            _cache_save(path, {"users": users})
            return "recommandations", _filter(users), "api"
        except RuntimeError as e:
            if not _rate_limited(e):
                raise
            stale = _cache_load_any(path)
            if stale:
                return "recommandations", _filter(stale["users"]), "cache expiré"
            raise RuntimeError(f"{label} : rate limit — aucune entrée en cache") from None


def charger(ig, user, *, refresh: bool = False):
    """Charge un compte et retourne ComptePublic ou ComptePrive selon is_private."""
    username = user.lstrip("@").strip()
    path = _cache_file("account", username)

    if not refresh:
        hit = _cache_load(path, ACCOUNT_TTL)
        if hit:
            if hit["is_private"]:
                return ComptePrive(hit["pk"], hit["username"], ig)
            return ComptePublic(
                hit["pk"], hit["username"], ig,
                follower_count=hit["follower_count"],
                following_count=hit["following_count"],
            )

    u = _ig_call(f"@{username}", ig.user_info_by_username, username)
    data = {
        "pk": str(u.pk),
        "username": u.username,
        "is_private": bool(u.is_private),
        "follower_count": int(getattr(u, "follower_count", 0) or 0),
        "following_count": int(getattr(u, "following_count", 0) or 0),
    }
    _cache_save(path, data)

    if data["is_private"]:
        return ComptePrive(data["pk"], data["username"], ig)
    return ComptePublic(
        data["pk"], data["username"], ig,
        follower_count=data["follower_count"],
        following_count=data["following_count"],
    )


# -------matching-------

def _norm(s):
    """Normalise un texte : minuscules, sans accents ni ponctuation."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s.lower().strip())).strip()


def _match(nom, user) -> bool:
    """True si le nom cherché apparaît dans le username ou le nom complet."""
    q = _norm(nom)
    if not q:
        return False
    return q in _norm(user.get("full_name", "")) or q in _norm(user.get("username", ""))


# -------arbre-------

def _tree_line(prefix: str, is_last: bool, text: str) -> str:
    """Affiche une branche d'arbre (texte blanc)."""
    connector = "└── " if is_last else "├── "
    print(f"{prefix}{connector}{text}", flush=True)
    return prefix + ("    " if is_last else "│   ")


def _tree_list(prefix: str, labels: list[str]) -> None:
    """Affiche des lignes sœurs sous le même parent."""
    for i, label in enumerate(labels):
        _tree_line(prefix, i == len(labels) - 1, label)


# -------interface-------

def _split(items):
    """Découpe une liste de chaînes séparées par des virgules."""
    out = []
    for item in items:
        out.extend(x.strip() for x in item.split(",") if x.strip())
    return out


def _ask_list(title):
    """Demande une liste à l'utilisateur (saisie séparée par virgules)."""
    line = input(f"\n{_pink(title)} (séparés par des virgules) : ").strip()
    return _split([line]) if line else []


def _agreger(resultat) -> dict:
    """Compte les occurrences de chaque username (doublons = plusieurs comptes clés)."""
    compteur = {}
    for user in resultat:
        key = user["username"]
        if key not in compteur:
            compteur[key] = {"full_name": user["full_name"], "count": 0}
        compteur[key]["count"] += 1
    return dict(sorted(compteur.items(), key=lambda x: -x[1]["count"]))


def _afficher_resultats(tous_resultats):
    """Affiche les résultats — titre jaune, contenu blanc."""
    _titre("résultats", YELLOW)
    if not tous_resultats:
        print(_dim("  aucune correspondance"))
        return

    for nom, compteur in tous_resultats.items():
        print(f"\n  {_bold(f'«{nom}»')}")
        if not compteur:
            print(_dim("    aucun résultat"))
            continue
        print(_dim(f"    {'@compte':<22} {'nom':<26} occ."))
        print(_dim(f"    {'─' * 52}"))
        for username, info in compteur.items():
            occ = f"x{info['count']}" if info['count'] > 1 else "·"
            print(f"    @{username:<20} {info['full_name']:<26} {occ}")
    print()


# -------recherche-------

def chercher(ig, names, keys, *, refresh: bool = False):
    """
    Pour chaque nom × compte clé :
    - public  → search_followers ou search_following (1 requête, comme la barre IG)
    - privé   → recommandations filtrées
    Résultats mis en cache dans .cache/ (24 h).
    """
    names = [n.strip() for n in names if n.strip()]
    keys = [k.lstrip("@").strip() for k in keys if k.strip()]
    if not names or not keys:
        raise ValueError("noms et comptes clés requis")

    tous_resultats = {}

    _titre("recherche", GREEN)

    for i_nom, nom in enumerate(names):
        resultat = []
        is_last_nom = i_nom == len(names) - 1
        p_nom = _tree_line("", is_last_nom, _bold(f"«{nom}»"))

        for i_cle, cle in enumerate(keys):
            is_last_cle = i_cle == len(keys) - 1
            try:
                compte = charger(ig, cle, refresh=refresh)
            except Exception as e:
                _tree_line(p_nom, is_last_cle, f"@{cle}  {_dim('! Erreur :')} {e}")
                continue

            kind = "privé" if isinstance(compte, ComptePrive) else "public"
            p_cle = _tree_line(p_nom, is_last_cle, f"@{compte.username}  {_dim(f'({kind})')}")

            try:
                source, matches, origine = compte.chercher(nom, refresh=refresh)
            except RuntimeError as e:
                _tree_list(p_cle, [_dim(str(e))])
                continue

            matches = [u for u in matches if _match(nom, u)]
            resultat.extend(matches)

            origine_label = _dim(f"via {origine}")
            if isinstance(compte, ComptePublic):
                labels = [
                    _dim(f"choix: {source}  ({compte.follower_count} ab. / {compte.following_count} abo.)"),
                    _dim(f"{len(matches)} match(s)  {origine_label}"),
                ]
            else:
                labels = [_dim(f"{source}: {len(matches)} match(s)  {origine_label}")]

            if origine == "cache expiré":
                labels.append(_dim("rate limit — données cache (peuvent être anciennes)"))

            if matches:
                labels += [_bold(f"→ @{u['username']}  {u['full_name']}") for u in matches]
            else:
                labels.append(_dim("aucun match"))
            _tree_list(p_cle, labels)

            if i_cle < len(keys) - 1:
                time.sleep(2)

        tous_resultats[nom] = _agreger(resultat)

    return tous_resultats


# -------main-------

def _lire_entrees_interactif():
    """Affiche le banner et demande les noms + comptes clés à l'utilisateur."""
    print()
    print(_pink(BANNER))
    print()

    liste_noms = _ask_list("Noms à chercher")
    liste_comptes_cles = _ask_list("Comptes clés")
    return liste_noms, liste_comptes_cles


def _lire_entrees_cli(args):
    """Transforme les arguments -n et -k en listes (découpe les virgules)."""
    liste_noms = _split(args.name)
    liste_comptes_cles = _split(args.key)
    return liste_noms, liste_comptes_cles


def main():
    try:
        _run()
    except KeyboardInterrupt:
        print()
        print(_dim("interrompu"))
        sys.exit(130)


def _run():
    """Point d'entrée : session → recherche native → résultats."""

    parser = argparse.ArgumentParser(
        description="Instree — chercher des personnes via des comptes clés",
    )
    parser.add_argument(
        "-n", "--name",
        action="append",
        default=[],
        help='nom à chercher, ex: -n "Jean Dupont" (répétable, virgules ok)',
    )
    parser.add_argument(
        "-k", "--key",
        action="append",
        default=[],
        help='compte clé, ex: -k @ecole (répétable, virgules ok)',
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="ignorer le cache et refaire les requêtes Instagram",
    )
    args = parser.parse_args()

    aucun_argument = (len(args.name) == 0 and len(args.key) == 0)

    if aucun_argument:
        liste_noms, liste_comptes_cles = _lire_entrees_interactif()
    else:
        liste_noms, liste_comptes_cles = _lire_entrees_cli(args)

    if not liste_noms or not liste_comptes_cles:
        print("! Erreur : il faut au moins un nom ET un compte clé.")
        print('  Exemple : instree -n "Jean Dupont" -k @mon_ecole')
        sys.exit(1)

    _titre("session", BLUE)
    client_instagram = connect()
    print(f"  connecté en {_bold('@' + session_user(client_instagram))}")

    try:
        resultats = chercher(
            client_instagram,
            liste_noms,
            liste_comptes_cles,
            refresh=args.refresh,
        )
    except Exception as erreur:
        print(f"! Erreur : {erreur}")
        sys.exit(1)

    _afficher_resultats(resultats)


if __name__ == "__main__":
    main()
