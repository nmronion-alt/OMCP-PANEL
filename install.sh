#!/usr/bin/env bash
# ONION HUB foundation bootstrap — diagnostics only; no destructive actions.
set -Eeuo pipefail
VERSION="0.1.0-foundation"
BRAND="ONION HUB"
line(){ printf '%s\n' '============================================================'; }
have(){ command -v "$1" >/dev/null 2>&1; }
detect_cloud_shell(){
  [[ -n "${CLOUD_SHELL:-}" || -n "${GOOGLE_CLOUD_PROJECT:-}" ||
     -n "${DEVSHELL_PROJECT_ID:-}" || -d /google/devshell ]]
}
smart_check(){
  line; printf '             %s — SMART CHECK\n' "$BRAND"; line
  if [[ -r /etc/os-release ]]; then . /etc/os-release; printf 'OS: %s (%s %s)\n' "${PRETTY_NAME:-Unknown}" "${ID:-?}" "${VERSION_ID:-?}"; else echo 'OS: Unknown'; fi
  printf 'Kernel: %s\nArchitecture: %s\n' "$(uname -r)" "$(uname -m)"
  printf 'Virtualization: %s\nUser: %s (UID %s)\n' "$(systemd-detect-virt 2>/dev/null || echo unknown)" "$(id -un)" "$EUID"
  line; echo 'RESOURCES'
  have nproc && printf 'CPU threads: %s\n' "$(nproc)"
  [[ -r /proc/meminfo ]] && awk '/MemTotal:/ {printf "RAM: %.2f GiB\n",$2/1048576}' /proc/meminfo
  have df && df -hP / | awk 'NR<=2'
  line; echo 'ENVIRONMENT'
  if detect_cloud_shell; then echo '[WARN] Google Cloud Shell detected; temporary environment, not persistent VPS hosting.'; else echo '[INFO] Cloud Shell marker not detected (suitability is not proven).'; fi
  if have systemctl && systemctl is-system-running >/dev/null 2>&1; then echo '[PASS] systemd running'; elif have systemctl; then echo '[WARN] systemd present but not fully running'; else echo '[FAIL] systemctl unavailable'; fi
  if have docker && docker info >/dev/null 2>&1; then echo '[PASS] Docker daemon responds'; elif have docker; then echo '[WARN] Docker CLI exists but daemon unavailable/permission denied'; else echo '[INFO] Docker not installed (not installed by this check)'; fi
  line; echo 'NETWORK'
  if have ip; then ip -brief address 2>/dev/null || true; ip route show default 2>/dev/null || true; else echo '[WARN] ip command unavailable'; fi
  if have curl; then printf 'Outbound IPv4: '; curl -4fsS --connect-timeout 4 --max-time 8 https://api.ipify.org 2>/dev/null || printf 'unavailable'; printf '\n'; else echo '[WARN] curl unavailable'; fi
  echo '[NOTE] Outbound public IP does not prove inbound reachability.'
  echo '[NOTE] Inbound ports require an independent external test.'
  line; echo 'COMPATIBILITY'
  local ok=0
  if [[ -r /etc/os-release ]]; then . /etc/os-release; case "${ID:-}:${VERSION_ID:-}" in ubuntu:24.04|debian:12|debian:13) ok=1;; esac; fi
  ((ok)) && echo '[PASS] OS is in diagnostic target list.' || echo '[WARN] OS is outside diagnostic target list.'
  echo '[INFO] Foundation release only: no packages, firewall rules, services, or user data changed.'
  line
}
install_hub(){
  line; echo 'ONION HUB — INSTALL'
  echo '[STOP] Production installation is not enabled in this foundation release.'
  echo 'Panel, database, Wings, relay provisioning, node registration and Green Heart verification are not implemented yet.'
  echo 'No system changes were made.'
  line
}
while true; do
  clear 2>/dev/null || true
  line; printf '                 %s\n                 Version %s\n' "$BRAND" "$VERSION"; line
  echo '  [1] SMART CHECK'
  echo '  [2] INSTALL ONION HUB (not enabled yet)'
  echo '  [3] EXIT'
  line
  read -r -p 'Select option: ' choice || exit 0
  case "$choice" in
    1) smart_check; read -r -p 'Press Enter to continue...' _ ;;
    2) install_hub; read -r -p 'Press Enter to continue...' _ ;;
    3) exit 0 ;;
    *) echo 'Invalid option.'; sleep 1 ;;
  esac
done
