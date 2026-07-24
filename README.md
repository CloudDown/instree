# Instree

Surveillance **locale** de tes abonnements mutuels Instagram (tu les suis, ils te suivent). Chaque scan compare ta liste, puis les abonnements de chaque mutuel.

| Symbole | Sens |
|---------|------|
| `>` | ajouté à **ta** liste |
| `+` / `−` | un mutuel s’est abonné / désabonné |
| `×` | compte supprimé ou renommé |
| pastille jaune **mutuel** | déjà dans ta liste |
| pastille bleue | compte vérifié |

Interface web en FR / EN / ES. Données locales dans `data/` (SQLite). Mode **serveur public** multi-utilisateurs possible (voir plus bas).

---

## Installation

### Windows

1. Télécharge le projet (ZIP GitHub ou `git clone`).
2. Double-clique **`run.bat`**.

Au premier lancement : Python (winget si besoin), dépendances, config, ouverture de [http://127.0.0.1:8765](http://127.0.0.1:8765).

### Linux / macOS

```bash
git clone https://github.com/CloudDown/instree.git
cd instree
./run
```

Au premier lancement : installation de **uv** si besoin, Python 3.11+, dépendances, config locale, ouverture du navigateur sur [http://127.0.0.1:8765](http://127.0.0.1:8765).

Ensuite : **Paramètres** → session Instagram → **Home** → lancer un scan.

Si Instagram limite les requêtes (`feedback_required`), Instree affiche une pause avec compte à rebours puis réessaie. Les snapshots des mutuels sont sauvés au fil de l’eau : tu peux **relancer** un scan après un blocage / cancel — les comptes déjà traités sont sautés. Avec `watch_n = MAX`, Instree charge tous les abonnements de chaque mutuel (la barre utilise le vrai compte Instagram).

---

## Session Instagram

**Auto (recommandé)**  
Connecté sur [instagram.com](https://www.instagram.com) → ferme le navigateur → **Paramètres** → **Tester la connexion**.  
Les cookies vont dans `config/profiles/<session>/local.toml` (gitignored). Chaque session a ses propres paramètres et son historique (`data/profiles/<session>/`).

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
| `config/instree.toml` | host, port, session active |
| `config/profiles/<id>/settings.toml` | scan / planification de la session |
| `config/profiles/<id>/local.toml` | cookies Instagram (gitignored) |
| `data/profiles/<id>/` | SQLite + journal de la session |

Les mêmes options sont éditables dans **Paramètres**.

---

## Mode serveur public (multi-utilisateurs)

Pour héberger Instree derrière un DNS public, chaque visiteur a son **compte** (username + mot de passe) et ses propres sessions IG / scans, isolés sous `serveur/` (**hors git**).

```bash
# Linux / macOS
./run-public

# Exposer sur Internet via ngrok (HTTPS)
./run-public --ngrok

# ou
.venv/bin/instree serve --public
.venv/bin/instree serve --ngrok
```

```bat
REM Windows
run-public.bat
run-public.bat --ngrok
```

**ngrok** : installe [ngrok](https://ngrok.com/download), puis `ngrok config add-authtoken <token>`.  
`./run-public --ngrok` démarre le serveur public en local et affiche l’URL `https://….ngrok-free.app` (+ `/login`).

Au premier lancement, Instree crée :

```
serveur/
  instree.toml       # host/port (défaut 0.0.0.0:8765)
  secret.key         # signature des cookies de session
  accounts.db        # comptes
  users/<id>/        # config + data de chaque utilisateur
```

Puis ouvre `/login` : inscription → connexion → usage normal (sessions IG, scans).  
Le mode local (`./run` / `run.bat`) reste inchangé : pas d’auth, données dans `config/` + `data/`.

Place un reverse-proxy (HTTPS) devant le bind `0.0.0.0` en production.
