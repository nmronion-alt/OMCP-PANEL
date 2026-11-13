# OMCP — Onion Minecraft Panel

OMCP is a standalone Minecraft Java server panel for Linux VPS hosts, including hosts without public IPv4. It does **not** install or depend on Pterodactyl or Wings.

## Functional MVP included

- First-run Admin account setup, username/password login, separate user accounts, and salted PBKDF2 password hashes.
- Username matching is case-insensitive; passwords remain case-sensitive.
- Local OMCP agent and web panel; management API stays bound to localhost by default.
- Three-step server wizard (Minecraft version, software, RAM/details); Paper, Vanilla and Fabric server downloads are currently implemented with official download APIs and explicit Minecraft EULA acknowledgement.
- Forge, Spigot and Velocity are visible as planned choices but are not implemented yet.
- Start, stop, restart, Minecraft console commands and recent log viewing.
- File browser/editor with line numbers and basic syntax coloring, Aternos-style server.properties controls, world listing/deletion, safe server deletion with a final ZIP, and server software cards with optional wipe-after-backup.
- Live ZIP backups, per-server scheduled local-VPS backups (no OAuth) or Google Drive uploads, server list and Linux memory/CPU-thread metrics.
- Minecraft TCP routing adapters for Pinggy and Bore.pub, plus Minekube Connect plugin installation for supported Paper/Spigot/Velocity-compatible servers.
- Local API binds to `127.0.0.1:8765` by default.

## One-command installer (Ubuntu/Debian)

On a fresh Ubuntu/Debian VPS with sudo access, run this single command:

```bash
curl -fsSL https://raw.githubusercontent.com/nmronion-alt/onion-hub/main/install-omcp.sh | sudo bash
```

The installer installs the required runtime, creates the dedicated `omcp` service account, downloads the latest panel and agent, and starts OMCP. The panel URL and first-run setup details are printed by the installer. Cloud Shell/container sessions may be temporary; use a persistent VPS for a long-running panel.

## Remote access / private-IP VPS

For remote web access, configure Cloudflare Tunnel to `http://localhost:8765` and protect the hostname with Cloudflare Access. Do not expose port 8765 directly or publish an unauthenticated tunnel. The generated OMCP Admin Key is still required for management actions.

Cloudflare's ordinary web tunnel does not relay arbitrary Minecraft Java TCP traffic. Player connectivity requires a separate TCP relay/provider. The installer does not configure a game relay. Cloud Shell is ephemeral: processes and files may disappear when the session ends, so it is for testing rather than persistent hosting.

## MVP limitations

Paper, Vanilla and Fabric creation are implemented; Paper uses PaperMC's current v3 downloads API. Other server software adapters are not implemented yet. Java 21 is installed by the Ubuntu/Debian installer. Google Drive backups require the owner to configure Google OAuth credentials (Client ID, Client Secret and Refresh Token) in the Backups tab. Automatic local-VPS backups need no OAuth but are not off-site and can be lost with the VPS. The scheduler runs only while the OMCP agent is running and the Minecraft server is online. It briefly disables world saving, flushes saves, creates the ZIP, then re-enables saving before uploading. Google Drive uses resumable uploads for large archives. Test on a disposable VPS and back up worlds before production use.

## Source layout

- `agent/omcp_agent.py` — Python standard-library local API/process manager.
- `index.html` — interactive panel served by the agent.
- `install-omcp.sh` — Ubuntu/Debian systemd installer.
- `docs/ARCHITECTURE.md` — architecture and security notes.

No arbitrary host-shell endpoint is provided. Console commands go only to the selected Minecraft server process.
