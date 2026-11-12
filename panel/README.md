# OMCP — Onion Minecraft Panel

OMCP is a single-admin Minecraft Java server panel for a persistent Linux host with Docker Engine and Docker Compose. This is an early development build, not a finished production hosting platform.

## One-command installer (Ubuntu/Debian)

Run on a VPS as a sudo-capable account:

```bash
curl -fsSL https://raw.githubusercontent.com/nmronion-alt/onion-hub/minecraft-panel-foundation/panel/install.sh | sudo bash
```

The installer checks Docker/Compose, clones this branch into `/opt/omcp`, creates a private admin token, builds the panel, starts it, and checks its health. It prints the local URL and admin token at the end. Save the token privately.

## Current features

- OMCP-branded responsive dashboard and single-admin bearer-token login.
- Docker connectivity and managed Minecraft container status.
- Create Java Edition containers using the maintained `itzg/minecraft-server` image.
- Initial software choices: Vanilla, Paper, Purpur, Fabric, Forge and NeoForge.
- Minecraft version field, Java heap selection (1–16 GB), per-server persistent Docker volume.
- Start, stop, restart, recent container logs, and a private in-panel RCON console.
- Minecraft server ports bind to host loopback; a local TCP relay can connect to `127.0.0.1:<assigned-port>`.
- EULA acceptance is an explicit checkbox before a server is created.

## Network layout

The panel HTTP service listens on `127.0.0.1:8787`. Create a Cloudflare Tunnel public hostname that forwards HTTP to `http://127.0.0.1:8787` to publish the web panel. Cloudflare Tunnel web publishing does not automatically expose Minecraft Java TCP to normal game clients. Configure a separate Minecraft-compatible TCP relay and point it at the server's assigned local port.

## Requirements and persistence

- Ubuntu/Debian with systemd, Docker Engine and Docker Compose plugin.
- Docker socket access and permission to run containers.
- Persistent disk for `/var/lib/docker`; each Minecraft world is stored in a named Docker volume.
- Long-running containers/background services must be permitted by the VPS provider.

Fastfetch host RAM/CPU/disk totals are not proof of the container's actual quota. Some hosted shells and notebook environments block Docker, do not allow daemons, or use temporary overlay storage. The installer warns and asks before continuing on overlay/tmpfs storage. If the host resets, server uptime ends; if its storage is ephemeral, worlds can be lost. Keep backups.

## Security

Mounting `/var/run/docker.sock` gives the panel broad control over the Docker host and is effectively root-equivalent. Keep the admin token secret, restrict Cloudflare Access to your own account, and never publish the panel without authentication. Minecraft ports are bound to loopback by default; do not change this unless you understand the network exposure.

## Not implemented yet

Interactive console input, file manager, plugin/mod upload, SFTP, automated Cloudflare Tunnel creation, TCP relay provider integrations, server deletion/reinstall, backups UI, resource monitoring, and theme editor. These must not be treated as available until implemented and tested.
