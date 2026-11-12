#!/usr/bin/env python3
import json, os, re, secrets, shutil, subprocess, threading, urllib.request, zipfile, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT=Path(os.environ.get("OMCP_DATA","/var/lib/omcp")).resolve()
SERVERS=ROOT/"servers"; CFGFILE=ROOT/"config.json"
WEB=Path(os.environ.get("OMCP_WEB","/opt/omcp/index.html"))
HOST=os.environ.get("OMCP_HOST","127.0.0.1"); PORT=int(os.environ.get("OMCP_PORT","8765"))
ROOT.mkdir(parents=True,exist_ok=True); SERVERS.mkdir(parents=True,exist_ok=True)
if not CFGFILE.exists():
    token=secrets.token_urlsafe(32); CFGFILE.write_text(json.dumps({"token":token})); os.chmod(CFGFILE,0o600)
    print("\nOMCP FIRST-RUN ADMIN KEY (save this):\n"+token+"\n",flush=True)
TOKEN=json.loads(CFGFILE.read_text())["token"]
PROCS={}; LOCK=threading.RLock()

def safe_dir(sid):
    if not re.fullmatch(r"[a-f0-9]{8}",sid or ""): raise ValueError("Invalid server id")
    p=(SERVERS/sid).resolve()
    if p.parent!=SERVERS.resolve(): raise ValueError("Unsafe path")
    return p

def servers():
    out=[]
    for p in SERVERS.iterdir():
        if p.is_dir() and re.fullmatch(r"[a-f0-9]{8}",p.name) and (p/"omcp.json").exists():
            m=json.loads((p/"omcp.json").read_text()); proc=PROCS.get(p.name)
            out.append({"id":p.name,"name":m["name"],"version":m["version"],"memory":m["memory"],"port":m["port"],"status":"running" if proc and proc.poll() is None else "stopped"})
    return out

def create(d):
    name=str(d.get("name","")).strip(); ver=str(d.get("version","")).strip()
    mem=int(d.get("memory",2)); port=int(d.get("port",25565))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,23}",name): raise ValueError("Name must be 2-24 letters, numbers, _ or -")
    if not re.fullmatch(r"\d{1,2}\.\d{1,2}(?:\.\d{1,2})?",ver): raise ValueError("Invalid Minecraft version")
    if not 1<=mem<=64 or not 1024<=port<=65535: raise ValueError("RAM must be 1-64 GB; port 1024-65535")
    if not d.get("eulaAccepted"): raise ValueError("Accept the Minecraft EULA first")
    if not shutil.which("java"): raise ValueError("Install a compatible Java runtime first")
    if any(s["name"].lower()==name.lower() or s["port"]==port for s in servers()): raise ValueError("Name or port already used")
    sid=secrets.token_hex(4); folder=safe_dir(sid); folder.mkdir(mode=0o750)
    try:
        api=f"https://api.papermc.io/v2/projects/paper/versions/{ver}/builds"
        req=urllib.request.Request(api,headers={"User-Agent":"OMCP/0.1"})
        with urllib.request.urlopen(req,timeout=30) as r: builds=json.load(r)["builds"]
        if not builds: raise ValueError("No Paper build for this version")
        b=builds[-1]["build"]; jar=f"paper-{ver}-{b}.jar"
        url=f"https://api.papermc.io/v2/projects/paper/versions/{ver}/builds/{b}/downloads/{jar}"
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"OMCP/0.1"}),timeout=120) as r:
            with (folder/"paper.jar").open("wb") as f: shutil.copyfileobj(r,f)
        (folder/"eula.txt").write_text("eula=true\n")
        (folder/"server.properties").write_text(f"server-port={port}\n")
        (folder/"omcp.json").write_text(json.dumps({"name":name,"version":ver,"memory":mem,"port":port},indent=2))
        return next(s for s in servers() if s["id"]==sid)
    except Exception: shutil.rmtree(folder,ignore_errors=True); raise

def start(sid):
    folder=safe_dir(sid); m=json.loads((folder/"omcp.json").read_text())
    p=PROCS.get(sid)
    if p and p.poll() is None: raise ValueError("Already running")
    java=shutil.which("java")
    if not java: raise ValueError("Java not installed")
    log=(folder/"console.log").open("ab",buffering=0)
    p=subprocess.Popen([java,f"-Xms1G",f"-Xmx{m['memory']}G","-jar","paper.jar","nogui"],cwd=folder,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    PROCS[sid]=p
    return {"status":"starting","pid":p.pid}

def stop(sid):
    p=PROCS.get(sid)
    if not p or p.poll() is not None: return {"status":"stopped"}
    try: p.stdin.write(b"stop\n"); p.stdin.flush()
    except Exception: pass
    try: p.wait(timeout=40)
    except subprocess.TimeoutExpired: p.terminate()
    return {"status":"stopped"}

def body(h):
    n=int(h.headers.get("Content-Length","0"))
    if n>1048576: raise ValueError("Request too large")
    return json.loads(h.rfile.read(n) or b"{}")

def send(h,code,obj,typ="application/json; charset=utf-8"):
    raw=obj if isinstance(obj,bytes) else json.dumps(obj).encode()
    h.send_response(code); h.send_header("Content-Type",typ); h.send_header("Cache-Control","no-store")
    h.send_header("X-Content-Type-Options","nosniff"); h.send_header("Content-Length",str(len(raw))); h.end_headers(); h.wfile.write(raw)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args): print(fmt%args,flush=True)
    def auth(self): return secrets.compare_digest(self.headers.get("Authorization",""),"Bearer "+TOKEN)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/api/health": return send(self,200,{"ok":True,"name":"OMCP"})
        if path=="/" or path=="/index.html":
            try: return send(self,200,WEB.read_bytes(),"text/html; charset=utf-8")
            except Exception: return send(self,404,{"error":"UI file missing"})
        if not self.auth(): return send(self,401,{"error":"Admin key required"})
        try:
            if path=="/api/servers": return send(self,200,{"servers":servers()})
            if path=="/api/metrics":
                m={}
                for line in Path("/proc/meminfo").read_text().splitlines():
                    k,v=line.split(":",1); m[k]=int(v.strip().split()[0])*1024
                total=m.get("MemTotal",0); used=total-m.get("MemAvailable",0)
                return send(self,200,{"memoryTotal":total,"memoryUsed":used,"cpuCount":os.cpu_count() or 1})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/logs",path)
            if x:
                f=safe_dir(x.group(1))/"console.log"
                return send(self,200,{"logs":f.read_text(errors="replace")[-20000:] if f.exists() else ""})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/files",path)
            if x:
                folder=safe_dir(x.group(1)); rel=self.headers.get("X-OMCP-Path","")
                f=(folder/rel).resolve()
                if folder not in f.parents and f!=folder: raise ValueError("Path outside server")
                if f.is_symlink(): raise ValueError("Symlink blocked")
                if f.is_dir(): return send(self,200,{"entries":[{"name":a.name,"directory":a.is_dir(),"size":a.stat().st_size if a.is_file() else 0} for a in sorted(f.iterdir()) if not a.is_symlink()]})
                if f.is_file() and f.stat().st_size<500000: return send(self,200,{"content":f.read_text(errors="replace")})
                raise ValueError("File not found or too large")
            return send(self,404,{"error":"Not found"})
        except Exception as e: return send(self,400,{"error":str(e)})
    def do_POST(self):
        path=urlparse(self.path).path
        if path=="/api/auth/check":
            try:
                ok=secrets.compare_digest(str(body(self).get("token","")),TOKEN)
                return send(self,200 if ok else 401,{"ok":ok})
            except Exception as e: return send(self,400,{"error":str(e)})
        if not self.auth(): return send(self,401,{"error":"Admin key required"})
        try:
            d=body(self)
            if path=="/api/servers": return send(self,201,{"server":create(d)})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/(start|stop|restart|command|backup)",path)
            if x:
                sid,act=x.groups()
                if act=="start": result=start(sid)
                elif act=="stop": result=stop(sid)
                elif act=="restart": stop(sid); result=start(sid)
                elif act=="command":
                    p=PROCS.get(sid); cmd=str(d.get("command",""))
                    if not p or p.poll() is not None: raise ValueError("Server stopped")
                    if not cmd or len(cmd)>500 or "\n" in cmd or "\r" in cmd: raise ValueError("Invalid command")
                    p.stdin.write(cmd.encode()+b"\n"); p.stdin.flush(); result={"sent":True}
                else:
                    folder=safe_dir(sid); dest=ROOT/"backups"; dest.mkdir(exist_ok=True)
                    zpath=dest/(sid+"-"+time.strftime("%Y%m%d-%H%M%S")+".zip")
                    with zipfile.ZipFile(zpath,"w",zipfile.ZIP_DEFLATED) as z:
                        for f in folder.rglob("*"):
                            if f.is_file() and not f.is_symlink(): z.write(f,f.relative_to(folder))
                    result={"backup":zpath.name,"bytes":zpath.stat().st_size}
                return send(self,200,result)
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/files",path)
            if x:
                folder=safe_dir(x.group(1)); f=(folder/str(d.get("path",""))).resolve()
                if folder not in f.parents or f.is_symlink(): raise ValueError("Unsafe path")
                content=str(d.get("content",""))
                if len(content)>500000: raise ValueError("File too large")
                f.parent.mkdir(parents=True,exist_ok=True); f.write_text(content)
                return send(self,200,{"saved":True})
            return send(self,404,{"error":"Not found"})
        except Exception as e: return send(self,400,{"error":str(e)})
    def do_DELETE(self):
        if not self.auth(): return send(self,401,{"error":"Admin key required"})
        return send(self,405,{"error":"Deletion disabled in MVP; back up before manual removal"})

print("OMCP listening at http://%s:%s"%(HOST,PORT),flush=True)
ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
