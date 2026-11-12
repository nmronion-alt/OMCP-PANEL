# OMCP — Onion Minecraft Panel

OMCP is a standalone Minecraft Java server panel for Linux VPS hosts, including hosts without public IPv4. It does **not** install or depend on Pterodactyl or Wings.

## Functional MVP included

- One local OMCP agent and web panel; no user-account system.
- A generated Admin Key protects management actions (necessary because the panel can start/stop game servers).
- Create Paper servers by name, Minecraft version, RAM and port, with explicit Minecraft EULA acknowledgement.
- Start, stop, restart, Minecraft console commands and recent log viewing.
- Basic text file browser/editor, ZIP backups, server list and Linux memory/CPU-thread metrics.
- Local API binds to `127.0.0.1:8765` by default.

## One-command installer (Ubuntu/Debian with systemd)

Review the installer before running it. On a fresh supported VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/nmronion-alt/onion-hub/main/install-omcp.sh -o install-omcp.sh
sudo bash install-omcp.sh
```

Or, after reviewing the script, run it directly:

```bash
curl -fsSL https://raw.githubusercontent.com/nmronion-alt/onion-hub/main/install-omcp.sh | sudo bash
```

The installer installs Python 3 and OpenJDK 21, creates a dedicated unprivileged `omcp` Linux account, downloads the agent/UI and enables a systemd service. Retrieve the first-run Admin Key with:

```bash
sudo journalctl -u omcp -n 80 --no-pager
```

Open locally at `http://127.0.0.1:8765`. The panel itself is not a public listener.

## Remote access / private-IP VPS

For remote web access, configure Cloudflare Tunnel to `http://localhost:8765` and protect the hostname with Cloudflare Access. Do not expose port 8765 directly or publish an unauthenticated tunnel. The generated OMCP Admin Key is still required for management actions.

Cloudflare's ordinary web tunnel does not relay arbitrary Minecraft Java TCP traffic. Player connectivity requires a separate TCP relay/provider. The installer does not configure a game relay.

## MVP limitations

Paper only; selected versions are downloaded from PaperMC's API. Java 21 is installed by the Ubuntu/Debian installer. The MVP does not yet include Fabric/Forge, plugin catalogue, live CPU percentage, delete/restore UI, automatic Cloudflare setup, or a TCP game-routing adapter. Test on a disposable VPS and back up worlds before production use.

## Source layout

- `agent/omcp_agent.py` — Python standard-library local API/process manager.
- `index.html` — interactive panel served by the agent.
- `install-omcp.sh` — Ubuntu/Debian systemd installer.
- `docs/ARCHITECTURE.md` — architecture and security notes.

No arbitrary host-shell endpoint is provided. Console commands go only to the selected Minecraft server process.
