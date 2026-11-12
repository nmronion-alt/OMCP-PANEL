# OMCP Local Agent

The local agent will run beside the web UI and manage Minecraft Java server processes directly. It is not Wings and does not use the Pterodactyl API.

Responsibilities:
- Maintain a registry of OMCP-managed servers.
- Create isolated server directories and install supported server software.
- Launch each server under a PTY-backed process supervisor for reliable console input/output.
- Stop/restart processes safely and report PID, exit status, CPU/RAM and logs.
- Expose a loopback-only authenticated API to the panel.
- Enforce per-server path boundaries and never expose an unrestricted shell.

An already-running unmanaged Java process may not have an attachable stdin. Import should scan user-approved directories and, where console control is needed, require a planned stop and relaunch under the OMCP supervisor.

Implementation status: design only; no working agent/API is shipped yet.
