# Instree

**Local** monitoring of your mutual Instagram follows (you follow them, they follow you). Each scan compares your list, then each mutual’s following.

| Symbol | Meaning |
|--------|---------|
| `>` | added to **your** list |
| `+` / `−` | a mutual followed / unfollowed |
| `×` | account deleted or renamed |
| yellow **mutual** badge | already on your list |
| blue badge | verified account |

Web UI in FR / EN / ES. Desktop data in `var/desktop/` (SQLite).

Two modes:

| | **Instree Desktop** | **Instree Web** |
|---|---------------------|-----------------|
| Launch | `./bin/run-desktop` · `instree serve` | `./bin/run-web` · `instree-web` |
| Package | `instree.desktop` | `instree.web` |
| Usage | 1 person, at home | multi-account (Pi, VPS…) |
| Data | `var/desktop/` | `var/web/` or `INSTREE_HOME` |

Repo layout: see [AGENTS.md](AGENTS.md) · Pi deploy: [deploy/pi/README.md](deploy/pi/README.md).

---

## Installation

### Windows

1. Download the project (GitHub ZIP or `git clone`).
2. Double-click **`bin\run-desktop.bat`**.

On first launch: Python (winget if needed), dependencies, config, opens [http://127.0.0.1:1488](http://127.0.0.1:1488).

### Linux / macOS

```bash
git clone https://github.com/CloudDown/instree.git
cd instree
./bin/run-desktop
```

On first launch: installs **uv** if needed, Python 3.11+, dependencies, local config, opens the browser at [http://127.0.0.1:1488](http://127.0.0.1:1488).

Then: **Settings** → Instagram session → **Home** → start a scan.

If Instagram rate-limits requests (`feedback_required`), Instree shows a pause with a countdown then retries. Mutual snapshots are saved as they go: you can **resume** a scan after a block / cancel — already processed accounts are skipped, and the mutual list and in-flight fetches pick up where they left off. With `watch_n = MAX`, Instree loads every mutual’s full following (the progress bar uses the real Instagram count).

---

## Instagram session

**Auto (recommended)**  
Signed in on [instagram.com](https://www.instagram.com) → close the browser → **Settings** → **Test connection**.  
Cookies go into `var/desktop/config/profiles/<session>/local.toml` (gitignored). Each session has its own settings and history (`var/desktop/data/profiles/<session>/`).

**Manual** if auto fails: F12 → Cookies → `instagram.com` → copy `sessionid` and `ds_user_id` into **Settings**.

In **Settings**, the **+** button creates a new Instagram session (isolated config + data). Click a session in the list to switch. **Export** / **Import** saves or restores a session (ZIP, without IG cookies).

---

## The 3 pages

### Home — scans & history

![Home](docs/screenshots/readme-home.png)

Start a scan, browse history, and read changes from a scan:

- scan list on the left (baseline, dates, change count);
- detail grouped by watched mutual, with `(+N −M)` counters;
- `@user` search (accents ignored, history highlighted);
- clickable legend: hide a line type (adds, removals, mutuals, verified…).

### Graph — mutual network

![Graph](docs/screenshots/readme-graph.png)

Force-directed view of your community:

- nodes colored by group (detected communities);
- **Display** panel: node size, groups, intra / inter links;
- `@` search with zoom to the node;
- fullscreen mode for comfortable exploration.

### Settings — session & config

![Settings](docs/screenshots/readme-settings.png)

Configure Instree without editing files by hand:

- Instagram session (`sessionid` / `ds_user_id`) and connection test;
- scan size (`n`, `watch_n`, API delays);
- scheduling (auto interval, launch on start);
- web UI host / port.

---

## Useful config

| File | Contents |
|------|----------|
| `var/desktop/config/instree.toml` | host, port, active session |
| `var/desktop/config/profiles/<id>/settings.toml` | scan / scheduling |
| `var/desktop/config/profiles/<id>/local.toml` | Instagram cookies (gitignored) |
| `var/desktop/data/profiles/<id>/` | SQLite + journal |

The same options are editable in **Settings**.

---

## Instree Web (multi-user)

Same UI as Desktop (shared core `instree.core`).  
Differences: **login / signup**, **Logout**, data isolated per user.

```bash
./bin/run-web                 # ngrok (public HTTPS, default)
./bin/run-web --no-ngrok      # LAN only
# or: .venv/bin/instree-web --no-ngrok
```

Data **outside git** (`var/web/` in dev, or `INSTREE_HOME` in prod):

```
var/web/   # or INSTREE_HOME
  instree.toml       # host/port (default 0.0.0.0:1488)
  secret.key
  accounts.db
  users/<id>/        # config + data per user
```

**Raspberry Pi**: [deploy/pi/README.md](deploy/pi/README.md).  
In production: reverse proxy (Caddy / nginx) + HTTPS in front of the bind.
