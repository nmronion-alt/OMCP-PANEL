#!/usr/bin/env bash
set -Eeuo pipefail
# OMCP installer for Ubuntu/Debian. Supports systemd VPS and no-systemd shells.
REPO="https://raw.githubusercontent.com/nmronion-alt/onion-hub/main"
APP="/opt/omcp"
DATA="/var/lib/omcp"
if [[ "${EUID}" -ne 0 ]]; then echo "Run with sudo/root: sudo bash install-omcp.sh"; exit 1; fi
if ! command -v apt-get >/dev/null; then echo "Supported target: Ubuntu/Debian."; exit 1; fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-paramiko git curl ca-certificates openjdk-21-jre-headless openssh-client
# Install Java 25 when the configured Ubuntu/Debian repositories provide it; Java 21 remains the baseline.
if apt-cache show openjdk-25-jre-headless >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y openjdk-25-jre-headless
fi
# Open the dedicated SFTP listener in UFW when UFW is already active. Cloud firewalls need a separate rule.
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow 2022/tcp || true; fi

# tunnl.gg uses the system OpenSSH client and does not require a Cloudflare account.
id omcp >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --create-home --shell /usr/sbin/nologin omcp
install -d -o root -g omcp -m 0750 "$APP"
install -d -o omcp -g omcp -m 0750 "$DATA" "$DATA/servers" "$DATA/backups"
curl -fsSL "$REPO/agent/omcp_agent.py" -o "$APP/omcp_agent.py"
curl -fsSL "$REPO/index.html" -o "$APP/index.html"
# Validate the complete agent source before stopping/restarting the existing process.
python3 -m py_compile "$APP/omcp_agent.py"
chown root:omcp "$APP/omcp_agent.py" "$APP/index.html"
chmod 0640 "$APP/omcp_agent.py" "$APP/index.html"

# Keep one SSH identity so tunnl.gg can return the same free stable URL after reconnects.
install -d -o omcp -g omcp -m 0700 "$DATA/.ssh"
if [[ ! -s "$DATA/.ssh/id_ed25519" ]]; then
  runuser -u omcp -- ssh-keygen -q -t ed25519 -N "" -f "$DATA/.ssh/id_ed25519"
fi
cat >"$APP/run-tunnel.sh" <<'TUNNEL'
#!/usr/bin/env bash
set +e
while true; do
  /usr/bin/ssh -i /var/lib/omcp/.ssh/id_ed25519 \
    -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes -t -R 80:localhost:8765 \
    stable@proxy.tunnl.gg 2>&1 | /usr/bin/tee -a /var/lib/omcp/tunnl.log
  sleep 5
done
TUNNEL
chmod 0750 "$APP/run-tunnel.sh"
chown root:omcp "$APP/run-tunnel.sh"

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
  cat >/etc/systemd/system/omcp-tunnel.service <<'TUNNEL'
[Unit]
Description=OMCP stable HTTPS tunnel via tunnl.gg
After=network-online.target omcp.service
Wants=network-online.target
[Service]
Type=simple
User=omcp
Group=omcp
ExecStart=/opt/omcp/run-tunnel.sh
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/omcp
UMask=0027
[Install]
WantedBy=multi-user.target
TUNNEL
  systemctl daemon-reload
  systemctl enable --now omcp-tunnel.service
  sleep 2
  echo "OMCP service status:"
  systemctl --no-pager --full status omcp || true
  echo "First-run Admin setup: sudo journalctl -u omcp -n 80 --no-pager"
  echo "Tunnel URL/log: sudo tail -n 40 /var/lib/omcp/tunnl.log"
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
  if [[ -f "$DATA/tunnel.pid" ]] && kill -0 "$(cat "$DATA/tunnel.pid")" 2>/dev/null; then
    kill "$(cat "$DATA/tunnel.pid")" 2>/dev/null || true
  fi
  runuser -u omcp -- sh -c 'nohup /opt/omcp/run-tunnel.sh </dev/null >/dev/null 2>&1 & echo $! >/var/lib/omcp/tunnel.pid'
  sleep 3
  echo "tunnl.gg URL/log: sudo tail -n 40 $DATA/tunnl.log"
  echo "Stop this no-systemd tunnel: sudo kill \$(cat $DATA/tunnel.pid)"
  echo "Stop this no-systemd panel: sudo kill \$(cat $DATA/agent.pid)"
fi
echo
echo "OMCP panel listener: http://127.0.0.1:8765"
echo "Panel is bound to localhost. tunnl.gg HTTPS tunnel reconnects automatically using a persistent SSH identity."
echo "OpenJDK 21 was installed. Verify with: java -version"
echo "Cloud Shell sessions are temporary; processes and files may be lost when the session ends."
echo "Free tunnl.gg links have a 2-hour idle timeout and a 24-hour maximum session; automatic reconnect reuses the same SSH-key URL." 
echo "This tunnel is for the panel's HTTPS URL only; Minecraft servers still need a separate TCP relay."
