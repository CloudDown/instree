# Instree

Suivi des abonnements Instagram : ajouts (`+`), retraits (`-`), évolutions de comptes suivis (`~`).

## Prérequis (Linux)

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommandé) ou pip

## Installation

```bash
git clone https://github.com/CloudDown/instree.git
cd instree
cp instree.local.toml.example instree.local.toml
# Éditer instree.local.toml (sessionid, ds_user_id)
./run
```

Au premier `./run`, les dépendances s'installent seules. Ensuite pour scanner :

```bash
.venv/bin/instree scan --init
```

Ou avec uv installé manuellement avant :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Toujours lancer depuis la racine du dépôt (là où se trouve `instree.toml`).

## Usage CLI

```bash
./run                        # interface web (recommandé)
uv run instree scan          # incrémental
uv run instree scan -q       # silencieux (systemd)
uv run instree serve         # idem que ./run
```

## Configuration

| Fichier | Rôle |
|---------|------|
| `instree.toml` | Config partagée (scan, web, horaires) |
| `instree.local.toml` | Secrets Instagram (gitignored) |

```toml
# instree.toml
[scan]
n = 100

[schedule]
times = ["08:00", "20:00"]
```

```toml
# instree.local.toml
[instagram]
sessionid = "..."
ds_user_id = "..."
```

## Planification (systemd)

1. Remplir `sessionid` dans `instree.local.toml` (obligatoire — pas de navigateur en tâche planifiée).
2. Définir les heures dans `[schedule] times`.
3. Installer le timer :

```bash
cd /chemin/vers/instree    # racine du clone
uv run instree schedule install
systemctl --user daemon-reload
systemctl --user enable --now instree-scan.timer
```

Vérifier :

```bash
systemctl --user list-timers instree-scan.timer
systemctl --user start instree-scan.service
tail -f data/scheduler.log
```

Après changement d'horaires : `schedule install` puis `systemctl --user restart instree-scan.timer`.

`schedule install` détecte automatiquement `.venv/bin/instree` ou `python -m instree.cli` selon l'installation.

### cron (alternative)

```cron
0 8,20 * * * cd /chemin/vers/instree && .venv/bin/instree scan -q >> data/scheduler.log 2>&1
```

## Données locales (`data/`, gitignored)

- `watch.db` — historique
- `journal/*.log` — journaux
- `scheduler.log` — scans planifiés
