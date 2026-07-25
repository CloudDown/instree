# Instree Web sur Raspberry Pi

**Oui, c’est faisable.** Instree Web est léger : Python + FastAPI + SQLite.

## Prérequis

- Raspberry Pi 4/5 (2 Go RAM minimum, 4 Go confortable)
- Raspberry Pi OS 64-bit
- Python 3.11+

## Installation

```bash
git clone https://github.com/CloudDown/instree.git
cd instree

# Installe les deps (via le lanceur Desktop une fois)
./bin/run-desktop --help >/dev/null || true

# Données persistantes hors du dépôt (recommandé)
sudo mkdir -p /var/lib/instree
sudo chown "$USER:$USER" /var/lib/instree
export INSTREE_HOME=/var/lib/instree
```

Premier lancement :

```bash
./bin/run-web --no-ngrok
# → crée INSTREE_HOME/instree.toml, secret.key, accounts.db
```

Ouvre `http://<ip-du-pi>:1488/login`.

## Service systemd

```bash
sudo cp deploy/systemd/instree-web.service.example /etc/systemd/system/instree-web.service
# Adapter User, WorkingDirectory, INSTREE_HOME
sudo systemctl daemon-reload
sudo systemctl enable --now instree-web
```

## Accès Internet

1. Reverse proxy (Caddy / nginx) + HTTPS
2. Ou `./bin/run-web` (ngrok) pour tester depuis l'extérieur
3. DNS → IP fixe ou DynDNS

```
instree.example.com {
    reverse_proxy 127.0.0.1:1488
}
```

## Limites

- Cookies Instagram : collage manuel (pas de lecture Chrome sur le Pi)
- SQLite suffisant pour usage perso / petit groupe
- Sauvegarde : arrêter le service, archiver `INSTREE_HOME`
