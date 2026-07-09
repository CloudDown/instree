# Instree

Outil local pour **surveiller ta liste d'abonnements Instagram** (ou celle d'un compte configuré).

À chaque scan, Instree compare les N derniers abonnements (100 par défaut) avec le précédent et journalise :

- `+` nouveaux abonnements
- `-` désabonnements
- `~` évolution du nombre d'abonnements des comptes que tu suis

Historique en SQLite, journaux texte, interface web et scans planifiés.

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

## Lancer le site web

```bash
./run
```

Ouvre [http://127.0.0.1:8765](http://127.0.0.1:8765) — interface pour lancer les scans, voir l'historique et les changements (`+` / `-` / `~`).

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

## Planification

Dans **Paramètres** :

- **Heures fixes** et **intervalle (minutes)** — scans automatiques tant que `instree serve` tourne
- **Lancement au démarrage** — lance `instree serve` à la connexion (Linux, Windows, macOS)

La session Instagram doit être configurée dans `instree.local.toml` pour les scans sans navigateur.

## Données locales (`data/`, gitignored)

- `watch.db` — historique
- `journal/*.log` — journaux
