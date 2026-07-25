# Structure du dépôt

Instree = **une seule app**, deux façons de la lancer :

| | **Instree Desktop** | **Instree Web** |
|---|---------------------|-----------------|
| Commande | `./run` | `./run-public` |
| Utilisateurs | 1 (toi) | plusieurs (login) |
| Données | `config/` + `data/` | `serveur/` (ou `INSTREE_HOME`) |
| Cookies IG | lecture navigateur possible | collage manuel sessionid |

## Arborescence

```
instree/                 # code Python (package)
  cli.py                 # point d'entrée CLI
  config.py              # chemins, profils, TOML
  scan.py, store.py, …   # logique métier Instagram
  web/                   # FastAPI, auth, templates, static

bin/                     # scripts de lancement
  run-desktop            # Instree Desktop
  run-web                # Instree Web

config/                  # config Desktop (template + profils locaux)
data/                    # SQLite Desktop (gitignored)

serveur/                 # données Web en dev (gitignored)
  instree.toml           # host / port du serveur
  secret.key             # cookies de session
  accounts.db            # comptes utilisateurs
  users/<id>/            # config + data par utilisateur

docs/                    # documentation
deploy/                  # exemples prod (systemd, etc.)
scripts/                 # outils dev (screenshots, …)

run, run-public          # raccourcis vers bin/
pyproject.toml           # dépendances Python
```

## Variables d'environnement

| Variable | Effet |
|----------|--------|
| `INSTREE_PUBLIC=1` | active le mode Web |
| `INSTREE_HOME=/chemin` | racine des données Web (remplace `serveur/`) |

## Production (Raspberry Pi, VPS)

Voir [deploy-raspberry-pi.md](deploy-raspberry-pi.md).
