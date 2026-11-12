# OMCP architecture

## Goal

Run a standalone Minecraft management panel on a Linux VPS even when it has no public IPv4 address. Do not deploy Pterodactyl Panel, Wings, or Docker as a product dependency.

## Components

```
Browser
  |
  | HTTPS
  v
Cloudflare Tunnel (optional, outbound connection)
  |
  v
OMCP Web/API (loopback listener)
  |
  +-- Authentication + authorization
  +-- Server registry
  +-- Safe file manager
  +-- Metrics/log reader
  +-- Routing adapters
  |
  v
OMCP Local Agent
  |
  +-- Process supervisor (one isolated process/session per server)
  +-- Java runtime selector
  +-- Minecraft software/version installer
  +-- Per-server directory and port allocation
  +-- Backup/restore
  |
  v
Minecraft Java server processes

Players ---> External TCP relay/provider ---> Minecraft server port
```

## No-public-IPv4 access

- Panel traffic: Cloudflare Tunnel can publish the HTTP(S) web app from an outbound tunnel.
- Game traffic: a separate TCP-capable relay/provider must forward player connections to each server port. Cloudflare Tunnel for ordinary websites is not that relay.
- The panel and game routing are independent. A working panel URL does not prove that a Minecraft server is reachable.

## Server lifecycle

- Create: allocate a unique server ID and directory; validate name, port and memory; select Java and software/version; download from a trusted official metadata source; show/record EULA acceptance; launch under the supervisor.
- Console: use a PTY or equivalent managed stdin/stdout channel. Never claim an unmanaged detached Java process can always be reattached.
- Stop: send the normal server stop command, wait for graceful exit, then offer a force-stop only after timeout and explicit confirmation.
- Import: scan only user-selected roots; show candidates; back up metadata; ask the user to stop and re-launch under OMCP to gain managed console control.
- Delete: stop first, preserve a backup, and require explicit confirmation before removing a world.

## Isolation and safety

- Each server gets a dedicated directory under the configured OMCP data root.
- Canonicalize paths and reject traversal/symlink escapes.
- Execute binaries with argument arrays; never interpolate panel input into a shell command.
- Apply per-server memory/CPU limits where supported.
- API binds to loopback by default. Authentication is mandatory before any mutating endpoint.
- No unrestricted host shell, arbitrary file path access, or unauthenticated console endpoint.

## First implementation milestones

1. API auth + local agent health.
2. Server registry and managed process lifecycle.
3. Create-server workflow and console streaming.
4. File manager, logs, metrics, backups.
5. Java/software/version management.
6. Cloudflare Tunnel onboarding.
7. TCP game-routing provider adapters.
