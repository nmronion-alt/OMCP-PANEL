# Minecraft Server Panel — Foundation

This is the first implementation stage. It is deliberately a single-admin panel, not a multi-user hosting platform.

## Included now

- Responsive web dashboard.
- Bearer-token authentication for administrative API calls.
- Docker connectivity check.
- Listing of containers labelled `managed-by=mc-panel`.
- Start, stop and restart for those labelled containers.
- Recent container logs.

## Not implemented yet

- Creating/deleting Minecraft servers.
- File manager and SFTP.
- Plugin and mod installers.
- Minecraft/Paper/Fabric/Forge version selection.
- Cloudflare Tunnel provisioning.
- Minecraft TCP routing providers.
- Theme editor and background image upload.

## Run on a supported Linux Docker host

1. Install Docker Engine and Docker Compose plugin on a persistent Linux host.
2. From this directory, create a private environment file:

   ```bash
   cp .env.example .env
   ```

3. Generate a token and put it in `.env` (do not commit this file):

   ```bash
   openssl rand -hex 32
   chmod 600 .env
   ```

4. Build and start:

   ```bash
   docker compose up -d --build
   ```

5. Open locally at `http://127.0.0.1:8787`. A Cloudflare Tunnel can be configured later to publish this HTTP service.

## Security note

Mounting `/var/run/docker.sock` grants the panel container control over the host Docker daemon and is effectively highly privileged. Do not expose this service directly to the public internet. Keep the single-admin token private and put the web service behind HTTPS and authentication. The current API only operates on containers carrying the `managed-by=mc-panel` label.

## Compatibility

A successful Minecraft process on a hosted shell does not guarantee Docker support. This stage requires Docker Engine, permission to access its socket, persistent storage, and a host that permits long-running background containers. Hosted notebook/shell environments may reset or terminate workloads.
