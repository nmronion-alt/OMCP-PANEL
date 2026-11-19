#!/usr/bin/env bash
set -Eeuo pipefail
PURPLE='\033[1;35m'
CYAN='\033[1;36m'
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
WHITE='\033[1;37m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'
LINE='──────────────────────────────────────────────────────────────────────────────'
OMCP_REPO_REF="${OMCP_REPO_REF:-main}"
REPO="https://raw.githubusercontent.com/nmronion-alt/OMCP-PANEL/${OMCP_REPO_REF}"
TMP='/tmp/omcp-menu'
if [[ "$EUID" -ne 0 ]]; then echo "Run this menu with sudo: sudo bash omcp-menu.sh"; exit 1; fi
mkdir -p "$TMP"
clear 2>/dev/null || true
system_stats() {
  local cpu ram disk load net
  cpu="$(top -bn1 2>/dev/null | awk '/Cpu\(s\)/ {for(i=1;i<=NF;i++) if($i=="id,"){gsub(/,/, "", $(i-1)); printf "%d", 100-$(i-1); exit} if($i=="id"){printf "%d",100-$(i-1); exit}}' || true)"
  [[ -n "$cpu" ]] || cpu="N/A"
  ram="$(free -m 2>/dev/null | awk '/^Mem:/ {if($2>0) printf "%d%%",($3/$2)*100; else print "N/A"}' || true)"
  [[ -n "$ram" ]] || ram="N/A"
  disk="$(df -hP / 2>/dev/null | awk 'NR==2 {print $5}' || true)"
  [[ -n "$disk" ]] || disk="N/A"
  load="$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo N/A)"
  if ip route 2>/dev/null | grep -q '^default'; then net="${GREEN}● ONLINE${RESET}"; else net="${RED}● OFFLINE${RESET}"; fi
  printf "  ${BOLD}${CYAN}◉ SYSTEM STATUS${RESET}\n"
  printf "  ${WHITE}CPU:${RESET} %s%%   ${WHITE}RAM:${RESET} %s   ${WHITE}DISK:${RESET} %s   ${WHITE}LOAD:${RESET} %s   ${WHITE}NETWORK:${RESET} %b\n" "$cpu" "$ram" "$disk" "$load" "$net"
}
banner() {
  clear 2>/dev/null || true
  printf "\n${PURPLE}${BOLD}"
  cat <<'ART'
   ██████╗ ███╗   ███╗ ██████╗██████╗
  ██╔═══██╗████╗ ████║██╔════╝██╔══██╗
  ██║   ██║██╔████╔██║██║     ██████╔╝
  ██║   ██║██║╚██╔╝██║██║     ██╔═══╝
  ╚██████╔╝██║ ╚═╝ ██║╚██████╗██║
   ╚═════╝ ╚═╝     ╚═╝ ╚═════╝╚═╝
ART
  printf "${RESET}"
  printf "  ${BOLD}${WHITE}ONION MINECRAFT CONTROL PANEL${RESET}  ${PURPLE}◆ INSTALLER EDITION${RESET}\n"
  printf "  ${DIM}%s${RESET}\n" "$LINE"
  system_stats
  printf "  ${DIM}%s${RESET}\n\n" "$LINE"
}
section() { printf "\n  ${BOLD}${CYAN}◆ %s${RESET}\n" "$1"; }
option() { printf "  ${BOLD}${YELLOW}[%s]${RESET} ${WHITE}%s${RESET}\n" "$1" "$2"; }
pause(){ echo; read -r -p "$(printf '\033[1;36m  Press Enter to continue...\033[0m ')" _; }
fetch_script(){
  local file="$1" out="$TMP/$1"
  curl -fL --retry 3 --retry-all-errors "$REPO/$file" -o "$out"
  chmod 700 "$out"
  echo "$out"
}
user_manager(){
  if ! id omcp >/dev/null 2>&1; then echo "Install OMCP first, then manage panel users."; return; fi
  clear 2>/dev/null || true
  python3 - <<'PY'
import os, sys, json, re, time, base64, hashlib, secrets, getpass, pathlib, pwd, grp
# Python source is supplied by heredoc; interactive answers must come from the actual terminal.
try:
    sys.stdin = open("/dev/tty", "r")
except OSError:
    raise SystemExit("ERROR: User management requires an interactive terminal (/dev/tty).")
p=pathlib.Path("/var/lib/omcp/users.json")
p.parent.mkdir(parents=True,exist_ok=True)
def load():
    if not p.exists(): return {}
    d=json.loads(p.read_text())
    if not isinstance(d,dict): raise SystemExit("users.json is not a JSON object; no changes made.")
    return d
def save(d):
    t=p.with_suffix(".tmp")
    t.write_text(json.dumps(d,indent=2))
    os.chmod(t,0o600)
    try: os.chown(t,pwd.getpwnam("omcp").pw_uid,grp.getgrnam("omcp").gr_gid)
    except KeyError: pass
    t.replace(p)
def pw():
    a=input("Password (10-128 chars, visible): ")
    b=input("Confirm password (visible): ")
    if a!=b or not 10<=len(a)<=128: raise ValueError("Passwords must match and be 10-128 characters.")
    salt=secrets.token_bytes(16)
    return {"salt":base64.b64encode(salt).decode(),"hash":base64.b64encode(hashlib.pbkdf2_hmac("sha256",a.encode(),salt,310000)).decode(),"iterations":310000}
while True:
    print("\033[2J\033[H", end="")
    print("\033[1;35m╭────────────── OMCP USER MANAGEMENT ──────────────╮\033[0m")
    print("\033[1;36m  [1]\033[0m New User       \033[1;36m[2]\033[0m Manage User (Role)")
    print("\033[1;36m  [3]\033[0m Delete User    \033[1;36m[4]\033[0m List Users")
    print("\033[1;36m  [5]\033[0m Reset User Password")
    print("\033[1;33m  [0]\033[0m Back")
    print("\033[1;35m╰─────────────────────────────────────────────────╯\033[0m")
    choice=input("\033[1;32m  ➜ Select option: \033[0m").strip()
    if choice=="0": break
    users=load()
    try:
        if choice=="1":
            name=input("Username (3-24 letters/numbers/._-): ").strip().lower()
            email=input("Email: ").strip().lower()
            if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,24}",name): raise ValueError("Invalid username.")
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email): raise ValueError("Invalid email.")
            if any(k.casefold()==name.casefold() for k in users): raise ValueError("Username already exists.")
            if any(str(v.get("email","")).casefold()==email for v in users.values()): raise ValueError("Email already exists.")
            admin=input("Admin: create this as an administrator user? [y/N]: ").strip().lower() in ("y","yes")
            users[name]={"role":"admin" if admin else "user","created":int(time.time()),"email":email,"password":pw()}
            save(users); print("Created", "Administrator" if admin else "Normal user", name)
        elif choice=="2":
            for k,v in users.items(): print(f"{k} | {v.get('email','')} | {v.get('role','user')}")
            name=input("Username to manage: ").strip()
            if name not in users: raise ValueError("User not found.")
            role=input("New role: [A]dministrator / [N]ormal: ").strip().lower()
            if role not in ("a","admin","n","normal","user"): raise ValueError("Choose A or N.")
            newrole="admin" if role in ("a","admin") else "user"
            if users[name].get("role")=="admin" and newrole!="admin" and sum(v.get("role")=="admin" for v in users.values())<=1: raise ValueError("Cannot demote the last administrator.")
            users[name]["role"]=newrole; save(users); print("Updated role.")
        elif choice=="3":
            for k,v in users.items(): print(f"{k} | {v.get('email','')} | {v.get('role','user')}")
            name=input("Username to delete: ").strip()
            if name not in users: raise ValueError("User not found.")
            if users[name].get("role")=="admin" and sum(v.get("role")=="admin" for v in users.values())<=1: raise ValueError("Cannot delete the last administrator.")
            if input("Type DELETE to confirm: ").strip()!="DELETE": print("Cancelled."); continue
            del users[name]; save(users); print("Deleted",name)
        elif choice=="4":
            for k,v in users.items(): print(f"{k} | {v.get('email','')} | {v.get('role','user')}")
        elif choice=="5":
            for k,v in users.items(): print(f"{k} | {v.get('email','')} | {v.get('role','user')}")
            name=input("Username to reset password: ").strip()
            if name not in users: raise ValueError("User not found.")
            users[name]["password"]=pw(); save(users); print("Password reset for",name)
        else: print("Invalid option.")
    except Exception as e: print("ERROR:",e)
PY
}
minecraft_ip(){
  if ! id omcp >/dev/null 2>&1; then echo "Install OMCP first, then configure the Minecraft domain."; return; fi
  local domain port
  read -r -p "Minecraft domain (example: mc.example.com): " domain
  read -r -p "Minecraft server port [25565]: " port
  port="${port:-25565}"
  if [[ ! "$domain" =~ ^([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$ || ! "$port" =~ ^[0-9]{1,5}$ ]] || ((port<1 || port>65535)); then echo "Invalid domain or port."; return; fi
  install -d -m 0750 -o omcp -g omcp /var/lib/omcp
  DOMAIN="$domain" PORT="$port" python3 - <<'PY'
import os,json,pathlib
p=pathlib.Path("/var/lib/omcp/network.json")
d=json.loads(p.read_text()) if p.exists() else {}
d["minecraft"]={"domain":os.environ["DOMAIN"],"port":int(os.environ["PORT"])}
t=p.with_suffix(".tmp"); t.write_text(json.dumps(d,indent=2)); t.replace(p)
PY
  chown omcp:omcp /var/lib/omcp/network.json
  echo "Saved Minecraft endpoint: $domain:$port"
  echo "DNS reminder: create an A record for $domain pointing to this VPS IPv4."
  if [[ "$port" != "25565" ]]; then echo "For Java clients, also create an SRV record: _minecraft._tcp.$domain -> target $domain, port $port."; fi
}
tunnel_menu(){
  while true; do
    section "NON-IPv4 TUNNEL MANAGEMENT"
    option 1 "Restart panel tunnel"
    option 2 "Show panel URL"
    option 3 "Show tunnel status / log"
    option 0 "Back"
    printf "\n  ${BOLD}${GREEN}➜ Enter option:${RESET} "
    read -r x
    case "$x" in
      1) if systemctl list-unit-files 2>/dev/null | grep -q '^omcp-tunnel.service'; then systemctl restart omcp-tunnel; else echo "No systemd tunnel service found."; fi ;;
      2) cat /var/lib/omcp/panel-url 2>/dev/null || echo "No public URL saved yet." ;;
      3) systemctl status omcp-tunnel --no-pager 2>/dev/null || true; tail -n 50 /var/lib/omcp/tunnl.log 2>/dev/null || true ;;
      0) return ;;
      *) echo "Invalid option." ;;
    esac
  done
}
validate_ipv4_target(){
  local host="$1" public_ip resolved
  public_ip="$(curl -4fsS --max-time 10 https://api.ipify.org)" || { echo "ERROR: Could not detect the VPS public IPv4."; return 1; }
  if [[ ! "$public_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then echo "ERROR: Invalid public IPv4 response: $public_ip"; return 1; fi
  echo "Detected VPS public IPv4: $public_ip"
  if [[ "$host" == "$public_ip" ]]; then return 0; fi
  if [[ ! "$host" =~ ^([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$ ]]; then echo "Enter the detected public IPv4 ($public_ip) or a valid domain."; return 1; fi
  resolved="$(getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1{print $1}' || true)"
  if [[ "$resolved" != "$public_ip" ]]; then
    echo "DNS currently resolves $host to ${resolved:-no IPv4}; VPS IPv4 is $public_ip."
    read -r -p "If you use Cloudflare proxy/CDN, verify its origin A record then type YES to continue: " confirm
    [[ "$confirm" == "YES" ]] || return 1
  fi
}
configure_ipv4_proxy(){
  local host="$1" email="$2" public_ip resolved panel_url
  public_ip="$(curl -4fsS --max-time 10 https://api.ipify.org)"
  if [[ ! "$public_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then echo "ERROR: Public IPv4 detection failed."; return 1; fi
  if [[ "$host" != "$public_ip" ]]; then
    if [[ ! "$host" =~ ^([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$ ]]; then echo "Enter the VPS IPv4 ($public_ip) or a valid domain."; return 1; fi
    resolved="$(getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1{print $1}' || true)"
    if [[ "$resolved" != "$public_ip" ]]; then
      echo "DNS resolves to ${resolved:-no IPv4}; if using Cloudflare proxy, confirm the origin A record points to $public_ip."
      read -r -p "Type YES to continue: " confirm
      [[ "$confirm" == "YES" ]] || return 1
    fi
  fi
  DEBIAN_FRONTEND=noninteractive apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y nginx certbot python3-certbot-nginx
  cat >/etc/nginx/sites-available/omcp <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $host;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
    }
}
NGINX
  ln -sfn /etc/nginx/sites-available/omcp /etc/nginx/sites-enabled/omcp
  nginx -t
  systemctl enable --now nginx 2>/dev/null || service nginx start
  if [[ "$host" != "$public_ip" ]]; then
    if [[ -z "$email" ]]; then echo "A valid email is required for the HTTPS certificate."; return 1; fi
    certbot --nginx --non-interactive --agree-tos --redirect --email "$email" -d "$host"
    panel_url="https://$host"
  else
    panel_url="http://$host"
    echo "WARNING: IP-only access is HTTP. Use a domain to enable trusted HTTPS."
  fi
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow 80/tcp || true; ufw allow 443/tcp || true; fi
  printf '%s\n' "$panel_url" >/var/lib/omcp/panel-url
  echo
  echo "=================================================="
  echo "OMCP PANEL URL: $panel_url"
  echo "=================================================="
}
run_install(){
  local mode="$1" host email script
  if [[ "$mode" == "ipv4" ]]; then
    read -r -p "Panel public IPv4 or custom domain: " host
    if [[ -z "$host" ]]; then echo "A public IP or domain is required."; return; fi
    validate_ipv4_target "$host" || return 1
    if [[ "$host" =~ ^([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$ ]]; then
      read -r -p "Email for HTTPS certificate: " email
    fi
  fi
  script="$(fetch_script install-omcp.sh)"
  OMCP_INSTALL_MODE="$mode" OMCP_PANEL_HOST="${host:-}" OMCP_PANEL_EMAIL="${email:-}" bash "$script"
  if [[ "$mode" == "ipv4" ]]; then configure_ipv4_proxy "$host" "$email"; fi
}
run_uninstall(){
  local script
  script="$(fetch_script uninstall-omcp.sh)"
  bash "$script"
}
run_update(){
  local script
  if [[ ! -d /opt/omcp || ! -d /var/lib/omcp ]]; then
    echo "OMCP installation was not found on this VPS."
    return 1
  fi
  script="$(fetch_script update-omcp.sh)"
  bash "$script"
}
mode_menu(){
  local mode="$1" label="$2" choice
  while true; do
    banner
    printf "  ${BOLD}${PURPLE}MODE:${RESET} ${BOLD}${GREEN}%s${RESET}\n" "$label"
    section "DEPLOYMENT & SERVICES"
    option 1 "Install OMCP"
    option 2 "Uninstall OMCP"
    option 3 "User Management"
    if [[ "$mode" == "ipv4" ]]; then option 4 "Minecraft IP / Domain"; else option 4 "Tunnel Management"; fi
    option 5 "Update OMCP — fetch latest GitHub version"
    option 0 "Back"
    printf "\n  ${BOLD}${GREEN}➜ Enter option:${RESET} "
    read -r choice
    case "$choice" in
      1) run_install "$mode"; pause ;;
      2) run_uninstall; pause ;;
      3) user_manager ;;
      4) if [[ "$mode" == "ipv4" ]]; then minecraft_ip; else tunnel_menu; fi; pause ;;
      5) run_update; pause ;;
      0) return ;;
      *) echo "Invalid option."; pause ;;
    esac
  done
}
while true; do
  banner
  section "NETWORK / DEPLOYMENT MODE"
  option 1 "IPv4 Mode       — Direct IP / Domain"
  option 2 "Non-IPv4 Mode   — tunnl.gg Reverse Tunnel"
  option 0 "Exit Installer"
  printf "\n  ${BOLD}${GREEN}➜ Enter option:${RESET} "
  read -r choice
  case "$choice" in
    1) mode_menu ipv4 "IPv4" ;;
    2) mode_menu nonipv4 "Non-IPv4" ;;
    0) exit 0 ;;
    *) echo "Invalid option."; pause ;;
  esac
done
