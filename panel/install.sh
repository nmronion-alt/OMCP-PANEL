#!/usr/bin/env bash
set -Eeuo pipefail

OMCP_REPO="https://github.com/nmronion-alt/onion-hub.git"
OMCP_BRANCH="minecraft-panel-foundation"
OMCP_HOME="/opt/omcp"
OMCP_PANEL_DIR="$OMCP_HOME/panel"
OMCP_DATA_DIR="$OMCP_HOME/data"
PANEL_PORT="8787"

if [[ "\${EUID}" -ne 0 ]]; then
  echo "Run as root: curl -fsSL https://raw.githubusercontent.com/nmronion-alt/onion-hub/\${OMCP_BRANCH}/panel/install.sh | sudo bash"
  exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
  echo "OMCP installer supports Ubuntu/Debian hosts with apt-get."
  exit 1
fi

echo "=============================================="
echo "       OMCP - Onion Minecraft Panel"
echo "       Native Java server mode"
echo "=============================================="

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git openssl python3 python3-venv python3-pip openjdk-21-jre-headless

command -v java >/dev/null 2>&1 || { echo "Java runtime installation failed."; exit 1; }
mkdir -p "$OMCP_HOME"
if [[ -d "$OMCP_HOME/.git" ]]; then
  git -C "$OMCP_HOME" fetch origin "$OMCP_BRANCH"
  git -C "$OMCP_HOME" checkout "$OMCP_BRANCH"
  git -C "$OMCP_HOME" reset --hard "origin/$OMCP_BRANCH"
else
  git clone --depth 1 --branch "$OMCP_BRANCH" "$OMCP_REPO" "$OMCP_HOME"
fi
[[ -f "$OMCP_PANEL_DIR/backend/main.py" && -f "$OMCP_PANEL_DIR/frontend/index.html" ]] || { echo "OMCP files are incomplete."; exit 1; }

mkdir -p "$OMCP_DATA_DIR/servers"
chmod 750 "$OMCP_HOME" "$OMCP_DATA_DIR" "$OMCP_DATA_DIR/servers"
python3 -m venv "$OMCP_HOME/venv"
"$OMCP_HOME/venv/bin/pip" install --upgrade pip
"$OMCP_HOME/venv/bin/pip" install -r "$OMCP_PANEL_DIR/requirements.txt"

if [[ ! -f "$OMCP_PANEL_DIR/.env" ]]; then
  TOKEN="$(openssl rand -hex 32)"
  umask 077
  printf 'ADMIN_TOKEN=%s\nPANEL_PORT=%s\nOMCP_DATA_DIR=%s\n' "$TOKEN" "$PANEL_PORT" "$OMCP_DATA_DIR" > "$OMCP_PANEL_DIR/.env"
else
  TOKEN="$(sed -n 's/^ADMIN_TOKEN=//p' "$OMCP_PANEL_DIR/.env" | head -n1)"
  [[ "\${#TOKEN}" -ge 32 ]] || { echo "Existing admin token is invalid. Back up and remove $OMCP_PANEL_DIR/.env, then retry."; exit 1; }
  grep -q '^OMCP_DATA_DIR=' "$OMCP_PANEL_DIR/.env" || printf 'OMCP_DATA_DIR=%s\n' "$OMCP_DATA_DIR" >> "$OMCP_PANEL_DIR/.env"
fi
chmod 600 "$OMCP_PANEL_DIR/.env"

if [[ -f "$OMCP_HOME/panel.pid" ]]; then
  OLD_PID="$(cat "$OMCP_HOME/panel.pid" 2>/dev/null || true)"
  if [[ "$OLD_PID" =~ ^[0-9]+$ ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" || true
    sleep 1
  fi
fi

set -a
source "$OMCP_PANEL_DIR/.env"
set +a
cd "$OMCP_PANEL_DIR"
nohup env ADMIN_TOKEN="$ADMIN_TOKEN" OMCP_DATA_DIR="$OMCP_DATA_DIR" "$OMCP_HOME/venv/bin/uvicorn" backend.main:app --host 127.0.0.1 --port "$PANEL_PORT" --workers 1 > "$OMCP_HOME/panel.log" 2>&1 < /dev/null &
echo $! > "$OMCP_HOME/panel.pid"

for attempt in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PANEL_PORT/api/health" >/dev/null; then break; fi
  sleep 2
done
if ! curl -fsS "http://127.0.0.1:$PANEL_PORT/api/health" >/dev/null; then
  echo "Panel failed to start. Logs: $OMCP_HOME/panel.log"
  tail -n 60 "$OMCP_HOME/panel.log" || true
  exit 1
fi

echo
echo "=============================================="
echo "          OMCP INSTALLATION READY"
echo "=============================================="
echo "Local panel URL : http://127.0.0.1:$PANEL_PORT"
echo "Admin token     : $TOKEN"
echo "Install folder  : $OMCP_HOME"
echo "Server data     : $OMCP_DATA_DIR/servers"
echo "Panel log       : $OMCP_HOME/panel.log"
echo
echo "Cloudflare Tunnel: route your panel hostname to http://127.0.0.1:$PANEL_PORT"
echo "Minecraft TCP   : use a separate TCP relay to the server's local target."
echo "No Docker or systemd is required by this installer."
echo "WARNING: the VPS must permit background processes and persistent disk."
echo "For Cloud Shell/temporary containers, uptime and saved worlds may be lost on reset."
