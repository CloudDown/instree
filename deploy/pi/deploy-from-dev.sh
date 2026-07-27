#!/usr/bin/env bash
# Déploie Instree sur la Pi depuis la machine de dev (rsync + setup)
set -euo pipefail

PI_HOST="${PI_HOST:-pi@192.168.2.170}"
PI_DIR="${PI_DIR:-/home/pi/instree}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "==> Sync vers $PI_HOST:$PI_DIR"
rsync -avz --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'var/web/users' \
  --exclude 'var/web/accounts.db' \
  --exclude 'var/web/secret.key' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$ROOT/" "$PI_HOST:$PI_DIR/"

echo "==> Setup distant"
ssh "$PI_HOST" "chmod +x $PI_DIR/deploy/pi/setup-remote.sh && $PI_DIR/deploy/pi/setup-remote.sh"
