import hmac
import os
from pathlib import Path
from typing import Optional

import docker
from docker.errors import DockerException, NotFound
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

app = FastAPI(title="Minecraft Server Panel", docs_url=None, redoc_url=None)


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
    return client.containers.list(
        all=True,
        filters={"label": "managed-by=mc-panel"},
    )


@app.get("/api/health")
def health():
    return {"ok": True, "service": "minecraft-panel-api"}


@app.get("/api/status")
def status(_: bool = Depends(require_admin)):
    client = docker_client()
    containers = managed_containers(client)
    running = sum(1 for item in containers if item.status == "running")
    return {
        "docker": "connected",
        "managed_servers": len(containers),
        "running_servers": running,
    }


@app.get("/api/servers")
def servers(_: bool = Depends(require_admin)):
    client = docker_client()
    result = []
    for item in managed_containers(client):
        item.reload()
        result.append({
            "id": item.short_id,
            "name": item.name,
            "status": item.status,
            "image": item.image.tags[0] if item.image.tags else item.image.short_id,
            "created": item.attrs.get("Created"),
        })
    return {"servers": result}


@app.post("/api/servers/{server_id}/{action}")
def server_action(server_id: str, action: str, _: bool = Depends(require_admin)):
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(status_code=400, detail="Unsupported action.")
    client = docker_client()
    try:
        item = client.containers.get(server_id)
        if "mc-panel" not in item.labels or item.labels.get("managed-by") != "mc-panel":
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
        if item.labels.get("managed-by") != "mc-panel":
            raise HTTPException(status_code=404, detail="Managed server not found.")
        raw = item.logs(tail=200, timestamps=True)
        return {"logs": raw.decode("utf-8", errors="replace")}
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Server not found.") from exc
    except DockerException as exc:
        raise HTTPException(status_code=502, detail=f"Could not read logs: {exc.__class__.__name__}") from exc


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")
