#!/usr/bin/env bash
# ONION HUB — Panel & Wings Toolkit
# Safe interactive preview. Panel themes are detection-only; no theme is installed.
set -Eeuo pipefail

VERSION="0.3.0-panel-themes-preview"
BRAND="ONION HUB"
RESET=$'\033[0m'
PURPLE=$'\033[1;38;5;141m'
LAVENDER=$'\033[1;38;5;183m'
CYAN=$'\033[1;38;5;117m'
GREEN=$'\033[1;38;5;82m'
YELLOW=$'\033[1;38;5;220m'
RED=$'\033[1;38;5;203m'
GRAY=$'\033[0;38;5;244m'
WHITE=$'\033[1;38;5;255m'

have(){ command -v "$1" >/dev/null 2>&1; }
pause(){ printf '\n%b' "${GRAY}Press Enter to return to menu...${RESET}"; read -r _ || true; }
rule(){ printf '%b\n' "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; }
ok(){ printf ' %b %s\n' "${GREEN}✓${RESET}" "$*"; }
warn(){ printf ' %b %s\n' "${YELLOW}! ${RESET}" "$*"; }
fail(){ printf ' %b %s\n' "${RED}✗${RESET}" "$*"; }

get_os(){
  if [[ -r /etc/os-release ]]; then . /etc/os-release; printf '%s' "${PRETTY_NAME:-Unknown Linux}"; else printf 'Unknown'; fi
}
get_ram(){
  if [[ -r /proc/meminfo ]]; then awk '/MemTotal:/ {printf "%.1f GiB",$2/1048576}' /proc/meminfo; else printf 'Unknown'; fi
}
get_cpu(){
  if have nproc; then nproc; else printf 'Unknown'; fi
}
get_disk(){
  df -hP / 2>/dev/null | awk 'NR==2 {printf "%s used / %s total (%s)",$3,$2,$5}'
}
get_public_ip(){
  if have curl; then curl -4fsS --connect-timeout 3 --max-time 6 https://api.ipify.org 2>/dev/null || true; fi
}
is_cloud_shell(){
  [[ -n "${CLOUD_SHELL:-}" || -n "${GOOGLE_CLOUD_PROJECT:-}" || -n "${DEVSHELL_PROJECT_ID:-}" || -d /google/devshell ]]
}
header(){
  clear 2>/dev/null || true
  printf '%b' "$PURPLE"
  cat <<'ART'
 ██████╗ ███╗   ██╗██╗ ██████╗ ███╗   ██╗
██╔═══██╗████╗  ██║██║██╔═══██╗████╗  ██║
██║   ██║██╔██╗ ██║██║██║   ██║██╔██╗ ██║
██║   ██║██║╚██╗██║██║██║   ██║██║╚██╗██║
╚██████╔╝██║ ╚████║██║╚██████╔╝██║ ╚████║
 ╚═════╝ ╚═╝  ╚═══╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝
ART
  printf '%b' "$RESET"
  printf ' %bPANEL & WINGS TOOLKIT%b  %b|%b  v%s  %b|%b  %s\n' "$LAVENDER" "$RESET" "$GRAY" "$RESET" "$VERSION" "$GRAY" "$RESET" "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo '')"
  rule
}
system_status(){
  local load ram disk ip
  load="$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo '?')"
  ram="$(get_ram)"; disk="$(get_disk)"; ip="$(get_public_ip)"
  printf ' %b◉ SYSTEM STATUS%b\n' "$CYAN" "$RESET"
  printf '   Host: %s  |  OS: %s\n' "$(hostname 2>/dev/null || echo unknown)" "$(get_os)"
  printf '   CPU threads: %s  |  RAM: %s  |  Load: %s\n' "$(get_cpu)" "$ram" "$load"
  printf '   Disk: %s\n' "${disk:-Unknown}"
  if [[ -n "$ip" ]]; then printf '   Outbound IPv4: %s\n' "$ip"; else warn 'Outbound IPv4 lookup unavailable'; fi
  if is_cloud_shell; then warn 'Cloud Shell detected: temporary session; not a persistent VPS.'; fi
}
smart_check(){
  header; printf ' %bSMART CHECK%b\n' "$LAVENDER" "$RESET"; rule
  printf ' OS: %s\n Kernel: %s\n Architecture: %s\n' "$(get_os)" "$(uname -r)" "$(uname -m)"
  printf ' Virtualization: %s\n' "$(systemd-detect-virt 2>/dev/null || echo unknown)"
  printf ' CPU threads: %s\n RAM: %s\n Disk: %s\n' "$(get_cpu)" "$(get_ram)" "$(get_disk)"
  if is_cloud_shell; then warn 'Cloud Shell environment detected; persistence and inbound networking are limited.'; else ok 'No common Cloud Shell marker detected (this is not proof of public reachability).'; fi
  if have systemctl; then
    if systemctl is-system-running >/dev/null 2>&1; then ok 'systemd is running'; else warn 'systemctl exists but systemd is not fully running'; fi
  else fail 'systemctl unavailable'; fi
  if have docker; then
    if docker info >/dev/null 2>&1; then ok 'Docker daemon responds'; else warn 'Docker CLI found; daemon unavailable or permission denied'; fi
  else warn 'Docker is not installed'; fi
  if have ip; then
    printf '\n%bNETWORK INTERFACES%b\n' "$CYAN" "$RESET"
    ip -brief address 2>/dev/null || true
    printf '\n%bDEFAULT ROUTE%b\n' "$CYAN" "$RESET"
    ip route show default 2>/dev/null || true
  fi
  printf '\n%bIMPORTANT%b Public outbound IP does not prove inbound port access. Test from an independent network.\n' "$YELLOW" "$RESET"
  rule; pause
}
show_tools(){
  header; printf ' %bVPS TOOLBOX%b\n' "$LAVENDER" "$RESET"; rule
  echo ' [1] Show system uptime'
  echo ' [2] Show memory details'
  echo ' [3] Show disk usage'
  echo ' [4] Show listening TCP ports'
  echo ' [5] Show Docker containers'
  echo ' [0] Back'
  rule
  read -r -p 'Select tool: ' t || return
  case "$t" in
    1) uptime 2>/dev/null || warn 'uptime command unavailable' ;;
    2) free -h 2>/dev/null || cat /proc/meminfo | head -n 8 ;;
    3) df -hT 2>/dev/null ;;
    4) if have ss; then ss -lnt 2>/dev/null; else warn 'ss command unavailable'; fi ;;
    5) if have docker && docker info >/dev/null 2>&1; then docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'; else warn 'Docker daemon unavailable'; fi ;;
    0) return ;;
    *) warn 'Invalid option' ;;
  esac
  pause
}
panel_themes(){
  header; printf ' %bPANEL THEMES & BLUEPRINT%b\n' "$LAVENDER" "$RESET"; rule
  local panel_dir=""
  for candidate in "${PTERODACTYL_DIRECTORY:-}" /var/www/pterodactyl /var/www/panel; do
    if [[ -n "$candidate" && -f "$candidate/artisan" ]]; then panel_dir="$candidate"; break; fi
  done

  if [[ -n "$panel_dir" ]]; then
    ok "Pterodactyl Panel detected: $panel_dir"
  else
    warn 'Pterodactyl Panel directory not detected in the common locations.'
  fi

  if have blueprint; then
    ok "Blueprint CLI detected: $(command -v blueprint)"
  else
    warn 'Blueprint CLI not detected.'
  fi

  echo
  echo ' This menu is for the WEBSITE PANEL appearance, not terminal colors.'
  echo ' Theme installation is not enabled in this preview release.'
  echo ' No theme files were downloaded, changed, or removed.'
  echo
  echo ' Next: verify Panel version + Blueprint compatibility, show available'
  echo ' themes, back up the Panel, then install only after confirmation.'
  rule; pause
}
service_status(){
  header; printf ' %bPANEL & WINGS STATUS%b\n' "$LAVENDER" "$RESET"; rule
  if have systemctl; then
    for svc in nginx mariadb mysql redis-server wings; do
      if systemctl list-unit-files "${svc}.service" --no-legend 2>/dev/null | grep -q "${svc}.service"; then
        printf ' %-16s %s\n' "$svc" "$(systemctl is-active "$svc" 2>/dev/null || true)"
      else
        printf ' %-16s %bnot detected%b\n' "$svc" "$GRAY" "$RESET"
      fi
    done
  else warn 'systemd unavailable; service status cannot be queried'; fi
  echo
  warn 'This is detection only. It does not install, configure, or repair Panel/Wings.'
  pause
}
routing_status(){
  header; printf ' %bROUTING DIAGNOSTICS%b\n' "$LAVENDER" "$RESET"; rule
  local ip
  ip="$(get_public_ip)"
  printf ' Outbound public IPv4: %s\n' "${ip:-unavailable}"
  if have cloudflared; then ok 'cloudflared binary detected'; else warn 'cloudflared not detected'; fi
  warn 'Cloudflare Pages is only hosting for this installer, not a TCP relay.'
  warn 'Cloudflare Tunnel can publish supported HTTP services; Wings/SFTP/game TCP need compatible routing.'
  warn 'Minekube Connect is a Minecraft route only; it does not route Panel or Wings.'
  echo
  echo ' No tunnel credentials are requested or stored by this diagnostic module.'
  pause
}
install_notice(){
  header; printf ' %bINSTALLATION%b\n' "$LAVENDER" "$RESET"; rule
  warn 'Production deployment is not enabled in this build.'
  echo ' Target: Panel + database + Wings + automatic node registration + heartbeat checks.'
  echo ' Direct mode requires verified inbound access; private mode needs a real TCP relay.'
  echo ' Minekube is for Minecraft traffic only; it does not route Wings API or SFTP.'
  echo ' This build does not yet deploy these components.'
  echo
  echo 'No packages installed. No firewall changes. No existing data modified.'
  pause
}
main_menu(){
  while true; do
    header
    system_status
    rule
    printf ' %bDEPLOYMENT & SERVICES%b\n' "$CYAN" "$RESET"
    printf '  [1] Smart Check          [5] Panel Themes\n'
    printf '  [2] Install ONION HUB    [6] System Tools\n'
    printf '  [3] Panel & Wings Status [7] Container Tools\n'
    printf '  [4] Routing Diagnostics [8] New Modules (coming soon)\n'
    printf '\n %bMAINTENANCE & TOOLS%b\n' "$CYAN" "$RESET"
    printf '  [9] VPS Toolbox          [0] Exit\n'
    rule
    read -r -p ' ➜ Enter Option (0-9): ' choice || exit 0
    case "$choice" in
      1) smart_check ;;
      2) install_notice ;;
      3) service_status ;;
      4) routing_status ;;
      5) panel_themes ;;
      6|7|9) show_tools ;;
      8) header; warn 'Additional modules are planned; none are falsely marked as installed.'; pause ;;
      0) printf '%bONION HUB closed.%b\n' "$PURPLE" "$RESET"; exit 0 ;;
      *) warn 'Invalid option'; sleep 1 ;;
    esac
  done
}

main_menu
