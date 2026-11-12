#!/usr/bin/env bash
set -Eeuo pipefail
# OMCP single-command installer for Ubuntu/Debian. No Pterodactyl/Wings.
REPO="https://raw.githubusercontent.com/nmronion-alt/onion-hub/main"
APP="/opt/omcp"
DATA="/var/lib/omcp"
if [[ "${EUID}" -ne 0 ]]; then echo "Run with sudo/root: sudo bash install-omcp.sh"; exit 1; fi
if ! command -v apt-get >/dev/null || ! command -v systemctl >/dev/null; then echo "Supported target: Ubuntu/Debian with systemd."; exit 1; fi
apt-get update
apt-get install -y python3 curl ca-certificates
id omcp >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --create-home --shell /usr/sbin/nologin omcp
install -d -o root -g omcp -m 0750 "$APP"
install -d -o omcp -g omcp -m 0750 "$DATA" "$DATA/servers" "$DATA/backups"
curl -fsSL "$REPO/agent/omcp_agent.py" -o "$APP/omcp_agent.py"
curl -fsSL "$REPO/index.html" -o "$APP/index.html"
chown root:omcp "$APP/omcp_agent.py" "$APP/index.html"
chmod 0640 "$APP/omcp_agent.py" "$APP/index.html"
cat >/etc/systemd/system/omcp.service <<'UNIT'
[Unit]
Description=OMCP Onion Minecraft Panel
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=omcp
Group=omcp
WorkingDirectory=/opt/omcp
Environment=OMCP_HOST=127.0.0.1
Environment=OMCP_PORT=8765
Environment=OMCP_DATA=/var/lib/omcp
Environment=OMCP_WEB=/opt/omcp/index.html
ExecStart=/usr/bin/python3 /opt/omcp/omcp_agent.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/omcp
UMask=0027
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now omcp
sleep 2
echo
echo "OMCP installed. Local panel: http://127.0.0.1:8765"
echo "First-run Admin Key (save it): sudo journalctl -u omcp -n 80 --no-pager"
echo "API is localhost-only. Put Cloudflare Access in front of a Tunnel to localhost:8765."
echo "Java is not installed by this script; install a compatible runtime before creating servers."
echo "No Minecraft TCP relay is configured by this installer."
