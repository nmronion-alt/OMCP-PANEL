#!/usr/bin/env bash
# ONION HUB — installer entry point for OMCP (Onion Minecraft Panel)
# This foundation build performs preflight only. Deployment modules are not yet shipped.
set -Eeuo pipefail

VERSION="0.4.0-foundation"
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PURPLE=$'\\033[1;38;5;141m'
CYAN=$'\\033[1;38;5;117m'
YELLOW=$'\\033[1;38;5;220m'
RESET=$'\\033[0m'

printf '%b\\n' "${PURPLE}ONION HUB ${VERSION}${RESET}"
printf '%b\\n' "OMCP — Onion Minecraft Panel"
printf '%b\\n' "One-command setup entry point"
printf '\\n'

if [[ "$(id -u)" -ne 0 ]]; then
  printf '%b\\n' "${YELLOW}Run this installer as root on a host intended for deployment.${RESET}"
  exit 1
fi

if [[ ! -f "${ROOT_DIR}/preflight.sh" ]]; then
  printf '%b\\n' "ERROR: preflight.sh is missing. Re-download the complete repository."
  exit 1
fi

printf '%b\\n' "${CYAN}[1/2] Checking host compatibility...${RESET}"
set +e
bash "${ROOT_DIR}/preflight.sh"
PREFLIGHT_STATUS=$?
set -e

if [[ "${PREFLIGHT_STATUS}" -eq 2 ]]; then
  printf '\\n%b\\n' "${YELLOW}Deployment blocked: resolve the listed requirements first. No packages or services were changed.${RESET}"
  exit 2
fi

printf '\\n%b\\n' "${CYAN}[2/2] Checking deployment modules...${RESET}"
if [[ ! -x "${ROOT_DIR}/modules/deploy.sh" ]]; then
  printf '%b\\n' "${YELLOW}The deployment engine is not included in this foundation release yet.${RESET}"
  printf '%b\\n' "No Panel, database, Wings, tunnel, relay, firewall rule, or Minecraft data was changed."
  printf '%b\\n' "This script is intentionally not pretending that OMCP has been installed."
  exit 3
fi

exec "${ROOT_DIR}/modules/deploy.sh"
