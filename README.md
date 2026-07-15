# Instree

Surveillance locale de tes **abonnements mutuels Instagram** (tu les suis, ils te suivent).

Chaque scan compare ta liste, puis les abonnements de chaque mutuel :

| Affichage | Sens |
|-----------|------|
| `>` | ajouté à **ta** liste |
| `+` / `−` | un mutuel s’est abonné / désabonné |
| `×` | compte supprimé ou renommé |
| pastille jaune **mutuel** | déjà dans ta liste |
| pastille bleue | compte vérifié |

Interface web : **Home** (scans + historique), **Graph**, **Paramètres**. FR / EN / ES.

---

## Windows

1. Télécharge le projet (ZIP GitHub ou `git clone`).
2. Double-clique **`run.bat`**.

Au premier lancement, tout est automatique : **Python** (via winget si besoin), dépendances, config, ouverture de [http://127.0.0.1:8765](http://127.0.0.1:8765).

Ensuite : **Paramètres** → session Instagram → **Home** → lancer un scan.

---

## Linux / macOS

```bash
git clone https://github.com/CloudDown/instree.git
cd instree
cp config/instree.local.toml.example config/instree.local.toml
./run
```

→ [http://127.0.0.1:8765](http://127.0.0.1:8765)

---

## Session Instagram

**Auto (recommandé)**  
Connecté sur [instagram.com](https://www.instagram.com) → ferme le navigateur → lance Instree → **Paramètres** → **Tester la connexion**.  
Les cookies sont enregistrés dans `config/instree.local.toml` (gitignored).

**Manuel** si l’auto échoue : F12 → Application / Stockage → Cookies → `instagram.com` → copie `sessionid` et `ds_user_id` dans **Paramètres**.

---

## Config utile

| Fichier | Contenu |
|---------|---------|
| `config/instree.toml` | `n`, `watch_n`, port, intervalle de scan |
| `config/instree.local.toml` | session Instagram |

Dans **Paramètres** : scans auto (intervalle) et lancement au démarrage de la session.

Données locales dans `data/` (base SQLite + journaux).
