import hmac
import os
import re
import socket
from pathlib import Path
from typing import Optional

import docker
from docker.errors import DockerException, NotFound
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
MC_IMAGE = "itzg/minecraft-server:latest"
SERVER_TYPES = {"VANILLA", "PAPER", "PURPUR", "FABRIC", "FORGE", "NEOFORGE"}
VERSION_PATTERN = re.compile(r"^(LATEST|SNAPSHOT|[1-9][0-9]?\\.[0-9]+(?:\\.[0-9]+)?)$")

app = FastAPI(title="OMCP - Onion Minecraft Panel", docs_url=None, redoc_url=None)


class ServerCreate(BaseModel):
    name: str = Field(min_length=3, max_length=32)
    version: str = Field(default="LATEST", min_length=1, max_length=20)
    server_type: str = Field(default="PAPER", min_length=1, max_length=16)
    memory_gb: int = Field(default=2, ge=1, le=16)
    eula_accepted: bool = False


def require_admin(authorization: Optional[str] = Header(default=None)):
    if not ADMIN_TOKEN or len(ADMIN_TOKEN) < 32:
        raise HTTPException(status_code=503, detail="Panel admin token is not configured securely.")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Authentication required.")
    return True


def docker_client():
    try:
        client = docker.from_env(timeout=4)
        client.ping()
        return client
    except DockerException as exc:
        raise HTTPException(status_code=503, detail=f"Docker is unavailable: {exc.__class__.__name__}") from exc


def managed_containers(client):
    return client.containers.list(all=True, filters={"label": "managed-by=omcp"})


def allocate_loopback_port():
    # Bind only to loopback: a TCP relay on this host can reach it, but the
    # Minecraft port is not exposed directly on every public host interface.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@app.get("/api/health")
def health():
    return {"ok": True, "service": "omcp-api"}


@app.get("/api/status")
def status(_: bool = Depends(require_admin)):
    client = docker_client()
    containers = managed_containers(client)
    running = sum(1 for item in containers if item.status == "running")
    return {"docker": "connected", "managed_servers": len(containers), "running_servers": running}


@app.get("/api/servers")
def servers(_: bool = Depends(require_admin)):
    client = docker_client()
    result = []
    for item in managed_containers(client):
        item.reload()
        ports = item.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
        binding = (ports.get("25565/tcp") or [{}])[0]
        result.append({
            "id": item.short_id,
            "name": item.labels.get("omcp.name", item.name),
            "status": item.status,
            "image": item.image.tags[0] if item.image.tags else item.image.short_id,
            "created": item.attrs.get("Created"),
            "host": binding.get("HostIp", "127.0.0.1"),
            "port": int(binding["HostPort"]) if binding.get("HostPort") else None,
            "version": item.labels.get("omcp.version", "unknown"),
            "server_type": item.labels.get("omcp.type", "unknown"),
        })
    return {"servers": result}


@app.post("/api/servers")
def create_server(payload: ServerCreate, _: bool = Depends(require_admin)):
    name = payload.name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{1,30}[A-Za-z0-9]", name):
        raise HTTPException(status_code=422, detail="Use 3-32 characters: letters, numbers, spaces, _ or -; start and end with a letter or number.")
    if not payload.eula_accepted:
        raise HTTPException(status_code=400, detail="You must confirm the Minecraft EULA before creating a server.")
    version = payload.version.strip().upper()
    server_type = payload.server_type.strip().upper()
    if not VERSION_PATTERN.fullmatch(version):
        raise HTTPException(status_code=422, detail="Version must be LATEST, SNAPSHOT, or a version such as 1.21.11.")
    if server_type not in SERVER_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported server type.")

    client = docker_client()
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    container_name = f"omcp-{slug}"
    try:
        client.containers.get(container_name)
        raise HTTPException(status_code=409, detail="A server with that name already exists.")
    except NotFound:
        pass

    port = allocate_loopback_port()
    volume_name = f"omcp-data-{slug}"
    volume = None
    try:
        volume = client.volumes.create(name=volume_name, labels={"managed-by": "omcp", "omcp.server": slug})
        container = client.containers.run(
            MC_IMAGE,
            name=container_name,
            detach=True,
            labels={
                "managed-by": "omcp",
                "omcp.name": name,
                "omcp.version": version,
                "omcp.type": server_type,
            },
            environment={
                "EULA": "TRUE",
                "TYPE": server_type,
                "VERSION": version,
                "MEMORY": f"{payload.memory_gb}G",
                "TZ": "Asia/Kolkata",
                "MOTD": f"{name} - hosted by OMCP",
            },
            ports={"25565/tcp": ("127.0.0.1", port)},
            volumes={volume.name: {"bind": "/data", "mode": "rw"}},
            mem_limit=f"{payload.memory_gb + 1}g",
            nano_cpus=2_000_000_000,
            init=True,
            restart_policy={"Name": "unless-stopped"},
        )
        container.reload()
        return {
            "id": container.short_id,
            "name": name,
            "status": container.status,
            "host": "127.0.0.1",
            "port": port,
            "target": f"127.0.0.1:{port}",
            "volume": volume_name,
            "message": "Server container created. The first boot may take a few minutes while the server files download.",
        }
    except HTTPException:
        raise
    except DockerException as exc:
        if volume is not None:
            try:
                volume.remove(force=True)
            except DockerException:
                pass
        raise HTTPException(status_code=502, detail=f"Could not create Minecraft server: {exc.__class__.__name__}") from exc


@app.post("/api/servers/{server_id}/{action}")
def server_action(server_id: str, action: str, _: bool = Depends(require_admin)):
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(status_code=400, detail="Unsupported action.")
    client = docker_client()
    try:
        item = client.containers.get(server_id)
        if item.labels.get("managed-by") != "omcp":
            raise HTTPException(status_code=404, detail="Managed server not found.")
        getattr(item, action)()
        item.reload()
        return {"id": item.short_id, "status": item.status, "action": action}
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Server not found.") from exc
    except DockerException as exc:
        raise HTTPException(status_code=502, detail=f"Docker action failed: {exc.__class__.__name__}") from exc


@app.get("/api/servers/{server_id}/logs")
def server_logs(server_id: str, _: bool = Depends(require_admin)):
    client = docker_client()
    try:
        item = client.containers.get(server_id)
        if item.labels.get("managed-by") != "omcp":
            raise HTTPException(status_code=404, detail="Managed server not found.")
        raw = item.logs(tail=250, timestamps=True)
        return {"logs": raw.decode("utf-8", errors="replace")}
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Server not found.") from exc
    except DockerException as exc:
        raise HTTPException(status_code=502, detail=f"Could not read logs: {exc.__class__.__name__}") from exc


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")
