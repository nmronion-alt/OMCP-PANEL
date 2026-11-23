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

Run this command on a fresh Ubuntu/Debian VPS with root or `sudo` access:

```bash
curl -fL --retry 3 --retry-all-errors "https://raw.githubusercontent.com/nmronion-alt/OMCP-PANEL/main/omcp-menu.sh" -o /tmp/omcp-menu.sh && sudo bash /tmp/omcp-menu.sh
```

The installer opens an interactive IPv4 / Non-IPv4 menu. In IPv4 mode, both the VPS public IPv4 and the configured panel domain are accepted by the reverse proxy; a domain can receive HTTPS through Let's Encrypt, while IP-only access uses HTTP. Minecraft connection addresses are generated from the configured domain or VPS IPv4 plus the port selected for each server. No port is entered in the Minecraft host setup.

## 🔄 Update an existing VPS

Open the latest menu (the menu is downloaded fresh from GitHub each time):

```bash
curl -fL --retry 3 --retry-all-errors "https://raw.githubusercontent.com/nmronion-alt/OMCP-PANEL/main/omcp-menu.sh" -o /tmp/omcp-menu.sh && sudo bash /tmp/omcp-menu.sh
```

Choose **IPv4 Mode** or **Non-IPv4 Mode**, then select **[5] Update OMCP**. The updater downloads the latest panel code from the GitHub `main` branch, validates it, makes a rollback backup of `/opt/omcp`, replaces the application files and restarts the OMCP agent. It does not delete or overwrite `/var/lib/omcp`, so Minecraft servers, worlds, plugins, backups, users and configuration remain in place.

You can also run the updater directly:

```bash
curl -fL --retry 3 --retry-all-errors "https://raw.githubusercontent.com/nmronion-alt/OMCP-PANEL/main/update-omcp.sh" -o /tmp/update-omcp.sh && sudo bash /tmp/update-omcp.sh
```


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

The management API listens on `127.0.0.1:8765` by default. IPv4 mode publishes it through the VPS reverse proxy using the public IP and configured domain; Non-IPv4 mode uses the selected tunnel provider.

## 🚀 Features

| Area | What you can do |
|---|---|
| 🖥️ **Server Console** | Start, stop and restart servers, send console commands, and view live/recent logs |
| 📦 **Server Software** | Create and manage supported Minecraft server types and choose available versions |
| 📁 **File Manager** | Browse, upload, edit, rename, delete, download and archive server files; extract ZIP archives |
| 🌍 **World Manager** | View server worlds, import worlds from ZIP or folder, and manage eligible worlds |
| ⚙️ **Options** | Configure common server properties, gameplay settings and MOTD with a formatted preview |
| 🧩 **Plugins** | Browse compatible plugin catalogues, choose versions and install plugins on supported Bukkit-based servers |
| 🧵 **Fabric Mods** | Browse Modrinth Fabric mods and modpacks, select compatible releases and install them |
| 👥 **Players** | Read live status samples and manage ban, unban and operator records without sending console commands |
| 💾 **Backups** | Create ZIP backups and schedule local VPS or Google Drive backups |
| 🔐 **SFTP** | Generate SFTP credentials; IPv4 mode uses the VPS public IPv4 directly, while Non-IPv4 mode uses a dedicated TCP tunnel |
| 🌐 **Network Routing** | Non-IPv4 mode provides supported tunnel/relay controls; IPv4 mode uses direct VPS addressing and hides tunnel routing controls |
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
