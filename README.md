# 🧅 OMCP — Onion Minecraft Control Panel

<p align="center">
  <strong>A self-hosted Minecraft server control panel.</strong><br>
  Manage your Minecraft servers, files, worlds, plugins, backups and network access from one clean dashboard.
</p>

<p align="center">
  <a href="https://discord.gg/kRGg2HjRKn">💬 Join our Discord</a>
  &nbsp;•&nbsp;
  <a href="https://www.youtube.com/@not_mr_onion1">▶️ YouTube — not Mr Onion</a>
</p>

<p align="center">
  <strong>Created by not Mr Onion</strong>
</p>

---

## ⚡ Install OMCP

Run this **single command** on a fresh Ubuntu/Debian VPS with `sudo` access:

```bash
```bash
curl -fsSL curl -fsSL https://raw.githubusercontent.com/nmronion-alt/OMCP-PANEL/main/install-omcp.sh -o /tmp/omcp.sh && sudo bash /tmp/omcp.sh && for i in $(seq 1 60); do u=$(sudo grep -Eo 'https://[A-Za-z0-9.-]+\.tunnl\.gg' /var/lib/omcp/tunnl.log 2>/dev/null | tail -n 1 || true); [ -n "$u" ] && { echo "OMCP PANEL: $u"; exit 0; }; sleep 2; done; echo "Tunnel pending — check /var/lib/omcp/tunnl.log"
```
```

The installer sets up OMCP and starts its panel tunnel. When the tunnel connects, the command prints the **Panel Link** in your terminal. Open that link in your browser.

> **Note:** This installer targets Ubuntu/Debian systems. Use a persistent VPS for a panel that should stay online. Temporary cloud-shell sessions can stop or lose their files when the session ends.

## ✨ What is OMCP?

OMCP is a self-hosted control panel for managing Minecraft Java servers on your own Linux host. It includes a web dashboard and a local agent that controls the Minecraft server process and its files.

**How it works**

```text
Your Browser
    │
    ▼
OMCP Web Panel (HTTPS)
    │
    ▼
OMCP Agent on your VPS
    │
    ├── Minecraft Server
    ├── Server Files & Worlds
    ├── Plugins & Configuration
    └── Backups & Network Routing
```

The management API listens on `127.0.0.1:8765` by default. The installer provides the panel's remote HTTPS link through its tunnel.

## 🚀 Features

| Area | What you can do |
|---|---|
| 🖥️ **Server Console** | Start, stop and restart servers, send console commands, and view live/recent logs |
| 📦 **Server Software** | Create and manage supported Minecraft server types and choose available versions |
| 📁 **File Manager** | Browse, upload, edit, rename, delete, download and archive server files; extract ZIP archives |
| 🌍 **World Manager** | View server worlds, import worlds from ZIP or folder, and manage eligible worlds |
| ⚙️ **Options** | Configure common server properties, gameplay settings and MOTD with a formatted preview |
| 🧩 **Plugins** | Browse plugin catalogues, choose available plugin versions, install plugins and see detected installed plugins |
| 💾 **Backups** | Create ZIP backups and schedule local VPS or Google Drive backups |
| 🔐 **SFTP** | Access server files through the panel's SFTP service |
| 🌐 **Network Routing** | Use supported Minecraft TCP relay options and Minekube Connect integration |
| 📊 **Resource Information** | View host memory and CPU-thread information |
| 👤 **Accounts** | Set up an admin account and sign in with protected password storage |

Feature availability depends on the selected Minecraft software, version, host environment and configured providers. Some plugin or server-software combinations may need a manual restart or additional compatibility checks.

## 🧰 Requirements

- Ubuntu or Debian Linux VPS
- Root or `sudo` access
- Internet connection for installation and downloads
- A persistent host for long-running use

The installer installs the runtime components it needs, including Java 21 where required.

## 🔒 Security & networking

- The OMCP management API binds to localhost (`127.0.0.1:8765`) by default.
- Do not expose the management API directly to the public internet.
- Keep your admin credentials private and use a trusted HTTPS access method.
- Minecraft Java player traffic uses a separate TCP route/relay; a web HTTPS tunnel alone does not carry Minecraft TCP connections.
- Local backups stay on the VPS. They are not off-site and can be lost if the host is lost.
- Google Drive backups require your own Google OAuth configuration.

## 🧑‍💻 Project files

- `agent/omcp_agent.py` — local API and Minecraft process manager
- `index.html` — OMCP web dashboard
- `install-omcp.sh` — installer
- `docs/ARCHITECTURE.md` — architecture and security notes

## 💬 Community & updates

Questions, feedback or ideas? Join the community:

- **Discord:** https://discord.gg/kRGg2HjRKn
- **YouTube:** https://www.youtube.com/@not_mr_onion1

---

<p align="center">
  Made with 🧅 by <strong>not Mr Onion</strong>
</p>
