# Structure du dépôt

```
instree/                 # package Python
  core/                  # métier partagé
  desktop/               # Instree Desktop
  web/                   # Instree Web

bin/                     # lanceurs (Desktop + Web)
deploy/                  # systemd, etc.
docs/
scripts/                 # outils dev
var/                     # données runtime (gitignored)
  desktop/config/        # config + profils Desktop
  desktop/data/          # SQLite Desktop
  web/                   # comptes + users/ Web

pyproject.toml
README.md
uv.lock
```

## Commandes

| | Desktop | Web |
|---|---------|-----|
| Lancer | `./bin/run-desktop` | `./bin/run-web` (ngrok par défaut ; `--no-ngrok` pour LAN) |
| CLI | `instree serve` | `instree-web` |
| Données | `var/desktop/` | `var/web/` ou `INSTREE_HOME` |

Voir [deploy-raspberry-pi.md](deploy-raspberry-pi.md) pour Instree Web en prod.
