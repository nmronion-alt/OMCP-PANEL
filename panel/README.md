# OMCP — Onion Minecraft Panel

OMCP is a single-admin web control panel for ordinary Minecraft Java servers running directly on a Linux VPS. It manages Java processes and normal server folders; it does not require Docker or systemd.

## Native development build

- Single-admin bearer-token login.
- Creates Paper servers using the official PaperMC downloads API.
- Stores worlds and server files in \`/opt/omcp/data/servers/<server-id>\`.
- Starts, stops and restarts normal Java server processes.
- Uses loopback-bound Minecraft ports and local RCON for console commands.
- Lists server files, reads/edits text files, uploads files (50 MB cap), and lists installed plugin JARs.
- EULA acceptance is required before a server is created.
- Panel runs as a background process without requiring systemd.

## Install (Ubuntu/Debian)

\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/nmronion-alt/onion-hub/minecraft-panel-foundation/panel/install.sh | sudo bash
\`\`\`

Installer prints the local panel URL and admin token. Keep the token private. Panel listens on \`127.0.0.1:8787\`.

## Routing

Publish the web UI with a Cloudflare Tunnel hostname pointing to \`http://127.0.0.1:8787\`. This is HTTP panel routing only. Normal Minecraft Java clients need a separate TCP relay or compatible network service pointed at the server's displayed local target, for example \`127.0.0.1:25565\`.

## Important limitations

- This build currently creates **Paper** servers only. Vanilla, Purpur, Fabric, Forge and NeoForge installers are not implemented yet.
- File upload supports files up to 50 MB. Text editing is limited to 2 MB.
- SFTP, automated Cloudflare configuration, relay-provider API integrations, backups, server deletion/reinstall, live resource charts and theme editor are not implemented yet.
- The panel must be kept running for web management. Minecraft processes are separate, but host policy may still stop them when a shell/container sleeps or resets.
- Cloud Shell and other ephemeral environments may lose data or kill background processes. Use a persistent VPS/disk for reliable hosting.
- Only expose the panel through a protected route (for example Cloudflare Access) and keep the admin token secret.

## Data and logs

- Server data: \`/opt/omcp/data/servers\`
- Panel log: \`/opt/omcp/panel.log\`
- Panel PID: \`/opt/omcp/panel.pid\`
