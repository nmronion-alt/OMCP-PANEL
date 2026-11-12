#!/usr/bin/env bash
# ONION HUB preflight — read-only checks. No packages, services, firewall or game data changed.
set -Eeuo pipefail

GREEN=$'\\033[1;32m'; YELLOW=$'\\033[1;33m'; RED=$'\\033[1;31m'; CYAN=$'\\033[1;36m'; RESET=$'\\033[0m'
PASS=0; WARN=0; BLOCK=0
pass(){ printf ' %b[PASS]%b %s\\n' "$GREEN" "$RESET" "$*"; PASS=$((PASS+1)); }
warn(){ printf ' %b[WARN]%b %s\\n' "$YELLOW" "$RESET" "$*"; WARN=$((WARN+1)); }
block(){ printf ' %b[BLOCK]%b %s\\n' "$RED" "$RESET" "$*"; BLOCK=$((BLOCK+1)); }
section(){ printf '\\n%b%s%b\\n' "$CYAN" "$*" "$RESET"; }

os_id=unknown; os_name=unknown
if [[ -r /etc/os-release ]]; then . /etc/os-release; os_id="${ID:-unknown}"; os_name="${PRETTY_NAME:-unknown}"; fi
ram_kb="$(awk '/MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
ram_gib="$(awk -v k="${ram_kb:-0}" 'BEGIN{printf "%.1f",k/1048576}')"
cpu_count="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0)"
disk_kb="$(df -Pk / 2>/dev/null | awk 'NR==2 {print $4}')"
disk_gib="$(awk -v k="${disk_kb:-0}" 'BEGIN{printf "%.1f",k/1048576}')"
pid1="$(ps -p 1 -o comm= 2>/dev/null | xargs || true)"
cgroup="$(cat /proc/1/cgroup 2>/dev/null || true)"
in_container=false
if grep -Eqi 'docker|containerd|kubepods|lxc|podman' <<<"$cgroup" || [[ -f /.dockerenv ]] || [[ -f /run/.containerenv ]]; then in_container=true; fi

printf '%b\\n' '=============================================='
printf '%b\\n' '             ONION HUB PREFLIGHT'
printf '%b\\n' '=============================================='
printf 'OS: %s\\nCPU: %s logical cores\\nRAM: %s GiB\\nFree disk on /: %s GiB\\nPID 1: %s\\nContainer detected: %s\\n' "$os_name" "$cpu_count" "$ram_gib" "$disk_gib" "${pid1:-unknown}" "$in_container"

section "1. Base host"
if [[ "$os_id" == ubuntu || "$os_id" == debian ]]; then pass "Ubuntu/Debian detected"; else block "This build targets Ubuntu/Debian only"; fi
if [[ "$(id -u)" -eq 0 ]]; then pass "Root access available"; else block "Root access is required for the standard Panel/Wings deployment"; fi
if [[ "$(uname -m)" == x86_64 || "$(uname -m)" == aarch64 ]]; then pass "Architecture: $(uname -m)"; else block "Unsupported architecture: $(uname -m)"; fi

section "2. Resources"
if (( cpu_count >= 2 )); then pass "CPU: $cpu_count cores"; else warn "Only $cpu_count CPU core(s); performance may be limited"; fi
if awk -v r="$ram_gib" 'BEGIN{exit !(r>=4)}'; then pass "RAM: $ram_gib GiB"; else block "At least 4 GiB RAM is required for the planned Panel + Wings stack"; fi
if awk -v d="$disk_gib" 'BEGIN{exit !(d>=20)}'; then pass "Free disk: $disk_gib GiB"; else block "Only $disk_gib GiB free; at least 20 GiB is required before deployment"; fi

section "3. Wings capability"
if [[ "$pid1" == systemd ]]; then pass "systemd is PID 1"; else warn "systemd is not PID 1 (found: ${pid1:-unknown}); standard persistent Wings service setup cannot run here"; fi
if [[ "$in_container" == true ]]; then warn "Container/Kubernetes environment detected; privileged Docker and persistence must be verified"; else pass "No common container marker detected"; fi
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then pass "Docker daemon reachable"; else warn "Docker daemon unavailable; Wings deployment cannot proceed until a supported Docker daemon is available"; fi

section "4. Network capability"
if command -v curl >/dev/null 2>&1; then
  public4="$(curl -4fsS --connect-timeout 3 --max-time 6 https://api.ipify.org 2>/dev/null || true)"
  if [[ -n "$public4" ]]; then pass "Outbound IPv4: $public4"; else warn "Outbound IPv4 lookup unavailable"; fi
else warn "curl unavailable; public-IP lookup skipped"; fi
if command -v ip >/dev/null 2>&1; then
  printf 'Interfaces:\\n'; ip -brief address 2>/dev/null || true
  printf 'Default route:\\n'; ip route show default 2>/dev/null || true
fi
warn "Outbound IP detection does not prove inbound reachability; inbound ports need independent tests."
warn "Without a public/inbound route, Panel HTTP, Wings API/SFTP and Minecraft game traffic need separate supported routing paths."

section "Result"
printf 'PASS: %d  WARN: %d  BLOCK: %d\\n' "$PASS" "$WARN" "$BLOCK"
if (( BLOCK > 0 )); then
  printf '%bBASE HOST BLOCKED%b — no installation was attempted.\\n' "$RED" "$RESET"
  exit 2
elif (( WARN > 0 )); then
  printf '%bCONDITIONAL%b — some Wings/persistence capabilities need attention.\\n' "$YELLOW" "$RESET"
  exit 1
else
  printf '%bPREFLIGHT PASSED%b — this does not prove inbound routing or a successful deployment.\\n' "$GREEN" "$RESET"
fi
