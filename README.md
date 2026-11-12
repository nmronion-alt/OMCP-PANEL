# ONION HUB

One-command Pterodactyl deployment project.

## Target workflow

1. Detect the host before making changes.
2. Install a Pterodactyl Panel and its database on a supported, persistent Linux host.
3. Install Wings and create/register its node through the Panel API.
4. Configure allocations and verify Panel-to-Wings connectivity.
5. Offer optional Panel extensions and themes only when their framework and Panel versions are compatible.
6. Select networking based on verified inbound reachability, not merely an outbound public-IP lookup.

## Supported-host policy

The first real installer target is a persistent Ubuntu/Debian VPS with root access, systemd, Docker support, sufficient resources, and control of the required DNS/network settings. KVM is the preferred virtualization type. Environments such as hosted code sandboxes are not assumed to support privileged Docker, systemd, persistent storage, or inbound game ports. The installer must stop with a clear reason when a required capability is missing.

## Networking design

- **Direct mode:** use the node's reachable public address or DNS name only after independent inbound checks. Configure the Panel, Wings API, SFTP, and game allocations separately.
- **Private/inbound-restricted mode:** publish the Panel web app through an HTTP-capable tunnel if appropriate. Wings API, SFTP, and game allocations still need a compatible TCP path that works for the Panel and end users.
- **Minekube Connect:** optional Minecraft traffic connector only. It does not replace Wings API or SFTP routing.
- **Cloudflare Tunnel:** can publish the Panel's HTTP(S) service. Its non-HTTP TCP routes require a client-side `cloudflared` connection; it is not a transparent public TCP relay for arbitrary Minecraft clients.

No relay provider is provisioned by GitHub or Cloudflare Pages. A private host cannot become publicly reachable for all protocols without a real relay/network provider and its required account/configuration.

## Panel extensions and themes

Pterodactyl 2.x has a native extension/theme system. Blueprint is a separate community framework associated with the Pterodactyl 1.x ecosystem. These paths must not be mixed. The installer must detect the exact Panel version and refuse incompatible extension/theme packages. It must back up the Panel before applying any third-party modification.

## Automatic node registration

Node creation requires privileged Panel API access and a valid location, FQDN/scheme, resource limits, daemon ports, and allocations. The installer must create or obtain a least-privilege credential securely, register the node, obtain its Wings configuration, start Wings, then verify the actual heartbeat. A successful service start alone is not a Green Heart.

## Current repository state

The current shell script is still a diagnostics/toolbox preview. It does **not** yet deploy Panel, database, Wings, create nodes, provision relays, or install Blueprint/extensions/themes. Do not advertise it as a finished one-command installer until those stages are implemented and tested on clean supported VPS images.

## Security requirements

- Never overwrite an existing Panel, database, Docker setup, or firewall policy without an explicit backup and confirmation.
- Do not put API keys, passwords, tunnel tokens, or database credentials in Git, URLs, shell history, or logs.
- Download release assets from official project sources and verify checksums/signatures where published.
- Never use a blind remote `curl | bash` root execution path for unreviewed payloads.


## Read-only preflight module

Run `bash preflight.sh` before attempting any deployment. This module checks:

- Ubuntu/Debian family, root access, and CPU architecture
- CPU, host-visible RAM, and free root filesystem space
- Whether systemd is PID 1
- Container/Kubernetes markers
- Whether the Docker daemon is actually reachable (the Docker CLI alone is not enough)
- Outbound IPv4 and visible network interfaces

The preflight is read-only: it does not install packages, alter firewall rules, create services, or touch existing Minecraft data. Exit codes: `0` = no blocking findings, `1` = conditional/warnings, `2` = blocked.

A successful preflight is not proof of inbound reachability. Direct networking must be tested from an independent network. Private networking needs an actual relay provider for each required protocol. Cloudflare Tunnel is for publishing the Panel's HTTP(S) endpoint; it does not create a general public Minecraft TCP relay.

## Current development milestone

The repository is implementing the compatibility/preflight layer first. The Panel, database, Wings deployment, node registration, routing adapters, and Green Heart verification are not yet production-ready. Do not run this repository as a production installer or expect it to create a working hosting panel yet.
