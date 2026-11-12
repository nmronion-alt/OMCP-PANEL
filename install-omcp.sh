#!/usr/bin/env bash
set -Eeuo pipefail
# OMCP installer for Ubuntu/Debian. Supports systemd VPS and no-systemd shells.
REPO="https://raw.githubusercontent.com/nmronion-alt/onion-hub/main"
APP="/opt/omcp"
DATA="/var/lib/omcp"
if [[ "${EUID}" -ne 0 ]]; then echo "Run with sudo/root: sudo bash install-omcp.sh"; exit 1; fi
if ! command -v apt-get >/dev/null; then echo "Supported target: Ubuntu/Debian."; exit 1; fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 curl ca-certificates openjdk-21-jre-headless
id omcp >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --create-home --shell /usr/sbin/nologin omcp
install -d -o root -g omcp -m 0750 "$APP"
install -d -o omcp -g omcp -m 0750 "$DATA" "$DATA/servers" "$DATA/backups"
curl -fsSL "$REPO/agent/omcp_agent.py" -o "$APP/omcp_agent.py"
curl -fsSL "$REPO/index.html" -o "$APP/index.html"
chown root:omcp "$APP/omcp_agent.py" "$APP/index.html"
chmod 0640 "$APP/omcp_agent.py" "$APP/index.html"

if [[ -S /run/systemd/private ]] && [[ "$(ps -p 1 -o comm= 2>/dev/null | tr -d ' ')" == "systemd" ]] && command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
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
  echo "OMCP service status:"
  systemctl --no-pager --full status omcp || true
  echo "First-run Admin Key: sudo journalctl -u omcp -n 80 --no-pager"
else
  echo "systemd not detected; using a background process (Cloud Shell / container mode)."
  if [[ -f "$DATA/agent.pid" ]] && kill -0 "$(cat "$DATA/agent.pid")" 2>/dev/null; then
    echo "Existing OMCP process detected (PID $(cat "$DATA/agent.pid")); not starting a duplicate."
  else
    rm -f "$DATA/agent.pid"
    runuser -u omcp -- sh -c 'nohup env OMCP_HOST=127.0.0.1 OMCP_PORT=8765 OMCP_DATA=/var/lib/omcp OMCP_WEB=/opt/omcp/index.html /usr/bin/python3 /opt/omcp/omcp_agent.py </dev/null >>/var/lib/omcp/agent.log 2>&1 & echo $! >/var/lib/omcp/agent.pid'
    sleep 2
    if [[ -f "$DATA/agent.pid" ]] && kill -0 "$(cat "$DATA/agent.pid")" 2>/dev/null; then
      echo "OMCP background process started (PID $(cat "$DATA/agent.pid"))."
    else
      echo "OMCP did not start. Recent log:"
      tail -n 60 "$DATA/agent.log" 2>/dev/null || true
      exit 1
    fi
  fi
  echo "First-run Admin Key / startup log: sudo cat $DATA/agent.log"
  echo "Stop this no-systemd process: sudo kill \$(cat $DATA/agent.pid)"
fi
echo
echo "OMCP panel listener: http://127.0.0.1:8765"
echo "API is bound to localhost only. For a public VPS, put Cloudflare Access in front of a Cloudflare Tunnel."
echo "OpenJDK 21 was installed. Verify with: java -version"
echo "Cloud Shell sessions are temporary; processes and files may be lost when the session ends."
echo "No Minecraft TCP relay is configured by this installer."
