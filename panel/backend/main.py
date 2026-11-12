from __future__ import annotations
import hmac, json, os, re, secrets, shutil, socket, struct, subprocess, time, urllib.error, urllib.request
from pathlib import Path
from typing import Optional
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR=Path(__file__).resolve().parent
FRONTEND_DIR=BASE_DIR.parent/"frontend"
DATA_DIR=Path(os.environ.get("OMCP_DATA_DIR","/opt/omcp/data")).resolve()
SERVERS_DIR=DATA_DIR/"servers"
ADMIN_TOKEN=os.environ.get("ADMIN_TOKEN","")
VERSION_PATTERN=re.compile(r"^1\.[0-9]{1,2}(?:\.[0-9]{1,2})?$")
ID_PATTERN=re.compile(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")
MAX_UPLOAD=50*1024*1024
app=FastAPI(title="OMCP - Onion Minecraft Panel",docs_url=None,redoc_url=None)
SERVERS_DIR.mkdir(parents=True,exist_ok=True)

class ServerCreate(BaseModel):
    name:str=Field(min_length=3,max_length=32)
    version:str=Field(min_length=3,max_length=20)
    server_type:str=Field(default="PAPER")
    memory_gb:int=Field(default=2,ge=1,le=32)
    eula_accepted:bool=False
class ConsoleInput(BaseModel):
    command:str=Field(min_length=1,max_length=256)
class FileWrite(BaseModel):
    content:str=Field(max_length=2_000_000)

def require_admin(authorization:Optional[str]=Header(default=None)):
    if not ADMIN_TOKEN or len(ADMIN_TOKEN)<32: raise HTTPException(503,"Admin token is not configured securely.")
    scheme,_,supplied=(authorization or "").partition(" ")
    if scheme.lower()!="bearer" or not hmac.compare_digest(supplied,ADMIN_TOKEN): raise HTTPException(401,"Authentication required.")
    return True
def safe_id(server_id:str)->str:
    if not ID_PATTERN.fullmatch(server_id): raise HTTPException(404,"Server not found.")
    return server_id
def server_dir(server_id:str)->Path:
    path=(SERVERS_DIR/safe_id(server_id)).resolve()
    if path.parent!=SERVERS_DIR: raise HTTPException(400,"Invalid server path.")
    if not path.is_dir(): raise HTTPException(404,"Server not found.")
    return path
def metadata(directory:Path)->dict:
    try: return json.loads((directory/"omcp.json").read_text())
    except (OSError,ValueError): raise HTTPException(500,"Server metadata is missing or damaged.")
def save_meta(directory:Path,data:dict):
    temp=directory/"omcp.json.tmp"; temp.write_text(json.dumps(data,indent=2)); temp.replace(directory/"omcp.json")
def allocate_port()->int:
    with socket.socket() as sock: sock.bind(("127.0.0.1",0)); return int(sock.getsockname()[1])
def is_running(directory:Path,meta:dict)->bool:
    pid=meta.get("pid")
    if not isinstance(pid,int) or pid<2: return False
    try:
        proc=Path(f"/proc/{pid}")
        return proc.joinpath("cwd").resolve()==directory.resolve() and b"server.jar" in proc.joinpath("cmdline").read_bytes()
    except OSError:
        return False
def configure_properties(directory:Path,meta:dict):
    props=directory/"server.properties"; current={}
    if props.exists():
        for line in props.read_text(errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key,value=line.split("=",1); current[key]=value
    current.update({"server-port":str(meta["port"]),"server-ip":"127.0.0.1","enable-rcon":"true","rcon.port":str(meta["rcon_port"]),"rcon.password":meta["rcon_password"],"broadcast-rcon-to-ops":"false"})
    props.write_text("\n".join(f"{k}={v}" for k,v in current.items())+"\n")
def rcon(directory:Path,meta:dict,command:str)->str:
    def packet(sock,request_id,packet_type,payload):
        body=struct.pack("<ii",request_id,packet_type)+payload.encode()+b"\x00\x00"
        sock.sendall(struct.pack("<i",len(body))+body)
        size=struct.unpack("<i",sock.recv(4))[0]; data=b""
        while len(data)<size:
            chunk=sock.recv(size-len(data))
            if not chunk: break
            data+=chunk
        if len(data)<8: raise OSError("Invalid RCON response")
        return struct.unpack("<ii",data[:8]),data[8:-2].decode(errors="replace")
    with socket.create_connection(("127.0.0.1",int(meta["rcon_port"])),timeout=3) as sock:
        sock.settimeout(3); auth,_=packet(sock,11,3,meta["rcon_password"])
        if auth[0]==-1: raise OSError("RCON authentication failed")
        _,output=packet(sock,12,2,command); return output
def paper_download(version:str,destination:Path)->str:
    base="https://api.papermc.io/v2/projects/paper"
    def get_json(url):
        req=urllib.request.Request(url,headers={"User-Agent":"OMCP/0.2"})
        with urllib.request.urlopen(req,timeout=30) as response: return json.loads(response.read())
    try:
        versions=get_json(base)["versions"]
        if version not in versions: raise HTTPException(400,"That Paper version is not available from the official Paper API.")
        builds=get_json(f"{base}/versions/{version}")["builds"]
        if not builds: raise HTTPException(502,"No Paper builds are published for this version.")
        build=builds[-1]; info=get_json(f"{base}/versions/{version}/builds/{build}")
        name=info["downloads"]["application"]["name"]; url=f"{base}/versions/{version}/builds/{build}/downloads/{name}"
        req=urllib.request.Request(url,headers={"User-Agent":"OMCP/0.2"})
        with urllib.request.urlopen(req,timeout=180) as response,destination.open("wb") as out: shutil.copyfileobj(response,out)
        if destination.stat().st_size<1_000_000:
            destination.unlink(missing_ok=True); raise HTTPException(502,"Downloaded Paper JAR failed its size check.")
        return f"Paper {version} build {build}"
    except HTTPException: raise
    except (urllib.error.URLError,TimeoutError,KeyError,ValueError,OSError) as exc:
        destination.unlink(missing_ok=True); raise HTTPException(502,f"Paper download failed: {type(exc).__name__}") from exc

@app.get("/api/health")
def health(): return {"ok":True,"service":"omcp-native"}
@app.get("/api/status")
def status(_:bool=Depends(require_admin)):
    entries=[p for p in SERVERS_DIR.iterdir() if p.is_dir() and (p/"omcp.json").exists()]
    running=sum(1 for p in entries if is_running(p,metadata(p)))
    return {"mode":"native","managed_servers":len(entries),"running_servers":running,"data_dir":str(DATA_DIR)}
@app.get("/api/servers")
def servers(_:bool=Depends(require_admin)):
    result=[]
    for directory in sorted(SERVERS_DIR.iterdir()):
        if not directory.is_dir() or not (directory/"omcp.json").exists(): continue
        meta=metadata(directory); result.append({"id":directory.name,"name":meta["name"],"status":"running" if is_running(directory,meta) else "stopped","version":meta["version"],"server_type":meta["server_type"],"host":"127.0.0.1","port":meta["port"],"target":f"127.0.0.1:{meta['port']}","memory_gb":meta["memory_gb"]})
    return {"servers":result}
@app.post("/api/servers")
def create_server(payload:ServerCreate,_:bool=Depends(require_admin)):
    name=payload.name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{1,30}[A-Za-z0-9]",name): raise HTTPException(422,"Use 3-32 letters, numbers, spaces, _ or -.")
    if not payload.eula_accepted: raise HTTPException(400,"You must accept the Minecraft EULA first.")
    version=payload.version.strip()
    if not VERSION_PATTERN.fullmatch(version): raise HTTPException(422,"Enter a release version such as 1.21.11.")
    if payload.server_type.strip().upper()!="PAPER": raise HTTPException(400,"This native build currently supports Paper only. Other software installers are not ready yet.")
    slug=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")[:32].strip("-")
    if not slug: raise HTTPException(422,"Choose a valid server name.")
    target=SERVERS_DIR/slug
    if target.exists(): raise HTTPException(409,"A server with this name already exists.")
    target.mkdir(mode=0o750)
    try:
        info=paper_download(version,target/"server.jar")
        meta={"name":name,"version":version,"server_type":"PAPER","memory_gb":payload.memory_gb,"port":allocate_port(),"rcon_port":allocate_port(),"rcon_password":secrets.token_urlsafe(24),"pid":None,"created_at":int(time.time()),"software_info":info}
        save_meta(target,meta); (target/"eula.txt").write_text("eula=true\n"); configure_properties(target,meta)
        return {"id":slug,"name":name,"status":"stopped","target":f"127.0.0.1:{meta['port']}","message":f"{info} downloaded. Start the server when ready."}
    except Exception: shutil.rmtree(target,ignore_errors=True); raise
@app.post("/api/servers/{server_id}/actions/{action}")
def server_action(server_id:str,action:str,_:bool=Depends(require_admin)):
    if action not in {"start","stop","restart"}: raise HTTPException(400,"Unsupported action.")
    directory=server_dir(server_id); meta=metadata(directory); running=is_running(directory,meta)
    if action=="start" and running: return {"id":server_id,"status":"running","action":action}
    if action=="stop" and not running: return {"id":server_id,"status":"stopped","action":action}
    if action in {"stop","restart"} and running:
        try: rcon(directory,meta,"stop")
        except OSError:
            try: os.kill(int(meta["pid"]),15)
            except OSError: pass
        for _ in range(30):
            if not is_running(directory,meta): break
            time.sleep(1)
        if is_running(directory,meta): raise HTTPException(504,"Server did not stop in 30 seconds.")
        meta["pid"]=None; save_meta(directory,meta)
    if action in {"start","restart"}:
        if not (directory/"eula.txt").exists() or "eula=true" not in (directory/"eula.txt").read_text().lower(): raise HTTPException(400,"Minecraft EULA has not been accepted.")
        log=(directory/"server.log").open("ab",buffering=0)
        command=["java",f"-Xms{meta['memory_gb']}G",f"-Xmx{meta['memory_gb']}G","-jar","server.jar","--nogui"]
        try: proc=subprocess.Popen(command,cwd=directory,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,shell=False,start_new_session=True,close_fds=True)
        except OSError as exc:
            log.close(); raise HTTPException(500,f"Could not start Java server: {exc}") from exc
        meta["pid"]=proc.pid; save_meta(directory,meta)
        return {"id":server_id,"status":"starting","action":action,"pid":proc.pid}
    return {"id":server_id,"status":"stopped","action":action}
@app.post("/api/servers/{server_id}/console")
def server_console(server_id:str,payload:ConsoleInput,_:bool=Depends(require_admin)):
    directory=server_dir(server_id); meta=metadata(directory)
    if not is_running(directory,meta): raise HTTPException(409,"Start the server before sending console commands.")
    command=payload.command.strip().lstrip("/")
    if not command or any(c in command for c in "\r\n\x00"): raise HTTPException(422,"Enter one command on a single line.")
    try: return {"output":rcon(directory,meta,command) or "Command sent."}
    except OSError as exc: raise HTTPException(502,f"RCON error: {exc}") from exc
@app.get("/api/servers/{server_id}/logs")
def server_logs(server_id:str,_:bool=Depends(require_admin)):
    path=server_dir(server_id)/"server.log"
    if not path.exists(): return {"logs":""}
    with path.open("rb") as stream:
        stream.seek(0,os.SEEK_END); size=stream.tell(); stream.seek(max(0,size-60000)); raw=stream.read().decode("utf-8",errors="replace")
    return {"logs":raw[-60000:]}
def resolve_file(directory:Path,relative:str)->Path:
    if not relative or "\x00" in relative: raise HTTPException(400,"Invalid file path.")
    candidate=(directory/relative).resolve()
    if candidate!=directory and directory not in candidate.parents: raise HTTPException(400,"Path escapes the server directory.")
    if candidate.is_symlink(): raise HTTPException(400,"Symbolic links are not supported.")
    return candidate
@app.get("/api/servers/{server_id}/files")
def list_files(server_id:str,path:str="",_:bool=Depends(require_admin)):
    directory=server_dir(server_id); target=resolve_file(directory,path) if path else directory
    if not target.exists() or not target.is_dir(): raise HTTPException(404,"Directory not found.")
    items=[]
    for item in sorted(target.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower())):
        if item.name=="omcp.json" or item.is_symlink(): continue
        stat=item.stat(); items.append({"name":item.name,"directory":item.is_dir(),"size":stat.st_size if item.is_file() else None})
    return {"path":path,"items":items}
@app.get("/api/servers/{server_id}/file")
def read_file(server_id:str,path:str,_:bool=Depends(require_admin)):
    target=resolve_file(server_dir(server_id),path)
    if not target.is_file() or target.stat().st_size>2_000_000: raise HTTPException(400,"File is missing, not regular, or larger than 2 MB.")
    return {"path":path,"content":target.read_text(errors="replace")}
@app.put("/api/servers/{server_id}/file")
def write_file(server_id:str,path:str,payload:FileWrite,_:bool=Depends(require_admin)):
    directory=server_dir(server_id); target=resolve_file(directory,path)
    if target.name=="omcp.json": raise HTTPException(403,"Protected OMCP metadata.")
    target.parent.mkdir(parents=True,exist_ok=True); target.write_text(payload.content); return {"saved":True,"path":path}
@app.post("/api/servers/{server_id}/upload")
async def upload_file(server_id:str,path:str="",file:UploadFile=File(...),_:bool=Depends(require_admin)):
    directory=server_dir(server_id); folder=resolve_file(directory,path) if path else directory
    if not folder.is_dir(): raise HTTPException(404,"Upload directory not found.")
    filename=Path(file.filename or "").name
    if not filename or filename in {".",".."} or filename=="omcp.json": raise HTTPException(400,"Invalid upload filename.")
    destination=resolve_file(directory,str(Path(path)/filename) if path else filename); total=0
    with destination.open("wb") as out:
        while chunk:=await file.read(1024*1024):
            total+=len(chunk)
            if total>MAX_UPLOAD:
                out.close(); destination.unlink(missing_ok=True); raise HTTPException(413,"Maximum upload size is 50 MB.")
            out.write(chunk)
    return {"uploaded":filename,"size":total}
@app.get("/api/servers/{server_id}/plugins")
def plugins(server_id:str,_:bool=Depends(require_admin)):
    directory=server_dir(server_id)/"plugins"
    if not directory.exists(): return {"plugins":[]}
    return {"plugins":[{"name":p.name,"size":p.stat().st_size} for p in sorted(directory.glob("*.jar")) if p.is_file() and not p.is_symlink()]}
@app.get("/")
def index(): return FileResponse(FRONTEND_DIR/"index.html")
app.mount("/assets",StaticFiles(directory=FRONTEND_DIR),name="assets")
