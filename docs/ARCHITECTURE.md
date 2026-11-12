# OMCP architecture

Browser -> Cloudflare Tunnel + Cloudflare Access -> localhost OMCP web/API -> local process manager -> Paper server processes.

The local agent owns server folders under `/var/lib/omcp/servers`. It binds to loopback only. The generated Admin Key is a shared admin credential, not a user-account/login system. Cloudflare Access should provide an additional external gate before exposing the panel hostname.

## MVP process model

The Python agent creates Paper server directories, downloads the latest Paper build for a selected version, records explicit EULA acceptance, and launches Java with an argument array (never a shell string). Standard input is retained for Minecraft console commands; output is written to each server's console log. The agent supports graceful stop, restart, log viewing, basic text file editing and ZIP backups.

## Networking

- Panel: Cloudflare Tunnel can publish HTTP from localhost without public IPv4; protect it with Cloudflare Access.
- Game: a separate TCP relay/provider is required for Minecraft player traffic. Ordinary Cloudflare web tunnelling does not forward arbitrary Minecraft TCP.
- The installer does not install Cloudflare Tunnel or configure a game relay.

## Security boundaries and limitations

- Run as a dedicated unprivileged `omcp` account.
- API defaults to `127.0.0.1`; do not expose port 8765 directly.
- Admin Key is required for all management endpoints.
- No host shell endpoint; process arguments are arrays.
- Per-server path validation, symlink checks and request size limits.
- Server deletion is disabled in this MVP.
- The MVP does not yet implement PTY, Java version selection, resource cgroups, Fabric/Forge, plugin catalogue, backup restore, imported servers or TCP routing adapters.
