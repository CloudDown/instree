# Instree Web sur Raspberry Pi

## Prérequis Pi

- Raspberry Pi OS 64-bit, Python 3.11+
- `ngrok` installé et authtoken configuré (`ngrok config add-authtoken …`)
- SSH activé

> Sur les Pi récentes, le mot de passe par défaut `pi` n’existe plus. Utilise le user/mdp que tu as configurés, ou une clé SSH.

## Déploiement automatique (depuis ton PC)

Le mot de passe `pi` est bon — c’est le client OpenSSH local qui échouait (ssh-askpass sans TTY). Utilise :

```bash
python3 deploy/pi/deploy_paramiko.py
```

Variables optionnelles : `PI_HOST`, `PI_PASS`, `PI_DIR`, `PI_DATA`.

## Déploiement manuel (sur la Pi)

```bash
# Sur ton PC — copie le projet
rsync -avz --exclude .git --exclude .venv --exclude var/web/users \
  ./ pi@192.168.2.170:/home/pi/instree/

# Sur la Pi
ssh pi@192.168.2.170
cd ~/instree
chmod +x deploy/pi/setup-remote.sh
./deploy/pi/setup-remote.sh
```

## Résultat

| Élément | Chemin |
|---------|--------|
| Code | `/home/pi/instree` |
| Données (comptes, scans) | `/var/lib/instree` |
| Service | `instree-web.service` |

Le service lance **`instree-web --ngrok --host 0.0.0.0`** au boot.

```bash
sudo systemctl status instree-web
journalctl -u instree-web -f
```

URL ngrok affichée dans les logs au démarrage.

LAN : `http://192.168.2.170:1488/login`

## Activer le mot de passe SSH (si besoin)

Sur la Pi, en local ou via écran :

```bash
sudo raspi-config   # Interface Options → SSH
# ou /etc/ssh/sshd_config : PasswordAuthentication yes
sudo systemctl restart ssh
```

## Mise à jour

```bash
python3 deploy/pi/ssh_deploy.py
# puis sur la Pi :
sudo systemctl restart instree-web
```
