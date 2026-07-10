# Instree

Outil local pour **surveiller tes abonnements mutuels Instagram** (personnes que tu suis et qui te suivent en retour), ou celles d'un autre compte configuré.

À chaque scan, Instree compare ta liste de mutuels avec le précédent, puis explore les abonnements de chacun (selon `watch_n`) :

- **`+` / `−` sur ta liste** — nouveau mutuel ou mutuel perdu
- **`~ @personne`** — cette personne a changé d'abonnements depuis le dernier scan
  - sous chaque `~` : `+` / `−` pour les comptes qu'elle a commencé ou arrêté de suivre

Historique en SQLite, journaux texte, interface web (**Home**, **Graph**, **Paramètres**), scans planifiés et démarrage automatique au boot.

## Interface web

| Page | Rôle |
|------|------|
| **Home** | Lancer un scan (incrémental ou baseline), historique, voir les variations |
| **Graph** | Visualiser les mutuels en graphe force-directed, avec groupes détectés (Louvain) |
| **Paramètres** | Session Instagram, limites de scan, intervalle, lancement au démarrage |

Interface en **français**, **anglais** ou **espagnol** (sélecteur en haut à droite).

## Prérequis

- **Python 3.11+**
- [uv](https://docs.astral.sh/uv/) (optionnel, accélère l'installation)
- Un compte Instagram connecté dans le navigateur **ou** les cookies `sessionid` / `ds_user_id`

Instree fonctionne sur **Linux**, **macOS** et **Windows**.

---

## Installation rapide

### Linux / macOS

```bash
git clone https://github.com/CloudDown/instree.git
cd instree
cp config/instree.local.toml.example config/instree.local.toml
./run
```

Ouvre [http://127.0.0.1:8765](http://127.0.0.1:8765).

### Windows

1. Installe **Python 3.11+** depuis [python.org](https://www.python.org/downloads/)  
   Coche **« Add python.exe to PATH »** pendant l'installation.  
   Ou en ligne de commande : `winget install Python.Python.3.11`

2. Clone le dépôt (Git for Windows, ou télécharge le ZIP et dézippe).

3. Double-clique **`run.bat`** à la racine du projet  
   (ou ouvre `cmd`, `cd` vers le dossier, puis `run.bat`).

4. Au premier lancement :
   - création de `.venv` et installation des dépendances ;
   - copie de `config\instree.local.toml.example` → `config\instree.local.toml` ;
   - ouverture automatique de [http://127.0.0.1:8765](http://127.0.0.1:8765).

5. Configure ta session Instagram (voir section ci-dessous), puis lance un scan depuis **Home**.

> **Antivirus / pare-feu** : autorise Python en local si Windows demande une confirmation pour `127.0.0.1:8765`.

Installation manuelle (Windows, PowerShell ou cmd) :

```bat
cd instree
py -3.11 -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\instree serve
```

Toujours lancer depuis la **racine du dépôt** (là où se trouvent `config\instree.toml` et `run.bat`).

---

## Session Instagram

Instree a besoin d'une session valide pour appeler l'API Instagram. Deux méthodes :

### 1. Récupération automatique (recommandée)

Si `sessionid` est **vide** dans la config, Instree lit les cookies du navigateur où tu es déjà connecté à Instagram.

Navigateurs testés : **Chrome**, **Edge**, **Brave**, **Firefox**, **Opera**, **Vivaldi**, **Chromium**.

**Étapes :**

1. Ouvre [instagram.com](https://www.instagram.com) dans le navigateur et connecte-toi.
2. Ferme **toutes les fenêtres** de ce navigateur (sur Windows, les cookies sont parfois verrouillés tant que le navigateur tourne).
3. Lance Instree (`./run` ou `run.bat`).
4. Va dans **Paramètres** → **Tester la connexion**.

Si ça fonctionne, la session est **enregistrée automatiquement** dans `config/instree.local.toml` pour les prochains lancements (sans relire le navigateur).

### 2. Récupération manuelle (si l'automatique échoue)

Utilise cette méthode si tu vois *« Pas de session configurée »*, *« Session TOML invalide »*, ou si Instree ne trouve pas les cookies (navigateur fermé, profil différent, navigateur non supporté, etc.).

Tu dois copier **deux** valeurs depuis les cookies Instagram :

| Cookie       | Obligatoire | Rôle                          |
|-------------|-------------|-------------------------------|
| `sessionid` | oui         | Identifiant de session        |
| `ds_user_id`| oui         | ID numérique de ton compte    |

#### Chrome ou Edge (Windows, Linux, macOS)

1. Va sur [https://www.instagram.com](https://www.instagram.com) et vérifie que tu es connecté.
2. Appuie sur **F12** (outils de développement).
3. Onglet **Application** (Edge : parfois **Stockage** / **Storage**).
4. Dans le panneau de gauche : **Cookies** → `https://www.instagram.com`.
5. Dans la liste, repère les lignes **`sessionid`** et **`ds_user_id`**.
6. Double-clique la **Value** de chaque cookie et copie-la (Ctrl+C).

   Exemple de `sessionid` (souvent avec des `%3A` à la place de `:` — c'est normal, colle tel quel) :
   ```
   1234567890%3Axxxxxxxx%3A5%3Ayyyyyyyy
   ```

7. Colle les valeurs dans **Paramètres** → champs **Session ID** et **User ID**, puis **Enregistrer**.
8. Clique **Tester la connexion**.

#### Firefox

1. Connecte-toi sur [instagram.com](https://www.instagram.com).
2. **F12** → onglet **Stockage** (Storage).
3. **Cookies** → `https://www.instagram.com`.
4. Copie `sessionid` et `ds_user_id` comme ci-dessus.

#### Coller dans le fichier de config (alternative)

Édite `config/instree.local.toml` :

```toml
[instagram]
sessionid = "COLLE_ICI_LE_sessionid"
ds_user_id = "COLLE_ICI_LE_ds_user_id"
```

Sauvegarde, relance Instree, teste dans **Paramètres**.

> Ce fichier est **gitignored** : tes cookies ne partent pas sur GitHub.

#### Dépannage session

| Problème | Piste |
|----------|--------|
| Cookies introuvables | Tu n'es pas connecté sur instagram.com dans **ce** navigateur / ce profil. |
| Auto échoue sur Windows | Ferme complètement Chrome/Edge, relance Instree. |
| « Session invalide » après quelques jours | Session expirée — refais la procédure manuelle ou reconnecte-toi sur Instagram. |
| `sessionid` vide dans DevTools | Utilise l'onglet Application/Stockage, pas `document.cookie` dans la console (`sessionid` est souvent **HttpOnly**). |
| Compte avec 2FA / alerte Instagram | Connecte-toi d'abord dans le navigateur, valide la sécurité, **puis** copie les cookies. |

Pour **forcer** une nouvelle lecture navigateur : vide `sessionid` et `ds_user_id` dans `config/instree.local.toml`, enregistre, ferme le navigateur, relance Instree.

---

## Lancer le site web

| OS | Commande |
|----|----------|
| Linux / macOS | `./run` |
| Windows | `run.bat` |

Interface : [http://127.0.0.1:8765](http://127.0.0.1:8765)

Depuis **Home** : scan incrémental, baseline (premier scan), arrêt d'un scan en cours, navigation dans l'historique.

Premier scan en CLI (optionnel) :

```bash
# Linux / macOS
.venv/bin/instree scan --init

# Windows
.venv\Scripts\instree scan --init
```

---

## Configuration

| Fichier | Rôle |
|---------|------|
| `config/instree.toml` | Config partagée (scan, web, planification) |
| `config/instree.local.toml` | Secrets Instagram (gitignored) |

```toml
# config/instree.toml
[scan]
username = ""          # vide = compte de la session
n = "MAX"              # nombre de mutuels à suivre (ou MAX = tous)
watch_n = "MAX"        # abonnements explorés par mutuel (ou MAX = tous)
page_sleep = 0.6       # pause entre requêtes API (secondes)
page_size = 200        # taille de page API (12–200)

[web]
host = "127.0.0.1"
port = 8765
autostart_on_boot = false

[schedule]
interval_minutes = 0   # 0 = désactivé ; scans auto tant que le serveur tourne
```

```toml
# config/instree.local.toml
[instagram]
sessionid = "..."
ds_user_id = "..."
```

Les champs peuvent aussi être remplis depuis **Paramètres** dans l'interface web.

---

## Planification et démarrage automatique

Dans **Paramètres** :

- **Intervalle (minutes)** — scans automatiques tant que le serveur tourne
- **Lancement au démarrage** — enregistre un raccourci au démarrage de la session :
  - Linux : `~/.config/autostart/instree.desktop`
  - Windows : `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\instree-serve.bat`
  - macOS : `~/Library/LaunchAgents/com.instree.serve.plist`

La session Instagram doit rester valide dans `config/instree.local.toml` pour les scans en arrière-plan (sans navigateur ouvert).

---

## Données locales (`data/`, gitignored)

- `watch.db` — historique des scans
- `journal/*.log` — journaux texte
- `serve.log` — sortie du serveur si lancé au démarrage (Windows/macOS)
