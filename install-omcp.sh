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
# Install cloudflared from Cloudflare's official Debian/Ubuntu repository.
install -d --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
chmod 0644 /usr/share/keyrings/cloudflare-main.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" >/etc/apt/sources.list.d/cloudflared.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y cloudflared
id omcp >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --create-home --shell /usr/sbin/nologin omcp
install -d -o root -g omcp -m 0750 "$APP"
install -d -o omcp -g omcp -m 0750 "$DATA" "$DATA/servers" "$DATA/backups"
curl -fsSL "$REPO/agent/omcp_agent.py" -o "$APP/omcp_agent.py"
curl -fsSL "$REPO/index.html" -o "$APP/index.html"
chown root:omcp "$APP/omcp_agent.py" "$APP/index.html"
chmod 0640 "$APP/omcp_agent.py" "$APP/index.html"

SYSTEMD_STATE=""
SYSTEMD_OK=0
if command -v systemctl >/dev/null 2>&1; then
  SYSTEMD_STATE="$(systemctl is-system-running 2>/dev/null || true)"
  # Do not trust the mere presence of systemctl or /run/systemd files.
  # PID 1 must actually be systemd and the manager bus must answer.
  PID1_EXE="$(readlink -f /proc/1/exe 2>/dev/null || true)"
  if [[ "$PID1_EXE" == *systemd* ]] && systemctl is-active --quiet default.target 2>/dev/null; then
    SYSTEMD_OK=1
  fi
fi
if [[ "$SYSTEMD_OK" == "1" ]]; then
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
  systemctl enable omcp
  if systemctl is-active --quiet omcp; then systemctl restart omcp; else systemctl start omcp; fi
  cat >/etc/systemd/system/omcp-quick-tunnel.service <<'TUNNEL'
[Unit]
Description=OMCP temporary Cloudflare Quick Tunnel
After=network-online.target omcp.service
Wants=network-online.target
[Service]
Type=simple
User=omcp
Group=omcp
ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8765
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
UMask=0027
[Install]
WantedBy=multi-user.target
TUNNEL
  systemctl daemon-reload
  systemctl enable --now omcp-quick-tunnel.service
  sleep 2
  echo "OMCP service status:"
  systemctl --no-pager --full status omcp || true
  echo "First-run Admin Key: sudo journalctl -u omcp -n 80 --no-pager"
else
  echo "systemd is not usable (state: ${SYSTEMD_STATE:-unavailable}); using background-process mode."
  if [[ -f "$DATA/agent.pid" ]] && kill -0 "$(cat "$DATA/agent.pid")" 2>/dev/null; then
    old_pid="$(cat "$DATA/agent.pid")"
    echo "Restarting existing OMCP process (PID $old_pid) to load updated files."
    kill "$old_pid" 2>/dev/null || true
    for _ in {1..20}; do kill -0 "$old_pid" 2>/dev/null || break; sleep 0.25; done
  fi
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
  echo "First-run Admin setup / startup log: sudo cat $DATA/agent.log"
  if command -v cloudflared >/dev/null 2>&1; then
    if [[ -f "$DATA/cloudflared.pid" ]] && kill -0 "$(cat "$DATA/cloudflared.pid")" 2>/dev/null; then kill "$(cat "$DATA/cloudflared.pid")" 2>/dev/null || true; fi
    runuser -u omcp -- sh -c 'nohup /usr/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8765 </dev/null >>/var/lib/omcp/cloudflared.log 2>&1 & echo $! >/var/lib/omcp/cloudflared.pid'
    sleep 3
    echo "Cloudflare Quick Tunnel log: sudo tail -n 40 $DATA/cloudflared.log"
  fi
  echo "Stop this no-systemd process: sudo kill \$(cat $DATA/agent.pid)"
fi
echo
echo "OMCP panel listener: http://127.0.0.1:8765"
echo "Panel is bound to localhost. A temporary Cloudflare Quick Tunnel is started when cloudflared is available."
echo "OpenJDK 21 was installed. Verify with: java -version"
echo "Cloud Shell sessions are temporary; processes and files may be lost when the session ends."
echo "Quick Tunnel URLs are temporary. For a permanent hostname, configure a named Cloudflare Tunnel and Cloudflare Access." 
echo "No Minecraft TCP relay is configured by this installer."
