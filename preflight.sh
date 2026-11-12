#!/usr/bin/env bash
# ONION HUB preflight: read-only checks; does not install packages or change services.
set -Eeuo pipefail

GREEN=$'\033[1;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[1;31m'; CYAN=$'\033[1;36m'; RESET=$'\033[0m'
PASS=0; WARN=0; BLOCK=0
pass(){ printf ' %b[PASS]%b %s\n' "$GREEN" "$RESET" "$*"; PASS=$((PASS+1)); }
warn(){ printf ' %b[WARN]%b %s\n' "$YELLOW" "$RESET" "$*"; WARN=$((WARN+1)); }
block(){ printf ' %b[BLOCK]%b %s\n' "$RED" "$RESET" "$*"; BLOCK=$((BLOCK+1)); }
section(){ printf '\n%b%s%b\n' "$CYAN" "$*" "$RESET"; }

os_id=unknown; os_version=unknown; os_name=unknown
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  os_id="${ID:-unknown}"; os_version="${VERSION_ID:-unknown}"; os_name="${PRETTY_NAME:-unknown}"
fi
ram_kb="$(awk '/MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
ram_gib="$(awk -v k="${ram_kb:-0}" 'BEGIN{printf "%.1f",k/1048576}')"
cpu_count="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0)"
disk_kb="$(df -Pk / 2>/dev/null | awk 'NR==2 {print $4}')"
disk_gib="$(awk -v k="${disk_kb:-0}" 'BEGIN{printf "%.1f",k/1048576}')"
pid1="$(ps -p 1 -o comm= 2>/dev/null | xargs || true)"
virt="$(systemd-detect-virt 2>/dev/null || true)"
[[ -n "$virt" ]] || virt=unknown
cgroup="$(cat /proc/1/cgroup 2>/dev/null || true)"
in_container=false
if grep -Eqi 'docker|containerd|kubepods|lxc|podman' <<<"$cgroup" || [[ -f /.dockerenv ]] || [[ -f /run/.containerenv ]]; then in_container=true; fi

printf '%b\n' '=============================================='
printf '%b\n' '             ONION HUB PREFLIGHT'
printf '%b\n' '=============================================='
printf 'OS: %s (%s %s)\nCPU: %s logical cores\nRAM: %s GiB\nFree disk on /: %s GiB\nPID 1: %s\nVirtualization: %s\nContainer detected: %s\n' "$os_name" "$os_id" "$os_version" "$cpu_count" "$ram_gib" "$disk_gib" "${pid1:-unknown}" "$virt" "$in_container"

section "1. Operating system"
if [[ "$os_id" == ubuntu || "$os_id" == debian ]]; then pass "Ubuntu/Debian family detected"; else block "This first release targets Ubuntu/Debian only"; fi
if [[ "$(id -u)" -eq 0 ]]; then pass "Running as root"; else block "Run as root for a future Panel/Wings installation"; fi
if [[ "$(uname -m)" == x86_64 || "$(uname -m)" == aarch64 ]]; then pass "Supported CPU architecture: $(uname -m)"; else block "Unsupported architecture: $(uname -m)"; fi

section "2. Resources"
if (( cpu_count >= 2 )); then pass "CPU: $cpu_count cores"; else block "At least 2 CPU cores are recommended"; fi
if awk -v r="$ram_gib" 'BEGIN{exit !(r>=4)}'; then pass "RAM: $ram_gib GiB"; else block "At least 4 GiB RAM is required for the initial Panel + Wings target"; fi
if awk -v d="$disk_gib" 'BEGIN{exit !(d>=20)}'; then pass "Free disk: $disk_gib GiB"; else block "Only $disk_gib GiB free; keep at least 20 GiB free before installing Panel, database, Docker images and game data"; fi

section "3. Service manager and containers"
if [[ "$pid1" == systemd ]]; then pass "systemd is PID 1"; else block "systemd is not PID 1 (found: ${pid1:-unknown}); standard Wings service installation is unsupported here"; fi
if [[ "$in_container" == true ]]; then warn "Container/Kubernetes environment detected; nested Docker, privileged operations and persistence must be verified"; else pass "No common container marker detected"; fi
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then pass "Docker daemon is reachable"; else block "Docker CLI exists, but the Docker daemon is unavailable or permission is denied"; fi
else block "Docker is not installed"; fi

section "4. Networking"
if command -v curl >/dev/null 2>&1; then
  public4="$(curl -4fsS --connect-timeout 3 --max-time 6 https://api.ipify.org 2>/dev/null || true)"
  if [[ -n "$public4" ]]; then pass "Outbound IPv4 works: $public4"; else warn "Could not discover outbound IPv4"; fi
else warn "curl unavailable; outbound IP check skipped"; fi
if command -v ip >/dev/null 2>&1; then
  printf 'Interfaces:\n'; ip -brief address 2>/dev/null || true
  printf 'Default route:\n'; ip route show default 2>/dev/null || true
fi
warn "Outbound public-IP detection does NOT prove inbound TCP reachability. Direct mode needs an external port test."
warn "Private mode still needs a real relay for Wings API, SFTP and Minecraft game traffic; Cloudflare Pages is not a TCP relay."

section "Result"
printf 'PASS: %d  WARN: %d  BLOCK: %d\n' "$PASS" "$WARN" "$BLOCK"
if (( BLOCK > 0 )); then
  printf '%bNOT READY%b — do not run the production Panel/Wings installer on this host yet.\n' "$RED" "$RESET"
  exit 2
elif (( WARN > 0 )); then
  printf '%bCONDITIONAL%b — investigate warnings before deployment.\n' "$YELLOW" "$RESET"
  exit 1
else
  printf '%bPREFLIGHT PASSED%b — this is not yet proof of inbound networking or a successful deployment.\n' "$GREEN" "$RESET"
fi
