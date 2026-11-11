# ONION HUB

Universal Pterodactyl + Wings deployment and network-routing installer.

## Current status — foundation release

This repository currently contains a safe bootstrap, host diagnostics, and Cloudflare Pages distribution files. It is **not yet a production Pterodactyl installer**. Panel, Wings, relay provisioning, provider authentication, automatic node registration, and end-to-end Green Heart verification are not implemented in this release.

The installer deliberately does not install packages, change firewall rules, overwrite existing services, or delete data. Do not advertise this release as a one-click production deployment.

## Intended architecture

- **Direct mode:** use a public address only after independent inbound connectivity checks.
- **Routed mode:** use external routing providers for hosts without inbound connectivity.
- Cloudflare Pages hosts the installer; it is not a TCP relay.
- Cloudflare Tunnel can publish supported HTTP/HTTPS Panel traffic.
- Wings API, SFTP, and game allocations need explicitly supported TCP routing.
- Minekube Connect is for Minecraft traffic; it does not route Panel or Wings.
- A host without a public IP still needs an external relay/network provider. DNS alone cannot create inbound reachability.

## Requirements

- Bash 4+, curl, iproute2, coreutils.
- Ubuntu 24.04 LTS and Debian 12/13 are in the current diagnostic target list. This is not a claim that installation has been tested on every provider.
- Root is not required for Smart Check.

## Run safely

Review the script before running it:

```bash
curl -fsSLo onion-hub.sh https://hub.mronion.fun/install.sh
less onion-hub.sh
bash onion-hub.sh
```

This foundation release performs diagnostics only.

## Cloudflare Pages

Connect this repository to Cloudflare Pages:
- Framework preset: **None**
- Build command: `exit 0`
- Build output directory: `.`

After deployment, configure `hub.mronion.fun` under Pages → Custom domains. The installer URL will be `https://hub.mronion.fun/install.sh` once deployment and DNS are active.

## Safety

Never pipe an unreviewed remote script directly into a root shell. Keep credentials out of Git, logs, command-line arguments, and screenshots. Use provider-issued credentials and least-privilege tokens.
