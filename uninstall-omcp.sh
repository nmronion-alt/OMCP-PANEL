#!/usr/bin/env bash
set -Eeuo pipefail

APP="/opt/omcp"
DATA="/var/lib/omcp"
PURGE_DATA="${OMCP_PURGE_DATA:-0}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash uninstall-omcp.sh"
  exit 1
fi

echo "This will stop OMCP and remove its application files and service definitions."
if [[ "$PURGE_DATA" == "1" ]]; then
  echo "WARNING: OMCP server files, worlds, backups, users and configuration in $DATA will ALSO be permanently deleted."
else
  echo "Minecraft server files, worlds, backups, users and configuration in $DATA will be PRESERVED."
  echo "To remove those too, explicitly run: sudo OMCP_PURGE_DATA=1 bash uninstall-omcp.sh"
fi
read -r -p "Type REMOVE-OMCP to continue: " confirm
if [[ "$confirm" != "REMOVE-OMCP" ]]; then
  echo "Cancelled. Nothing was removed."
  exit 0
fi

# Stop managed services where systemd is available.
if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now omcp-tunnel.service 2>/dev/null || true
  systemctl disable --now omcp.service 2>/dev/null || true
fi

# Stop only processes recorded by this installation, after checking their command line.
stop_recorded_process() {
  local pidfile="$1" expected="$2" pid cmd
  [[ -f "$pidfile" ]] || return 0
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || { rm -f "$pidfile"; return 0; }
  if kill -0 "$pid" 2>/dev/null; then
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$cmd" == *"$expected"* ]]; then
      kill "$pid" 2>/dev/null || true
      for _ in {1..20}; do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
      if kill -0 "$pid" 2>/dev/null; then kill -TERM "$pid" 2>/dev/null || true; fi
    else
      echo "Skipping PID $pid: command does not match expected OMCP process."
    fi
  fi
  rm -f "$pidfile"
}
stop_recorded_process "$DATA/tunnel.pid" "/opt/omcp/run-tunnel.sh"
stop_recorded_process "$DATA/agent.pid" "/opt/omcp/omcp_agent.py"

# Remove only OMCP's own service definitions and app directory.
rm -f /etc/systemd/system/omcp.service /etc/systemd/system/omcp-tunnel.service
if command -v systemctl >/dev/null 2>&1; then systemctl daemon-reload 2>/dev/null || true; systemctl reset-failed omcp.service omcp-tunnel.service 2>/dev/null || true; fi
rm -rf "$APP"
rm -f /usr/local/bin/omcp-url

if [[ "$PURGE_DATA" == "1" ]]; then
  rm -rf "$DATA"
  if id omcp >/dev/null 2>&1; then userdel omcp 2>/dev/null || true; fi
  if getent group omcp >/dev/null 2>&1; then groupdel omcp 2>/dev/null || true; fi
  echo "OMCP application and data have been removed."
else
  echo "OMCP application has been removed. Data is preserved at $DATA."
  echo "The omcp system account is retained so preserved files keep their ownership."
fi

echo "Uninstall complete. Shared packages (Python, Java, OpenSSH and system libraries) were intentionally left installed."
