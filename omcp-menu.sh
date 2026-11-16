#!/usr/bin/env bash
set -Eeuo pipefail
PURPLE='\033[1;35m'
CYAN='\033[1;36m'
RESET='\033[0m'
REPO='https://raw.githubusercontent.com/nmronion-alt/OMCP-PANEL/main'
TMP='/tmp/omcp-menu'
if [[ "$EUID" -ne 0 ]]; then echo "Run this menu with sudo: sudo bash omcp-menu.sh"; exit 1; fi
mkdir -p "$TMP"
clear 2>/dev/null || true
banner() {
  clear 2>/dev/null || true
  echo -e "${PURPLE}"
  cat <<'ART'
   ____  __  __ ____ ____  ___
  / __ \\/\\ \\/ // ___/  _/ / _ \\
 / /_/ / \\ V / / /   / /  / ___/
/_____/   \\_/ /_/   /___/ /_/
          INSTALLER
ART
  echo -e "${RESET}"
  echo "             O M C P   I N S T A L L E R"
  echo
}
pause(){ echo; read -r -p "Press Enter to return to menu..." _; }
fetch_script(){
  local file="$1" out="$TMP/$1"
  curl -fL --retry 3 --retry-all-errors "$REPO/$file" -o "$out"
  chmod 700 "$out"
  echo "$out"
}
user_manager(){
  python3 - <<'PY'
import os, json, re, time, base64, hashlib, secrets, getpass, pathlib
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
    os.chmod(t,0o600); t.replace(p)
def pw():
    a=getpass.getpass("Password (10-128 chars): ")
    b=getpass.getpass("Confirm password: ")
    if a!=b or not 10<=len(a)<=128: raise ValueError("Passwords must match and be 10-128 characters.")
    salt=secrets.token_bytes(16)
    return {"salt":base64.b64encode(salt).decode(),"hash":base64.b64encode(hashlib.pbkdf2_hmac("sha256",a.encode(),salt,310000)).decode(),"iterations":310000}
while True:
    print("\n===== OMCP USER MANAGEMENT =====")
    print("1) New User\n2) Manage User (role)\n3) Delete User\n4) List Users\n0) Back")
    choice=input("Select: ").strip()
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
        else: print("Invalid option.")
    except Exception as e: print("ERROR:",e)
PY
}
minecraft_ip(){
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
    echo; echo "===== NON-IPv4 TUNNEL ====="
    echo "1) Restart panel tunnel"
    echo "2) Show panel URL"
    echo "3) Show tunnel status/log"
    echo "0) Back"
    read -r -p "Select: " x
    case "$x" in
      1) if systemctl list-unit-files 2>/dev/null | grep -q '^omcp-tunnel.service'; then systemctl restart omcp-tunnel; else echo "No systemd tunnel service found."; fi ;;
      2) cat /var/lib/omcp/panel-url 2>/dev/null || echo "No public URL saved yet." ;;
      3) systemctl status omcp-tunnel --no-pager 2>/dev/null || true; tail -n 50 /var/lib/omcp/tunnl.log 2>/dev/null || true ;;
      0) return ;;
      *) echo "Invalid option." ;;
    esac
  done
}
configure_ipv4_proxy(){
  local host="$1" email="$2" public_ip resolved panel_url
  public_ip="$(curl -4fsS --max-time 10 https://api.ipify.org)"
  if [[ ! "$public_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then echo "ERROR: Public IPv4 detection failed."; return 1; fi
  if [[ "$host" != "$public_ip" ]]; then
    if [[ ! "$host" =~ ^([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$ ]]; then echo "Enter the VPS IPv4 ($public_ip) or a valid domain."; return 1; fi
    resolved="$(getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1{print $1}' || true)"
    if [[ "$resolved" != "$public_ip" ]]; then echo "DNS A record for $host must point to $public_ip (currently: ${resolved:-not resolved})."; return 1; fi
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
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\$scheme;
        proxy_read_timeout 3600s;
    }
}
NGINX
  ln -sfn /etc/nginx/sites-available/omcp /etc/nginx/sites-enabled/omcp
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable --now nginx
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
mode_menu(){
  local mode="$1" label="$2" choice
  while true; do
    banner
    echo "MODE: $label"
    echo
    echo "1) Install"
    echo "2) Uninstall"
    echo "3) User Management"
    if [[ "$mode" == "ipv4" ]]; then echo "4) Minecraft IP / Domain"; else echo "4) Tunnel Management"; fi
    echo "0) Back"
    read -r -p "Select an option: " choice
    case "$choice" in
      1) run_install "$mode"; pause ;;
      2) run_uninstall; pause ;;
      3) user_manager; pause ;;
      4) if [[ "$mode" == "ipv4" ]]; then minecraft_ip; else tunnel_menu; fi; pause ;;
      0) return ;;
      *) echo "Invalid option."; pause ;;
    esac
  done
}
while true; do
  banner
  echo "Choose your network mode:"
  echo
  echo "1) IPv4 Mode       (Direct IP / Domain, no tunnel)"
  echo "2) Non-IPv4 Mode   (tunnl.gg reverse tunnel)"
  echo "0) Exit"
  read -r -p "Select an option: " choice
  case "$choice" in
    1) mode_menu ipv4 "IPv4" ;;
    2) mode_menu nonipv4 "Non-IPv4" ;;
    0) exit 0 ;;
    *) echo "Invalid option."; pause ;;
  esac
done
