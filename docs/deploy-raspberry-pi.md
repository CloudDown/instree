# Instree Web sur Raspberry Pi

**Oui, c’est faisable.** Instree est léger : Python + FastAPI + SQLite, pas de GPU, peu de RAM.

## Prérequis

- Raspberry Pi 4/5 (2 Go RAM minimum, 4 Go confortable)
- Raspberry Pi OS 64-bit (Bookworm ou plus récent)
- Python 3.11+
- Accès réseau stable (Instagram = beaucoup de requêtes HTTP)

## Installation

```bash
git clone https://github.com/CloudDown/instree.git
cd instree

# Installe les deps (une fois)
./run-public --help   # ou ./bin/run-web --help — déclenche l'install si besoin

# Données persistantes hors du dépôt (recommandé)
sudo mkdir -p /var/lib/instree
sudo chown "$USER:$USER" /var/lib/instree
export INSTREE_HOME=/var/lib/instree
```

Premier lancement :

```bash
./run-public
# → crée /var/lib/instree/instree.toml, secret.key, accounts.db
```

Ouvre `http://<ip-du-pi>:1488/login`, crée un compte, colle tes cookies Instagram dans Paramètres.

## Service systemd (démarrage auto)

Copie et adapte `deploy/systemd/instree-web.service.example` :

```bash
sudo cp deploy/systemd/instree-web.service.example /etc/systemd/system/instree-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now instree-web
sudo systemctl status instree-web
```

## Accès depuis Internet

Sur le Pi seul, `./run-public` écoute en LAN (`0.0.0.0:1488`).

Pour un vrai site public :

1. **Reverse proxy** (Caddy ou nginx) + HTTPS (Let’s Encrypt)
2. Ou **`./run-public --ngrok`** pour tester vite
3. DNS → IP fixe ou DynDNS sur ta box

Exemple Caddy (domaine `instree.example.com`) :

```
instree.example.com {
    reverse_proxy 127.0.0.1:1488
}
```

Instree gère déjà les en-têtes proxy (`ProxyHeadersMiddleware`) pour ngrok / reverse-proxy.

## Pare-feu

Ouvre le port si tu accèdes en LAN sans proxy :

```bash
sudo ufw allow 1488/tcp
```

## Limites à connaître

| Sujet | Détail |
|-------|--------|
| Cookies Instagram | pas de lecture Chrome sur le Pi → sessionid / ds_user_id à coller |
| Scans longs | OK sur Pi 4 ; un scan MAX peut prendre du temps |
| SQLite | suffisant pour usage perso / petit groupe ; sauvegarde `/var/lib/instree` |
| Instagram | rate limits identiques partout ; pas lié au Pi |

## Sauvegarde

```bash
sudo systemctl stop instree-web
tar czf instree-backup-$(date +%F).tar.gz -C /var/lib instree
sudo systemctl start instree-web
```
