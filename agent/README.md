# OMCP local agent

`omcp_agent.py` is the functional first MVP of the local agent.

- Python standard library only.
- Loopback API listener by default: `127.0.0.1:8765`.
- Generates a random Admin Key on first run and stores it in `/var/lib/omcp/config.json` with restrictive file permissions; the key is printed once in service logs for initial setup.
- Creates Paper server directories and downloads the selected Paper build.
- Start, stop, restart, console commands and recent log viewing.
- Basic text file list/read/write and ZIP backup.
- Launches Java with argument arrays rather than a shell command.
- Runs as a dedicated unprivileged `omcp` account when installed with the supplied installer.

This is an MVP, not a fully production-hardened hosting platform. Keep the API private behind Cloudflare Access, test on a disposable host and maintain external backups. PTY, imported servers, Fabric/Forge, plugin manager, resource quotas, backup restore and TCP routing adapters are not implemented yet.
