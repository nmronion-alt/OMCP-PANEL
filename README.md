# OMCP — Onion Minecraft Panel

OMCP is a standalone web panel for creating and managing Minecraft Java servers on a Linux host, including hosts that do not have a public IPv4 address.

**This project does not install or depend on Pterodactyl or Wings.**

## Product model

- **Web UI:** dashboard, server list, console, file manager, software/version settings, backups, and routing settings.
- **Local agent:** runs on the VPS and manages Minecraft server processes and their files.
- **Process supervisor:** starts every managed server as a child process with a controlled console (PTY), records its PID/state, and restarts only according to the user's configured policy.
- **Panel access:** the agent's web/API listener binds to localhost; Cloudflare Tunnel can publish the HTTP(S) panel without requiring inbound IPv4.
- **Game access:** Minecraft player traffic is a separate TCP-routing concern. A supported external TCP relay/provider (for example, a compatible Minekube Connect integration) is required when the host cannot accept inbound connections. Cloudflare's ordinary web tunnel is not a general Minecraft TCP relay.

## Core workflows

1. Install OMCP on a supported Linux host.
2. Open the panel through its local address or a configured Cloudflare Tunnel.
3. Create the first server in the panel by selecting Minecraft software/version, Java runtime, memory limit, and a server name.
4. Accept the EULA and start the server.
5. Add more servers with separate directories, ports, memory limits, and process sessions.
6. Configure a game-traffic route separately if players outside the host need to connect.

## Existing server import

OMCP can scan user-selected directories for server files and show candidates to import. It must not silently take over a process or modify a world. For reliable console access, an imported server should be stopped and relaunched under OMCP's process supervisor. An arbitrary detached Java process cannot always have its stdin/console safely reattached.

## Security requirements

- Bind the management API to loopback by default; expose it only through an authenticated HTTPS route.
- Require login and CSRF protection for browser actions.
- Use per-server directory boundaries; reject path traversal and symlink escapes.
- Never run user-supplied shell strings. Build process arguments as arrays and validate software, version, port, and memory inputs.
- Keep tokens and passwords out of source control, URLs, logs, and shell history.
- Back up world/config files before destructive operations; require explicit confirmation.
- Do not expose a raw terminal or unrestricted host shell through the panel.
- Use least privilege and do not run the agent as root unless a documented operation requires it.

## Deployment notes

A private IPv4 address does not prevent the panel itself from being accessed: an outbound Cloudflare Tunnel can publish the web UI. It does not, by itself, make Minecraft ports publicly reachable. Game routing needs a separate TCP-capable provider and its own credentials/configuration. SFTP is not required for the web file manager.

Cloud Shell and similar ephemeral environments may terminate or reset sessions and storage. They are useful for development/testing but should not be described as reliable permanent game hosting.

## Repository status

This repository is being refocused as OMCP. The current UI is a static design preview; the authenticated API, local process supervisor, server creation, file operations, backups, and routing adapters still need implementation and testing. Do not treat the preview as a working server manager yet.

## Planned implementation order

1. Secure local agent/API and authentication.
2. Process supervisor with PTY-backed console.
3. Create/list/start/stop/restart Minecraft servers.
4. Safe file manager, logs, backups, and resource metrics.
5. Software/version installer with Java compatibility checks.
6. Cloudflare Tunnel setup for panel access.
7. Pluggable TCP routing adapters for Minecraft game traffic.
