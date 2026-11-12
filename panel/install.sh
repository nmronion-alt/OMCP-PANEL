#!/usr/bin/env bash
set -Eeuo pipefail

OMCP_REPO="https://github.com/nmronion-alt/onion-hub.git"
OMCP_BRANCH="minecraft-panel-foundation"
OMCP_HOME="/opt/omcp"
OMCP_PANEL_DIR="$OMCP_HOME/panel"

if [[ "\${EUID}" -ne 0 ]]; then
  echo "Run as root: curl -fsSL https://raw.githubusercontent.com/nmronion-alt/onion-hub/\${OMCP_BRANCH}/panel/install.sh | sudo bash"
  exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
  echo "OMCP installer currently supports Ubuntu/Debian hosts with apt-get."
  exit 1
fi

echo "=============================================="
echo "       OMCP - Onion Minecraft Panel"
echo "       Installation and host checks"
echo "=============================================="

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git openssl

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker Engine and Compose plugin..."
  apt-get install -y docker.io docker-compose-v2
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is missing. Install docker-compose-v2 and retry."
  exit 1
fi

systemctl enable --now docker
docker info >/dev/null

mkdir -p "$OMCP_HOME"
if [[ -d "$OMCP_HOME/.git" ]]; then
  git -C "$OMCP_HOME" fetch origin "$OMCP_BRANCH"
  git -C "$OMCP_HOME" checkout "$OMCP_BRANCH"
  git -C "$OMCP_HOME" reset --hard "origin/$OMCP_BRANCH"
else
  git clone --depth 1 --branch "$OMCP_BRANCH" "$OMCP_REPO" "$OMCP_HOME"
fi

if [[ ! -f "$OMCP_PANEL_DIR/docker-compose.yml" || ! -f "$OMCP_PANEL_DIR/backend/main.py" ]]; then
  echo "The downloaded OMCP panel files are incomplete."
  exit 1
fi

DOCKER_FS="$(findmnt -n -o FSTYPE -T /var/lib/docker 2>/dev/null || true)"
case "$DOCKER_FS" in
  overlay|tmpfs|ramfs)
    echo "WARNING: Docker storage appears to use $DOCKER_FS."
    echo "This can be temporary. Your Minecraft worlds may disappear when this environment resets."
    if [[ -t 0 ]]; then
      read -r -p "Continue anyway? [y/N] " answer
      [[ "$answer" =~ ^[Yy]$ ]] || exit 1
    else
      echo "Non-interactive install stopped to protect your server data."
      exit 1
    fi
    ;;
esac

if [[ ! -f "$OMCP_PANEL_DIR/.env" ]]; then
  TOKEN="$(openssl rand -hex 32)"
  umask 077
  {
    printf 'ADMIN_TOKEN=%s\n' "$TOKEN"
    printf 'PANEL_PORT=8787\n'
  } > "$OMCP_PANEL_DIR/.env"
else
  TOKEN="$(sed -n 's/^ADMIN_TOKEN=//p' "$OMCP_PANEL_DIR/.env" | head -n1)"
  if [[ "\${#TOKEN}" -lt 32 ]]; then
    echo "Existing .env has an invalid ADMIN_TOKEN. Back it up and remove it, then rerun."
    exit 1
  fi
fi

chmod 600 "$OMCP_PANEL_DIR/.env"
cd "$OMCP_PANEL_DIR"
docker compose up -d --build

for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8787/api/health >/dev/null; then break; fi
  sleep 2
done
if ! curl -fsS http://127.0.0.1:8787/api/health >/dev/null; then
  echo "Panel did not become healthy. Check logs with: cd $OMCP_PANEL_DIR && docker compose logs --tail=100"
  exit 1
fi

echo
echo "=============================================="
echo "          OMCP INSTALLATION READY"
echo "=============================================="
echo "Local panel URL : http://127.0.0.1:8787"
echo "Admin token     : $TOKEN"
echo "Install folder  : $OMCP_PANEL_DIR"
echo
echo "IMPORTANT:"
echo "1. Save the admin token privately."
echo "2. For a public web link, create a Cloudflare Tunnel and route its hostname to http://127.0.0.1:8787."
echo "3. Minecraft Java traffic uses a separate TCP relay. The panel web tunnel does not forward Minecraft TCP."
echo "4. Minecraft servers use persistent Docker volumes under Docker's data directory."
echo "5. Keep this VPS/environment running; ephemeral environments may reset or stop."
echo
echo "Panel logs: cd $OMCP_PANEL_DIR && docker compose logs -f"
