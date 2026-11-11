# ONION HUB — Panel & Wings Toolkit

A modular toolkit for Pterodactyl Panel, Wings, Blueprint extensions and network diagnostics.

## Current release: 0.3.0-panel-themes-preview

The interactive Bash menu now includes:
- Smart Check: OS, kernel, virtualization, CPU, RAM, disk, systemd, Docker and basic network diagnostics.
- Panel & Wings service detection (read-only).
- Routing diagnostics (read-only).
- Purple terminal interface (visual styling only; not a Pterodactyl Panel theme).
- Panel Themes section: checks for a Pterodactyl installation and Blueprint CLI; theme installation is not enabled in this preview.
- VPS toolbox: uptime, memory, disk, listening TCP ports and Docker container listing.
- Explicit status for modules that are not implemented yet.

## Important status

This is an **interactive diagnostics/toolbox preview**, not yet a production Pterodactyl or Blueprint theme installer. Panel/database deployment, Wings installation and secure registration, Blueprint installation, third-party theme installation, external relay provisioning, routing provider authentication, game-port forwarding, and real Green Heart verification are not implemented.

The script does not install packages, install Panel themes or Blueprint extensions, change firewall rules, overwrite services, store tunnel credentials, or delete user data. Menu items marked as planned are not functional installation modules yet.

## Panel theme plan

The Panel Themes menu is for the web dashboard, not terminal colors. Pterodactyl 2.0 has a native theme system; Pterodactyl 1.x commonly uses community tools such as Blueprint for extensions and themes. These are different paths and must not be mixed. This preview only detects a likely Panel directory and whether the Blueprint CLI is available. It does not install Blueprint or download/apply a theme. A future installer must detect the Panel version, check the selected theme's compatibility and source, create a backup, and ask for confirmation before changing Panel files.

## Intended networking architecture

- Direct mode is allowed only after inbound reachability is independently verified.
- Cloudflare Pages distributes the installer; it is not a TCP relay.
- Cloudflare Tunnel can publish supported HTTP/HTTPS Panel traffic.
- Wings API, SFTP and game allocations need compatible TCP routing and externally reachable ports.
- Minekube Connect is for Minecraft traffic, not Panel or Wings.
- A host without public inbound connectivity still requires an external relay/network provider.

## Run safely

Review before running. Do not pipe an unreviewed remote script directly into a root shell:

```bash
curl -fsSLo onion-hub.sh https://hub.mronion.fun/install.sh
less onion-hub.sh
bash onion-hub.sh
```

Smart Check and toolbox options do not require root in normal configurations.

## Cloudflare Pages

Connect this repository to Cloudflare Pages:
- Framework preset: **None**
- Build command: `exit 0`
- Build output directory: `.`

After custom domain activation, the script URL is intended to be:
`https://hub.mronion.fun/install.sh`

## Safety

Keep provider credentials out of Git, shell history, logs and screenshots. Use provider-issued credentials with least privilege. Verify every remote payload before execution.
