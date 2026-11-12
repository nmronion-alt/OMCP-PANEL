# OMCP — Onion Minecraft Panel

OMCP is a standalone Minecraft Java server panel for Linux VPS hosts, including hosts without public IPv4. It does **not** install or depend on Pterodactyl or Wings.

## Functional MVP included

- First-run Admin account setup, username/password login, separate user accounts, and salted PBKDF2 password hashes.
- Username matching is case-insensitive; passwords remain case-sensitive.
- Local OMCP agent and web panel; management API stays bound to localhost by default.
- Three-step server wizard (Minecraft version, software, RAM/details); Paper, Vanilla and Fabric server downloads are currently implemented with official download APIs and explicit Minecraft EULA acknowledgement.
- Forge, Spigot and Velocity are visible as planned choices but are not implemented yet.
- Start, stop, restart, Minecraft console commands and recent log viewing.
- Basic text file browser/editor, live ZIP backups, per-server scheduled Google Drive uploads, server list and Linux memory/CPU-thread metrics.
- Minecraft TCP routing adapters for Pinggy and Bore.pub, plus Minekube Connect plugin installation for supported Paper/Spigot/Velocity-compatible servers.
- Local API binds to `127.0.0.1:8765` by default.

## One-command installer (Ubuntu/Debian, systemd or no-systemd)

Review the installer before running it. On a fresh supported VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/nmronion-alt/onion-hub/main/install-omcp.sh -o install-omcp.sh
sudo bash install-omcp.sh
```

Or, after reviewing the script, run it directly:

```bash
curl -fsSL https://raw.githubusercontent.com/nmronion-alt/onion-hub/main/install-omcp.sh | sudo bash
```

The installer installs Python 3 and OpenJDK 21, creates a dedicated unprivileged `omcp` Linux account and downloads the agent/UI. Bore's official static binary is downloaded on first use for Linux x86_64 or ARM64 hosts. On systemd VPS hosts it enables a systemd service; in Cloud Shell/container environments without systemd it starts a background process and writes its log to `/var/lib/omcp/agent.log`. Retrieve the first-run Admin Key with:

```bash
sudo journalctl -u omcp -n 80 --no-pager  # systemd VPS\nsudo cat /var/lib/omcp/agent.log          # no-systemd Cloud Shell/container
```

Open locally at `http://127.0.0.1:8765`. The panel itself is not a public listener. The panel web tunnel and Minecraft TCP routing are separate. Minecraft routing supports Pinggy and Bore.pub TCP relays. Minekube Connect is enabled by installing its official server/proxy plugin; restart the Minecraft server after installation and share the generated `*.play.minekube.net` address.

## Remote access / private-IP VPS

For remote web access, configure Cloudflare Tunnel to `http://localhost:8765` and protect the hostname with Cloudflare Access. Do not expose port 8765 directly or publish an unauthenticated tunnel. The generated OMCP Admin Key is still required for management actions.

Cloudflare's ordinary web tunnel does not relay arbitrary Minecraft Java TCP traffic. Player connectivity requires a separate TCP relay/provider. The installer does not configure a game relay. Cloud Shell is ephemeral: processes and files may disappear when the session ends, so it is for testing rather than persistent hosting.

## MVP limitations

Paper, Vanilla and Fabric creation are implemented; Paper uses PaperMC's current v3 downloads API. Other server software adapters are not implemented yet. Java 21 is installed by the Ubuntu/Debian installer. Cloud backups require the owner to configure Google OAuth credentials (Client ID, Client Secret and Refresh Token) in each server's Backups tab. The scheduler runs only while the OMCP agent is running and the Minecraft server is online. It briefly disables world saving, flushes saves, creates the ZIP, then re-enables saving before uploading. Google Drive uses resumable uploads for large archives. Test on a disposable VPS and back up worlds before production use.

## Source layout

- `agent/omcp_agent.py` — Python standard-library local API/process manager.
- `index.html` — interactive panel served by the agent.
- `install-omcp.sh` — Ubuntu/Debian systemd installer.
- `docs/ARCHITECTURE.md` — architecture and security notes.

No arbitrary host-shell endpoint is provided. Console commands go only to the selected Minecraft server process.
