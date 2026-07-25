# Instree

Surveillance **locale** de tes abonnements mutuels Instagram (tu les suis, ils te suivent). Chaque scan compare ta liste, puis les abonnements de chaque mutuel.

| Symbole | Sens |
|---------|------|
| `>` | ajouté à **ta** liste |
| `+` / `−` | un mutuel s’est abonné / désabonné |
| `×` | compte supprimé ou renommé |
| pastille jaune **mutuel** | déjà dans ta liste |
| pastille bleue | compte vérifié |

Interface web en FR / EN / ES. Données Desktop dans `var/desktop/` (SQLite).

Deux modes :

| | **Instree Desktop** | **Instree Web** |
|---|---------------------|-----------------|
| Lancement | `./bin/run-desktop` · `instree serve` | `./bin/run-web` · `instree-web` |
| Package | `instree.desktop` | `instree.web` |
| Usage | 1 personne, chez toi | multi-comptes (Pi, VPS…) |
| Données | `var/desktop/` | `var/web/` ou `INSTREE_HOME` |

Structure du dépôt : [docs/STRUCTURE.md](docs/STRUCTURE.md) · déploiement Pi : [docs/deploy-raspberry-pi.md](docs/deploy-raspberry-pi.md).

---

## Installation

### Windows

1. Télécharge le projet (ZIP GitHub ou `git clone`).
2. Double-clique **`bin\run-desktop.bat`**.

Au premier lancement : Python (winget si besoin), dépendances, config, ouverture de [http://127.0.0.1:1488](http://127.0.0.1:1488).

### Linux / macOS

```bash
git clone https://github.com/CloudDown/instree.git
cd instree
./bin/run-desktop
```

Au premier lancement : installation de **uv** si besoin, Python 3.11+, dépendances, config locale, ouverture du navigateur sur [http://127.0.0.1:1488](http://127.0.0.1:1488).

Ensuite : **Paramètres** → session Instagram → **Home** → lancer un scan.

Si Instagram limite les requêtes (`feedback_required`), Instree affiche une pause avec compte à rebours puis réessaie. Les snapshots des mutuels sont sauvés au fil de l’eau : tu peux **relancer** un scan après un blocage / cancel — les comptes déjà traités sont sautés, la liste mutuelle et les fetch en cours reprennent là où ils se sont arrêtés. Avec `watch_n = MAX`, Instree charge tous les abonnements de chaque mutuel (la barre utilise le vrai compte Instagram).

---

## Session Instagram

**Auto (recommandé)**  
Connecté sur [instagram.com](https://www.instagram.com) → ferme le navigateur → **Paramètres** → **Tester la connexion**.  
Les cookies vont dans `var/desktop/config/profiles/<session>/local.toml` (gitignored). Chaque session a ses propres paramètres et son historique (`var/desktop/data/profiles/<session>/`).

**Manuel** si l’auto échoue : F12 → Cookies → `instagram.com` → copie `sessionid` et `ds_user_id` dans **Paramètres**.

Dans **Paramètres**, le bouton **+** crée une nouvelle session Instagram (config + données isolées). Clique une session dans la liste pour basculer. **Exporter** / **Importer** sauve ou restaure une session (ZIP, sans cookies IG).

---

## Les 3 pages

### Home — scans & historique

![Home](docs/screenshots/readme-home.png)

Lancer un scan, parcourir l’historique, et lire les changements d’un scan :

- liste des scans à gauche (baseline, dates, nombre de changements) ;
- détail groupé par mutuel suivi, avec compteurs `(+N −M)` ;
- recherche `@utilisateur` (accents ignorés, historique mis en avant) ;
- légende cliquable : masquer un type de ligne (ajouts, suppressions, mutuels, vérifiés…).

### Graph — réseau des mutuels

![Graph](docs/screenshots/readme-graph.png)

Vue force-directed de ta communauté :

- nœuds colorés par groupe (communautés détectées) ;
- panneau **Display** : taille des nœuds, groupes, liens intra / inter ;
- recherche d’un `@` avec zoom sur le nœud ;
- mode plein écran pour explorer confortablement.

### Paramètres — session & config

![Paramètres](docs/screenshots/readme-settings.png)

Configurer Instree sans éditer les fichiers à la main :

- session Instagram (`sessionid` / `ds_user_id`) et test de connexion ;
- taille des scans (`n`, `watch_n`, délais API) ;
- planification (intervalle auto, lancement au démarrage) ;
- host / port de l’interface web.

---

## Config utile

| Fichier | Contenu |
|---------|---------|
| `var/desktop/config/instree.toml` | host, port, session active |
| `var/desktop/config/profiles/<id>/settings.toml` | scan / planification |
| `var/desktop/config/profiles/<id>/local.toml` | cookies Instagram (gitignored) |
| `var/desktop/data/profiles/<id>/` | SQLite + journal |

Les mêmes options sont éditables dans **Paramètres**.

---

## Instree Web (multi-utilisateurs)

Même UI que Desktop (cœur partagé `instree.core`).  
Différences : **login / inscription**, **Déconnexion**, données isolées par utilisateur.

```bash
./bin/run-web                 # ngrok (HTTPS public, défaut)
./bin/run-web --no-ngrok      # LAN seulement
# ou : .venv/bin/instree-web --no-ngrok
```

Données **hors git** (`var/web/` en dev, ou `INSTREE_HOME` en prod) :

```
var/web/   # ou INSTREE_HOME
  instree.toml       # host/port (défaut 0.0.0.0:1488)
  secret.key
  accounts.db
  users/<id>/        # config + data par utilisateur
```

**Raspberry Pi** : [docs/deploy-raspberry-pi.md](docs/deploy-raspberry-pi.md).  
En production : reverse-proxy (Caddy / nginx) + HTTPS devant le bind.
