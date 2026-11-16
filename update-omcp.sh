#!/usr/bin/env bash
set -Eeuo pipefail

REPO="https://raw.githubusercontent.com/nmronion-alt/OMCP-PANEL/main"
APP="/opt/omcp"
DATA="/var/lib/omcp"
BACKUP_ROOT="/var/backups/omcp"
WORK=""
BACKUP=""

say(){ printf '\n[OMCP UPDATE] %s\n' "$1"; }
fail(){ printf '\n[OMCP UPDATE] ERROR: %s\n' "$1" >&2; exit 1; }

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo bash update-omcp.sh"
  exit 1
fi
[[ -d "$APP" ]] || fail "OMCP application folder not found at $APP. Install OMCP first."
[[ -d "$DATA" ]] || fail "OMCP data folder not found at $DATA. Refusing to continue."
id omcp >/dev/null 2>&1 || fail "The omcp service account is missing."
command -v curl >/dev/null 2>&1 || fail "curl is required."
command -v python3 >/dev/null 2>&1 || fail "python3 is required."

WORK="$(mktemp -d /tmp/omcp-update.XXXXXX)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP="$BACKUP_ROOT/$STAMP"
mkdir -p "$BACKUP_ROOT" "$BACKUP"

cleanup(){ [[ -n "$WORK" && -d "$WORK" ]] && rm -rf "$WORK"; }
trap cleanup EXIT

say "Downloading latest OMCP files from GitHub main..."
download(){
  local path="$1" dest="$2"
  curl -fL --retry 3 --retry-all-errors --connect-timeout 15 "$REPO/$path" -o "$dest"
}
download "agent/omcp_agent.py" "$WORK/omcp_agent.py"
download "index.html" "$WORK/index.html"
mkdir -p "$WORK/admin"
for asset in index.html admin.css admin.js admin.ts; do
  download "admin/$asset" "$WORK/admin/$asset"
done

say "Validating downloaded files..."
python3 -m py_compile "$WORK/omcp_agent.py"
if command -v node >/dev/null 2>&1; then
  node --check "$WORK/admin/admin.js"
fi

say "Creating rollback backup of the current application..."
tar -czf "$BACKUP/omcp-app-before-update.tar.gz" -C /opt omcp
printf '%s\n' "$STAMP" > "$BACKUP_ROOT/latest-update"

rollback(){
  say "Update failed. Restoring the previous application files..."
  if [[ -s "$BACKUP/omcp-app-before-update.tar.gz" ]]; then
    tar -xzf "$BACKUP/omcp-app-before-update.tar.gz" -C /opt
    if command -v systemctl >/dev/null 2>&1 && systemctl cat omcp.service >/dev/null 2>&1; then
      systemctl restart omcp.service || true
    fi
  fi
}
UPDATED=0
on_error(){
  local code="$?"
  if [[ "$UPDATED" -eq 1 ]]; then rollback; fi
  echo "Update stopped with exit code $code. Backup: $BACKUP" >&2
  exit "$code"
}
trap on_error ERR

say "Installing panel files (Minecraft data is not touched)..."
install -d -o root -g omcp -m 0750 "$APP/admin"
install -o root -g omcp -m 0640 "$WORK/omcp_agent.py" "$APP/omcp_agent.py.new"
install -o root -g omcp -m 0640 "$WORK/index.html" "$APP/index.html.new"
for asset in index.html admin.css admin.js admin.ts; do
  install -o root -g omcp -m 0640 "$WORK/admin/$asset" "$APP/admin/$asset.new"
done
mv -f "$APP/omcp_agent.py.new" "$APP/omcp_agent.py"
mv -f "$APP/index.html.new" "$APP/index.html"
for asset in index.html admin.css admin.js admin.ts; do
  mv -f "$APP/admin/$asset.new" "$APP/admin/$asset"
done
chown root:omcp "$APP/omcp_agent.py" "$APP/index.html" "$APP/admin/"*
chmod 0640 "$APP/omcp_agent.py" "$APP/index.html" "$APP/admin/"*
UPDATED=1

say "Restarting OMCP agent..."
if command -v systemctl >/dev/null 2>&1 && systemctl cat omcp.service >/dev/null 2>&1; then
  systemctl restart omcp.service
else
  PIDFILE="$DATA/agent.pid"
  if [[ -f "$PIDFILE" ]]; then
    PID="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null; then
      CMD="$(tr '\0' ' ' < "/proc/$PID/cmdline" 2>/dev/null || true)"
      if [[ "$CMD" == *"/opt/omcp/omcp_agent.py"* ]]; then
        kill "$PID"
        for _ in {1..20}; do
          kill -0 "$PID" 2>/dev/null || break
          sleep 0.5
        done
      fi
    fi
    rm -f "$PIDFILE"
  fi
  runuser -u omcp -- sh -c 'nohup env OMCP_HOST=127.0.0.1 OMCP_PORT=8765 OMCP_DATA=/var/lib/omcp OMCP_WEB=/opt/omcp/index.html /usr/bin/python3 /opt/omcp/omcp_agent.py </dev/null >>/var/lib/omcp/agent.log 2>&1 & echo $! >/var/lib/omcp/agent.pid'
fi

say "Checking panel health..."
HEALTHY=0
for _ in {1..30}; do
  if curl -fsS --max-time 3 http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
    HEALTHY=1
    break
  fi
  sleep 1
done
if [[ "$HEALTHY" -ne 1 ]]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl cat omcp.service >/dev/null 2>&1; then
    systemctl --no-pager --full status omcp.service || true
    journalctl -u omcp.service -n 60 --no-pager || true
  else
    tail -n 60 "$DATA/agent.log" 2>/dev/null || true
  fi
  fail "New version did not pass the local health check. The previous app backup is at $BACKUP"
fi

trap - ERR
say "Update completed successfully."
echo "Panel health: OK"
echo "Backup: $BACKUP/omcp-app-before-update.tar.gz"
echo "Minecraft servers, worlds, plugins, backups, users and configuration in $DATA were preserved."
echo "Open your existing OMCP panel URL and refresh the browser."
