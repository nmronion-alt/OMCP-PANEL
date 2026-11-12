# ONION HUB

**ONION HUB** is the one-command installer and deployment orchestrator. It prepares **OMCP — Onion Minecraft Panel** and its Minecraft hosting infrastructure.

## Intended result

Run ONION HUB on a compatible Linux host. After setup, open OMCP in a browser and create the first Minecraft server from the panel. More servers can be created later from the same panel.

## Deployment modes

### Public-IP host
- Install the panel stack (Pterodactyl-based Panel + database + Wings).
- Configure DNS/TLS and the node.
- Configure allocations and verify the real Panel ↔ Wings heartbeat.
- Create Minecraft servers from OMCP.

### No-public-IP / inbound-restricted host
- Publish the panel's HTTP(S) endpoint through Cloudflare Tunnel.
- Configure Wings API, SFTP and Minecraft game traffic through separately supported TCP routing.
- Use Minekube Connect for Minecraft traffic where supported; it does not route the Panel, Wings API or SFTP.
- Verify every route and the actual node heartbeat before reporting success.

Cloudflare Tunnel can publish the web panel, but it is not a transparent public TCP relay for arbitrary Minecraft clients. GitHub and Cloudflare Pages distribute code/pages; they do not provide a general-purpose TCP relay. A private host therefore needs a real routing provider and its required account/configuration for each TCP service.

## Host compatibility

The installer should detect capabilities rather than assume every environment is identical. Standard Pterodactyl Wings deployment requires a supported Linux host, Docker daemon, systemd/service supervision, persistent storage, and adequate resources. A shell/container environment may run a Java process but still be unsuitable for a persistent Wings node. Cloud Shell sessions can be temporary and must not be presented as permanent hosting.

The installer must distinguish:
- Minecraft process/runtime capability
- Panel deployment capability
- Wings/Docker capability
- inbound networking and external relay capability

A public outbound IP lookup is not proof that inbound ports are reachable.

## Safety and reliability
- Never overwrite existing Panel, database, Docker, Minecraft worlds, or firewall rules without backup and explicit confirmation.
- Detect existing Minecraft servers, but ask which directory/process to adopt when multiple candidates exist.
- Create additional servers from OMCP using isolated directories and configurable Java/RAM/ports.
- Never claim a node is online because a service merely started; verify the real heartbeat.
- Never store API keys, passwords, tunnel tokens or database credentials in Git, URLs, shell history or logs.
- Download components from official sources and verify published checksums/signatures.
- Do not execute unreviewed remote scripts as root.

## Repository status

This repository is an early foundation, **not yet a production installer**. The current install.sh performs compatibility checks only; it does not yet deploy Panel, database, Wings, routing providers, node registration, or OMCP server-creation features. Do not use it as a production deployment command until those modules are implemented and tested on clean supported hosts.

## Development focus

1. Host capability detection and safe preflight.
2. Public-IP Panel + database + Wings deployment.
3. Private-host Panel tunnel and supported TCP routing adapters.
4. Automatic node setup and real heartbeat verification.
5. OMCP branding/dashboard and server creation workflow.
6. Backup, rollback, upgrade and uninstall flows.
