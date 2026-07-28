#!/usr/bin/env bash
# Installation Instree Web sur Raspberry Pi (systemd + ngrok au boot)
set -euo pipefail

INSTREE_DIR="${INSTREE_DIR:-/home/pi/instree}"
DATA_DIR="${INSTREE_DATA:-/var/lib/instree}"
SERVICE_USER="${SERVICE_USER:-pi}"
SUDO_PASS="${SUDO_PASS:-pi}"

sudo_cmd() {
  echo "$SUDO_PASS" | sudo -S "$@"
}

echo "==> Instree Web — installation Pi"
echo "    code  : $INSTREE_DIR"
echo "    data  : $DATA_DIR"
echo

sudo_cmd mkdir -p "$DATA_DIR"
sudo_cmd chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"

cd "$INSTREE_DIR"

if [[ ! -x .venv/bin/instree-web ]]; then
  echo "==> Environnement Python…"
  if command -v uv >/dev/null 2>&1; then
    uv sync
  else
    python3 -m venv .venv
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q -e .
  fi
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "==> Installation cloudflared…"
  arch="$(uname -m)"
  case "$arch" in
    aarch64|arm64) deb="cloudflared-linux-arm64.deb" ;;
    armv7l|armhf) deb="cloudflared-linux-arm.deb" ;;
    x86_64|amd64) deb="cloudflared-linux-amd64.deb" ;;
    *)
      echo "[AVERT] arch non supportée pour cloudflared: $arch"
      deb=""
      ;;
  esac
  if [[ -n "$deb" ]]; then
    curl -fsSL -o /tmp/cloudflared.deb \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/$deb"
    sudo_cmd dpkg -i /tmp/cloudflared.deb || sudo_cmd apt-get install -y -f
    rm -f /tmp/cloudflared.deb
  fi
fi

if command -v cloudflared >/dev/null 2>&1; then
  echo "[OK] cloudflared : $(command -v cloudflared) (tunnel sans page d'avertissement)"
elif command -v ngrok >/dev/null 2>&1; then
  echo "[OK] ngrok : $(command -v ngrok) (page d'avertissement possible — préfère cloudflared)"
else
  echo "[AVERT] ni cloudflared ni ngrok dans le PATH — pas de tunnel public."
fi

export INSTREE_HOME="$DATA_DIR"
INSTREE_HOME="$DATA_DIR" .venv/bin/python3 -c "
from instree.core.config import bootstrap_web_home, enable_web_mode, ensure_server_schedule
enable_web_mode()
bootstrap_web_home()
ensure_server_schedule(daily_hour=2, timezone='America/Montreal')
print('OK schedule America/Montreal 02:00')
"

echo "==> Service systemd"
UNIT="/tmp/instree-web.service"
cat > "$UNIT" <<EOF
[Unit]
Description=Instree Web (FastAPI + tunnel public)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTREE_DIR
Environment=INSTREE_HOME=$DATA_DIR
Environment=INSTREE_WEB=1
Environment=INSTREE_HTTPS=1
Environment=INSTREE_ALLOW_REGISTER=1
Environment=PATH=$INSTREE_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$INSTREE_DIR/.venv/bin/instree-web --ngrok --host 0.0.0.0
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo_cmd cp "$UNIT" /etc/systemd/system/instree-web.service
rm -f "$UNIT"

sudo_cmd systemctl daemon-reload
sudo_cmd systemctl enable instree-web
sudo_cmd systemctl restart instree-web

echo
echo "==> Statut"
sleep 2
sudo_cmd systemctl status instree-web --no-pager -l || true
echo
echo "Logs : journalctl -u instree-web -f"
echo "LAN  : http://$(hostname -I | awk '{print $1}'):1488/login"
