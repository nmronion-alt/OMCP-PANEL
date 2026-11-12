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
USERSFILE=ROOT/"users.json"
SESSIONS={}
SESSION_LOCK=threading.RLock()
SESSION_TTL=12*60*60
PROCS={}; LOCK=threading.RLock()

def load_users():
    if not USERSFILE.exists(): return {}
    try:
        data=json.loads(USERSFILE.read_text())
        return data if isinstance(data,dict) else {}
    except Exception:
        raise RuntimeError("users.json is invalid; restore it from backup before continuing")

def save_users(users):
    tmp=USERSFILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(users,indent=2))
    os.chmod(tmp,0o600)
    tmp.replace(USERSFILE)

def password_hash(password, salt=None):
    salt=salt or secrets.token_bytes(16)
    digest=__import__("hashlib").pbkdf2_hmac("sha256",password.encode(),salt,310000)
    import base64
    return {"salt":base64.b64encode(salt).decode(),"hash":base64.b64encode(digest).decode(),"iterations":310000}

def password_ok(password, record):
    import base64, hashlib
    try:
        salt=base64.b64decode(record["salt"])
        expected=base64.b64decode(record["hash"])
        actual=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,int(record["iterations"]))
        return secrets.compare_digest(actual,expected)
    except Exception:
        return False

def new_session(username):
    token=secrets.token_urlsafe(32)
    with SESSION_LOCK: SESSIONS[token]={"username":username,"expires":time.time()+SESSION_TTL}
    return token

def session_user(handler):
    header=handler.headers.get("Authorization","")
    if not header.startswith("Bearer "): return None
    token=header[7:]
    with SESSION_LOCK:
        item=SESSIONS.get(token)
        if not item: return None
        if item["expires"]<time.time():
            SESSIONS.pop(token,None); return None
        item["expires"]=time.time()+SESSION_TTL
        return item["username"]


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
    def auth(self):
        self.username=session_user(self)
        return self.username is not None
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/api/health": return send(self,200,{"ok":True,"name":"OMCP"})
        if path=="/api/setup/status": return send(self,200,{"setupRequired":len(load_users())==0})
        if path=="/" or path=="/index.html":
            try: return send(self,200,WEB.read_bytes(),"text/html; charset=utf-8")
            except Exception: return send(self,404,{"error":"UI file missing"})
        if not self.auth(): return send(self,401,{"error":"Admin key required"})
        try:
            if path=="/api/users":
                if load_users().get(self.username,{}).get("role")!="admin": return send(self,403,{"error":"Admin permission required"})
                return send(self,200,{"users":[{"username":u,"role":v.get("role","user")} for u,v in load_users().items()]})
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
        if path in ("/api/setup","/api/login"):
            try:
                d=body(self); username=str(d.get("username","")).strip(); password=str(d.get("password",""))
                users=load_users()
                if path=="/api/setup":
                    if users: return send(self,409,{"error":"Admin account already exists"})
                    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,24}",username): raise ValueError("Username must be 3-24 characters: letters, numbers, dot, _ or -")
                    if len(password)<10 or len(password)>128: raise ValueError("Password must be 10-128 characters")
                    users[username]={"password":password_hash(password),"role":"admin","created":int(time.time())}
                    save_users(users)
                else:
                    record=users.get(username)
                    if not record or not password_ok(password,record): return send(self,401,{"error":"Incorrect username or password"})
                return send(self,200,{"token":new_session(username),"user":{"username":username,"role":users[username]["role"]}})
            except Exception as e: return send(self,400,{"error":str(e)})
        if path=="/api/logout":
            header=self.headers.get("Authorization","")
            if header.startswith("Bearer "):
                with SESSION_LOCK: SESSIONS.pop(header[7:],None)
            return send(self,200,{"ok":True})
        if not self.auth(): return send(self,401,{"error":"Login required"})
        if path=="/api/users":
            try:
                if load_users().get(self.username,{}).get("role")!="admin": return send(self,403,{"error":"Admin permission required"})
                d=body(self); username=str(d.get("username","")).strip(); password=str(d.get("password",""))
                if not re.fullmatch(r"[A-Za-z0-9_.-]{3,24}",username): raise ValueError("Username must be 3-24 characters: letters, numbers, dot, _ or -")
                if len(password)<10 or len(password)>128: raise ValueError("Password must be 10-128 characters")
                users=load_users()
                if username in users: return send(self,409,{"error":"Username already exists"})
                users[username]={"password":password_hash(password),"role":"user","created":int(time.time())}
                save_users(users)
                return send(self,201,{"user":{"username":username,"role":"user"}})
            except Exception as e: return send(self,400,{"error":str(e)})
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
        if not self.auth(): return send(self,401,{"error":"Login required"})
        path=urlparse(self.path).path
        x=re.fullmatch(r"/api/users/([A-Za-z0-9_.-]{3,24})",path)
        if not x: return send(self,404,{"error":"Not found"})
        if load_users().get(self.username,{}).get("role")!="admin": return send(self,403,{"error":"Admin permission required"})
        target=x.group(1); users=load_users()
        if target==self.username or target not in users or users[target].get("role")=="admin": return send(self,400,{"error":"Cannot remove this account"})
        users.pop(target); save_users(users)
        with SESSION_LOCK:
            for key,value in list(SESSIONS.items()):
                if value["username"]==target: SESSIONS.pop(key,None)
        return send(self,200,{"deleted":target})

print("OMCP listening at http://%s:%s"%(HOST,PORT),flush=True)
ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
