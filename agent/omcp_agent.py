#!/usr/bin/env python3
import base64, json, os, re, secrets, shutil, subprocess, threading, urllib.request, urllib.error, zipfile, time, socket, posixpath, stat, errno, tarfile, platform
try:
    import paramiko
except ImportError:
    paramiko=None
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote, urlencode

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
TUNNELS={}; TUNNEL_LOCK=threading.RLock(); METRIC_PREV={}; MINEKUBE_STATE={}

def load_users():
    if not USERSFILE.exists(): return {}
    try:
        data=json.loads(USERSFILE.read_text())
        return data if isinstance(data,dict) else {}
    except Exception:
        raise RuntimeError("users.json is invalid; restore it from backup before continuing")

def atomic_json(path, data):
    path=Path(path)
    tmp=path.with_name(path.name+".tmp")
    tmp.write_text(json.dumps(data,indent=2),encoding="utf-8")
    os.replace(tmp,path)

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

SFTP_PORT=int(os.environ.get("OMCP_SFTP_PORT","2022"))
SFTP_STATE={"available":False,"status":"starting","error":"","fingerprint":""}
SFTP_HOST_KEY=ROOT/"sftp_host_rsa"

if paramiko:
    class OMCPSSFTPAuth(paramiko.ServerInterface):
        def __init__(self): self.sid=None
        def check_channel_request(self,kind,chanid):
            return paramiko.OPEN_SUCCEEDED if kind=="session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        def get_allowed_auths(self,username): return "password"
        def check_auth_password(self,username,password):
            m=re.fullmatch(r"omcp-([a-f0-9]{8})",str(username))
            if not m: return paramiko.AUTH_FAILED
            sid=m.group(1)
            try:
                meta=json.loads((safe_dir(sid)/"omcp.json").read_text())
                record=meta.get("sftp",{}).get("password_hash")
                if not record or not password_ok(password,record): return paramiko.AUTH_FAILED
            except Exception: return paramiko.AUTH_FAILED
            self.sid=sid
            return paramiko.AUTH_SUCCESSFUL

    class OMCPSSFTPInterface(paramiko.SFTPServerInterface):
        def __init__(self,server,*args,**kwargs):
            super().__init__(server,*args,**kwargs)
            self.root=safe_dir(server.sid).resolve()
        def _path(self,path):
            raw=str(path or "/").replace("\\","/")
            parts=[]
            for part in raw.split("/"):
                if part in ("","."): continue
                if part=="..": raise PermissionError("Parent-directory access is blocked")
                parts.append(part)
            target=self.root.joinpath(*parts)
            cur=self.root
            for part in parts:
                cur=cur/part
                if cur.is_symlink(): raise PermissionError("Symlinks are not allowed")
            resolved=target.resolve()
            if resolved!=self.root and self.root not in resolved.parents: raise PermissionError("Path outside this server")
            return target
        def canonicalize(self,path):
            try: return posixpath.normpath("/"+str(path or "").lstrip("/"))
            except Exception: return "/"
        def list_folder(self,path):
            try:
                target=self._path(path)
                out=[]
                for child in target.iterdir():
                    if child.is_symlink(): continue
                    attr=paramiko.SFTPAttributes.from_stat(child.stat()); attr.filename=child.name; out.append(attr)
                return out
            except OSError as e: return paramiko.SFTPServer.convert_errno(e.errno)
            except Exception: return paramiko.SFTP_PERMISSION_DENIED
        def stat(self,path):
            try: return paramiko.SFTPAttributes.from_stat(self._path(path).stat())
            except OSError as e: return paramiko.SFTPServer.convert_errno(e.errno)
            except Exception: return paramiko.SFTP_PERMISSION_DENIED
        def lstat(self,path): return self.stat(path)
        def open(self,path,flags,attr):
            try:
                target=self._path(path)
                if not target.parent.is_dir(): return paramiko.SFTP_NO_SUCH_FILE
                mode=attr.st_mode if getattr(attr,"st_mode",None) else 0o640
                fd=os.open(target,flags,mode)
                handle=paramiko.SFTPHandle(flags)
                writing=bool(flags & (os.O_WRONLY|os.O_RDWR))
                reading=not bool(flags & os.O_WRONLY)
                if reading: handle.readfile=os.fdopen(os.dup(fd),"rb" if not writing else "r+b")
                if writing: handle.writefile=os.fdopen(os.dup(fd),"wb" if not reading else "r+b")
                os.close(fd)
                return handle
            except OSError as e: return paramiko.SFTPServer.convert_errno(e.errno)
            except Exception: return paramiko.SFTP_FAILURE
        def remove(self,path):
            try: self._path(path).unlink(); return paramiko.SFTP_OK
            except OSError as e: return paramiko.SFTPServer.convert_errno(e.errno)
            except Exception: return paramiko.SFTP_PERMISSION_DENIED
        def mkdir(self,path,attr):
            try: self._path(path).mkdir(mode=(attr.st_mode & 0o777) if attr.st_mode else 0o750); return paramiko.SFTP_OK
            except OSError as e: return paramiko.SFTPServer.convert_errno(e.errno)
            except Exception: return paramiko.SFTP_PERMISSION_DENIED
        def rmdir(self,path):
            try: self._path(path).rmdir(); return paramiko.SFTP_OK
            except OSError as e: return paramiko.SFTPServer.convert_errno(e.errno)
            except Exception: return paramiko.SFTP_PERMISSION_DENIED
        def rename(self,oldpath,newpath):
            try:
                old=self._path(oldpath); new=self._path(newpath)
                if new.exists(): return paramiko.SFTP_FAILURE
                old.rename(new); return paramiko.SFTP_OK
            except OSError as e: return paramiko.SFTPServer.convert_errno(e.errno)
            except Exception: return paramiko.SFTP_PERMISSION_DENIED
        def chattr(self,path,attr):
            try:
                target=self._path(path)
                if attr.st_mode is not None: os.chmod(target,attr.st_mode & 0o777)
                if attr.st_atime is not None or attr.st_mtime is not None:
                    st=target.stat(); os.utime(target,(attr.st_atime if attr.st_atime is not None else st.st_atime,attr.st_mtime if attr.st_mtime is not None else st.st_mtime))
                return paramiko.SFTP_OK
            except OSError as e: return paramiko.SFTPServer.convert_errno(e.errno)
            except Exception: return paramiko.SFTP_PERMISSION_DENIED
        def symlink(self,*args): return paramiko.SFTP_OP_UNSUPPORTED
        def readlink(self,*args): return paramiko.SFTP_OP_UNSUPPORTED

def _serve_sftp_client(client,host_key):
    if not paramiko:
        client.close(); return
    transport=None
    try:
        transport=paramiko.Transport(client)
        transport.add_server_key(host_key)
        transport.set_subsystem_handler("sftp",paramiko.SFTPServer,OMCPSSFTPInterface)
        transport.start_server(server=OMCPSSFTPAuth())
        transport.set_keepalive(30)
        while transport.is_active(): time.sleep(0.5)
    except Exception:
        pass
    finally:
        try:
            if transport: transport.close()
            else: client.close()
        except Exception: pass

def start_sftp_service():
    global SFTP_STATE
    if not paramiko:
        SFTP_STATE={"available":False,"status":"unavailable","error":"Python Paramiko package is missing. Re-run the OMCP installer.","fingerprint":""}; return
    try:
        if SFTP_HOST_KEY.exists(): host_key=paramiko.RSAKey.from_private_key_file(str(SFTP_HOST_KEY))
        else:
            host_key=paramiko.RSAKey.generate(2048); host_key.write_private_key_file(str(SFTP_HOST_KEY)); os.chmod(SFTP_HOST_KEY,0o600)
        fingerprint="SHA256:"+base64.b64encode(__import__("hashlib").sha256(host_key.asbytes()).digest()).decode().rstrip("=")
        listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM); listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind(("0.0.0.0",SFTP_PORT)); listener.listen(64); listener.settimeout(1.0)
        def accept_loop():
            while True:
                try: client,_=listener.accept()
                except socket.timeout: continue
                except OSError: break
                threading.Thread(target=_serve_sftp_client,args=(client,host_key),daemon=True).start()
        threading.Thread(target=accept_loop,daemon=True,name="omcp-sftp").start()
        SFTP_STATE={"available":True,"status":"listening","error":"","fingerprint":fingerprint}
        print("OMCP SFTP listening on 0.0.0.0:%s"%SFTP_PORT,flush=True)
    except Exception as e:
        SFTP_STATE={"available":False,"status":"error","error":str(e),"fingerprint":""}
        print("OMCP SFTP could not start: "+str(e),flush=True)

def sftp_info(sid):
    meta=json.loads((safe_dir(sid)/"omcp.json").read_text())
    return {"available":SFTP_STATE.get("available",False),"status":SFTP_STATE.get("status","unavailable"),"error":SFTP_STATE.get("error",""),"enabled":bool(meta.get("sftp",{}).get("password_hash")),"username":"omcp-"+sid,"port":SFTP_PORT,"fingerprint":SFTP_STATE.get("fingerprint","")}

def reset_sftp_password(sid):
    if not SFTP_STATE.get("available"): raise ValueError(SFTP_STATE.get("error") or "SFTP service is not running")
    folder=safe_dir(sid); meta=json.loads((folder/"omcp.json").read_text())
    password=secrets.token_urlsafe(18)
    meta["sftp"]={"password_hash":password_hash(password),"created":int(time.time())}
    atomic_json(folder/"omcp.json",meta)
    return {"enabled":True,"username":"omcp-"+sid,"password":password,"port":SFTP_PORT,"fingerprint":SFTP_STATE.get("fingerprint","")}

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
    # Some HTTPS reverse proxies remove Authorization headers. Accept a dedicated
    # panel-session header as a fallback while keeping the same random session token.
    header=handler.headers.get("Authorization","")
    token=header[7:] if header.startswith("Bearer ") else handler.headers.get("X-OMCP-Session","")
    if not token: return None
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

def server_processes(sid):
    """Find Minecraft JVMs by exact server working directory and JAR path."""
    folder=safe_dir(sid)
    expected={(folder/"server.jar").resolve(),(folder/"paper.jar").resolve()}
    found=[]
    tracked=PROCS.get(sid)
    if tracked and tracked.poll() is None: found.append(tracked.pid)
    try: entries=list(Path("/proc").iterdir())
    except Exception: entries=[]
    for entry in entries:
        if not entry.name.isdigit(): continue
        pid=int(entry.name)
        try:
            if Path(os.readlink(str(entry/"cwd"))).resolve()!=folder: continue
            args=[x.decode(errors="replace") for x in (entry/"cmdline").read_bytes().split(b"\0") if x]
            if "-jar" not in args: continue
            jar_arg=args[args.index("-jar")+1]
            if Path(jar_arg).resolve() not in expected: continue
            if "java" not in Path(os.readlink(str(entry/"exe"))).name.lower(): continue
            if pid not in found: found.append(pid)
        except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, OSError):
            continue
    return found

def server_running(sid):
    return bool(server_processes(sid))

def servers():
    out=[]
    for p in SERVERS.iterdir():
        if p.is_dir() and re.fullmatch(r"[a-f0-9]{8}",p.name) and (p/"omcp.json").exists():
            m=json.loads((p/"omcp.json").read_text())
            out.append({"id":p.name,"name":m["name"],"version":m["version"],"software":m.get("software","paper"),"memory":m["memory"],"port":m["port"],"status":"running" if server_running(p.name) else "stopped"})
    return out

def physical_ram_gb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return max(1,int(line.split()[1])//1048576)
    except Exception: pass
    return 1

def create(d):
    name=str(d.get('name','')).strip(); ver=str(d.get('version','')).strip(); software=str(d.get('software','paper')).lower()
    mem=int(d.get('memory',2)); port=int(d.get('port',25565))
    supported=('paper','purpur','folia','spigot','velocity','waterfall','fabric','vanilla')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{1,23}',name): raise ValueError('Name must be 2-24 letters, numbers, _ or -')
    if not re.fullmatch(r'\d{1,2}\.\d{1,2}(?:\.\d{1,2})?(?:-[A-Za-z0-9.-]+)?',ver): raise ValueError('Invalid Minecraft or proxy software version')
    if software not in supported: raise ValueError('Unsupported software. Choose Paper, Purpur, Folia, Velocity, Waterfall, Fabric or Vanilla.')
    if not 1<=mem<=physical_ram_gb() or not 1024<=port<=65535: raise ValueError('RAM must be between 1 GB and host RAM; port 1024-65535')
    if not d.get('eulaAccepted'): raise ValueError('Accept the Minecraft EULA first')
    if not shutil.which('java'): raise ValueError('Java runtime not found')
    if any(s['name'].lower()==name.lower() or s['port']==port for s in servers()): raise ValueError('Name or port already used')
    sid=secrets.token_hex(4); folder=safe_dir(sid); folder.mkdir(mode=0o750)
    try:
        download_server_jar(software,ver,folder/'server.jar')
        if software not in ('velocity','waterfall'): (folder/'eula.txt').write_text('eula=true\n')
        if software not in ('velocity','waterfall'): (folder/'server.properties').write_text('server-port='+str(port)+'\n')
        (folder/'omcp.json').write_text(json.dumps({'name':name,'version':ver,'software':software,'memory':mem,'port':port,'serverType':'proxy' if software in ('velocity','waterfall') else 'game'},indent=2))
        return next(s for s in servers() if s['id']==sid)
    except Exception:
        shutil.rmtree(folder,ignore_errors=True)
        raise

def download_server_jar(software, ver, destination):
    headers={'User-Agent':'OMCP/0.5 (https://github.com/nmronion-alt/onion-hub)','Accept':'application/json'}
    if software in ('paper','folia','velocity','waterfall'):
        api='https://fill.papermc.io/v3/projects/'+software+'/versions/'+ver+'/builds?channel=STABLE&limit=1'
        with urllib.request.urlopen(urllib.request.Request(api,headers=headers),timeout=30) as r: builds=json.load(r)
        stable=next((x for x in builds if x.get('channel')=='STABLE' and x.get('downloads',{}).get('server:default',{}).get('url')),None)
        if not stable: raise ValueError('No stable '+software.title()+' build found for Minecraft '+ver)
        url=stable['downloads']['server:default']['url']
    elif software=='purpur':
        api='https://api.purpurmc.org/v2/purpur/'+ver
        with urllib.request.urlopen(urllib.request.Request(api,headers=headers),timeout=30) as r: info=json.load(r)
        builds=info.get('builds',{}).get('all',[])
        if not builds: raise ValueError('No Purpur builds found for Minecraft '+ver)
        url='https://api.purpurmc.org/v2/purpur/'+ver+'/'+str(builds[-1])+'/download'
    elif software=='fabric':
        with urllib.request.urlopen(urllib.request.Request('https://meta.fabricmc.net/v2/versions/loader/'+ver,headers=headers),timeout=30) as r: loaders=json.load(r)
        with urllib.request.urlopen(urllib.request.Request('https://meta.fabricmc.net/v2/versions/installer',headers=headers),timeout=30) as r: installers=json.load(r)
        loader=next((x['loader']['version'] for x in loaders if x.get('loader',{}).get('stable')),None)
        installer=next((x['version'] for x in installers if x.get('stable')),None)
        if not loader or not installer: raise ValueError('No stable Fabric loader found for '+ver)
        url='https://meta.fabricmc.net/v2/versions/loader/'+ver+'/'+loader+'/'+installer+'/server/jar'
    elif software=='spigot':
        if not shutil.which('git'): raise ValueError('Git is required to build Spigot. Re-run the OMCP installer to install Git.')
        build_dir=destination.parent/('buildtools-'+secrets.token_hex(4)); build_dir.mkdir(parents=True,exist_ok=True)
        try:
            buildtools=build_dir/'BuildTools.jar'
            build_url='https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar'
            with urllib.request.urlopen(urllib.request.Request(build_url,headers=headers),timeout=60) as r, buildtools.open('wb') as out: shutil.copyfileobj(r,out)
            java=shutil.which('java')
            result=subprocess.run([java,'-jar',str(buildtools),'--rev',ver],cwd=build_dir,capture_output=True,text=True,timeout=900)
            built=build_dir/('spigot-'+ver+'.jar')
            if result.returncode!=0 or not built.is_file(): raise ValueError('Spigot BuildTools failed: '+(result.stderr or result.stdout or 'Build did not produce a Spigot JAR')[-1800:])
            shutil.copy2(built,destination)
        finally: shutil.rmtree(build_dir,ignore_errors=True)
    elif software=='vanilla':
        with urllib.request.urlopen(urllib.request.Request('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json',headers=headers),timeout=30) as r: manifest=json.load(r)
        item=next((x for x in manifest['versions'] if x['id']==ver and x['type']=='release'),None)
        if not item: raise ValueError('No official Vanilla release found for '+ver)
        with urllib.request.urlopen(urllib.request.Request(item['url'],headers=headers),timeout=30) as r: meta=json.load(r)
        url=meta.get('downloads',{}).get('server',{}).get('url')
        if not url: raise ValueError('No official Vanilla server download for '+ver)
    else: raise ValueError('Unsupported server software')
    req=urllib.request.Request(url,headers={'User-Agent':headers['User-Agent']})
    with urllib.request.urlopen(req,timeout=240) as r, destination.open('wb') as out: shutil.copyfileobj(r,out)
    if destination.stat().st_size<100000 or not zipfile.is_zipfile(destination):
        destination.unlink(missing_ok=True)
        raise ValueError('Downloaded server software failed JAR validation')

VERSION_CACHE={}
def software_versions(software):
    software=str(software or '').lower()
    if software not in ('paper','purpur','folia','spigot','velocity','waterfall','fabric','vanilla'): raise ValueError('Unsupported server software')
    cached=VERSION_CACHE.get(software)
    if cached and time.time()-cached[0]<300: return cached[1]
    headers={'User-Agent':'OMCP/0.5 (https://github.com/nmronion-alt/onion-hub)','Accept':'application/json'}
    if software in ('paper','folia','velocity','waterfall'):
        with urllib.request.urlopen(urllib.request.Request('https://fill.papermc.io/v3/projects/'+software,headers=headers),timeout=30) as r: data=json.load(r)
        versions=[v for group in data.get('versions',{}).values() for v in group]
    elif software=='purpur':
        with urllib.request.urlopen(urllib.request.Request('https://api.purpurmc.org/v2/purpur',headers=headers),timeout=30) as r: data=json.load(r)
        versions=data.get('versions',[])
    elif software=='fabric':
        with urllib.request.urlopen(urllib.request.Request('https://meta.fabricmc.net/v2/versions/game',headers=headers),timeout=30) as r: data=json.load(r)
        versions=[x['version'] for x in data if x.get('stable')]
    else:
        with urllib.request.urlopen(urllib.request.Request('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json',headers=headers),timeout=30) as r: data=json.load(r)
        versions=[x['id'] for x in data.get('versions',[]) if x.get('type')=='release']
    versions=sorted(set(str(v) for v in versions),key=lambda v:tuple(int(x) for x in re.findall(r'\d+',v)),reverse=True)
    VERSION_CACHE[software]=(time.time(),versions)
    return versions

def upgrade_server(sid, ver, software=None, wipe=False):
    folder=safe_dir(sid); meta=json.loads((folder/"omcp.json").read_text())
    if not re.fullmatch(r"\d{1,2}\.\d{1,2}(?:\.\d{1,2})?(?:-[A-Za-z0-9.-]+)?",ver): raise ValueError("Invalid Minecraft or proxy software version")
    if server_running(sid): raise ValueError("Stop the server before changing its version")
    software=str(software or meta.get("software","paper")).lower()
    if software not in ("paper","purpur","folia","spigot","velocity","waterfall","fabric","vanilla"): raise ValueError("Unsupported server software")
    dest=ROOT/"backups"; dest.mkdir(exist_ok=True)
    backup=dest/(sid+"-"+time.strftime("%Y%m%d-%H%M%S")+".zip")
    with zipfile.ZipFile(backup,"w",zipfile.ZIP_DEFLATED) as z:
        for f in folder.rglob("*"):
            if f.is_file() and not f.is_symlink(): z.write(f,f.relative_to(folder))
    temp=folder/"server.jar.new"
    try:
        download_server_jar(software,ver,temp)
        if wipe:
            for child in list(folder.iterdir()):
                if child.name in ("omcp.json","server.jar.new"): continue
                if child.is_dir() and not child.is_symlink(): shutil.rmtree(child)
                elif child.is_file() or child.is_symlink(): child.unlink()
        os.replace(temp,folder/"server.jar")
        meta["version"]=ver; meta["software"]=software; meta["serverType"]="proxy" if software in ("velocity","waterfall") else "game"
        atomic_json(folder/"omcp.json",meta)
    finally:
        if temp.exists(): temp.unlink()
    return {"updated":True,"version":ver,"software":software,"backup":backup.name}

def java_runtimes():
    found=[]
    for base in (Path("/usr/lib/jvm"),Path("/opt/java"),Path("/usr/local/java")):
        if base.exists():
            for p in base.glob("*/bin/java"):
                if p.is_file() and os.access(p,os.X_OK): found.append(str(p.resolve()))
    system=shutil.which("java")
    if system and os.path.isfile(system): found.append(os.path.realpath(system))
    out=[]
    for p in dict.fromkeys(found):
        try:
            v=subprocess.run([p,"-version"],capture_output=True,text=True,timeout=5).stderr
            m=re.search(r'version "(?:1\.)?(\d+)',v)
            out.append({"path":p,"label":"Java "+(m.group(1) if m else "runtime")+" · "+p})
        except Exception: pass
    return out

def start(sid):
    folder=safe_dir(sid); m=json.loads((folder/"omcp.json").read_text())
    with LOCK:
        existing=server_processes(sid)
        if existing: raise ValueError("Minecraft is already running for this server (PID "+", ".join(map(str,existing))+"). Stop it first; OMCP detected the live process even after an agent restart.")
    java=m.get("javaPath") or shutil.which("java")
    software=str(m.get("software","paper")); ver=str(m.get("version",""))
    first=re.match(r"(\d+)",ver)
    major=int(first.group(1)) if first else 0
    needs_java25=(major>=26) or (software=="velocity" and major>=4)
    if needs_java25:
        candidates=[m["javaPath"]] if m.get("javaPath") else [x["path"] for x in java_runtimes() if x["label"].startswith("Java 25 ")]
        java25=None
        for candidate in candidates:
            try:
                output=subprocess.run([candidate,"-version"],capture_output=True,text=True,timeout=5).stderr
                match=re.search(r"version .*?(\d+)",output)
                if match and int(match.group(1))>=25: java25=candidate; break
            except Exception: pass
        if not java25: raise ValueError("This software version requires Java 25 or newer. Install/select Java 25 in Server Settings, then start again.")
        java=java25
    if not java or not os.path.isfile(java) or not os.access(java,os.X_OK): raise ValueError("Selected Java runtime is missing or not executable. Choose a valid Java runtime in Server Settings.")
    jar=folder/("server.jar" if (folder/"server.jar").is_file() else "paper.jar")
    if not jar.is_file() or jar.stat().st_size<100000: raise ValueError("Server JAR is missing or incomplete. Check the server files or use Reinstall server.")
    memory=int(m.get("memory",2))
    if memory<1 or memory>physical_ram_gb(): raise ValueError("Saved RAM setting is invalid for this host. Open Server Settings and save a valid memory limit.")
    log_path=folder/"console.log"
    fifo_path=folder/"console.stdin"
    if fifo_path.exists() and not fifo_path.is_fifo(): fifo_path.unlink()
    if not fifo_path.exists(): os.mkfifo(fifo_path,0o600)
    # Keep the JVM stdin descriptor blocking; Java console readers can exit on EAGAIN otherwise.
    fifo_fd=os.open(fifo_path,os.O_RDWR)
    try:
        with log_path.open("wb",buffering=0) as log:
            log.write(("\n[OMCP] Starting with Java: "+java+" | RAM: "+str(memory)+" GB | JAR: "+jar.name+"\n").encode())
            p=subprocess.Popen([java,f"-Xms{min(1,memory)}G",f"-Xmx{memory}G","-jar",str(jar),"nogui"],cwd=folder,stdin=fifo_fd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    except Exception as e:
        raise ValueError("Could not launch Minecraft: "+str(e))
    finally:
        os.close(fifo_fd)
    PROCS[sid]=p
    time.sleep(0.25)
    if p.poll() is not None:
        tail=log_path.read_text(errors="replace")[-1800:] if log_path.exists() else ""
        raise ValueError("Minecraft exited during startup (exit "+str(p.returncode)+"). Console: "+tail[-1200:])
    return {"status":"starting","pid":p.pid}

def send_console_command(sid, command):
    folder=safe_dir(sid)
    payload=command.encode("utf-8")+b"\n"
    fifo=folder/"console.stdin"
    # Preferred path: the named FIFO created before the JVM starts.
    try:
        if fifo.exists() and fifo.is_fifo():
            fd=os.open(str(fifo),os.O_WRONLY|os.O_NONBLOCK)
            try:
                os.write(fd,payload)
                return True
            finally:
                os.close(fd)
    except OSError:
        # A stale or unlinked FIFO can remain attached to the running JVM.
        pass
    # Recovery path: write to the JVM's inherited stdin descriptor. This also
    # works if console.stdin was removed after the process started.
    for pid in server_processes(sid):
        proc_fd=Path("/proc")/str(pid)/"fd"/"0"
        try:
            fd=os.open(str(proc_fd),os.O_WRONLY|os.O_NONBLOCK)
            try:
                os.write(fd,payload)
                return True
            finally:
                os.close(fd)
        except OSError:
            continue
    p=PROCS.get(sid)
    if p and p.poll() is None and p.stdin:
        try:
            p.stdin.write(payload); p.stdin.flush()
            return True
        except (BrokenPipeError,OSError,ValueError):
            pass
    return False

def stop(sid):
    p=PROCS.get(sid)
    tracked=p is not None and p.poll() is None
    pids=server_processes(sid)
    if not pids:
        (safe_dir(sid)/"console.log").unlink(missing_ok=True)
        (safe_dir(sid)/"console.stdin").unlink(missing_ok=True)
        return {"status":"stopped"}
    try:
        sent=send_console_command(sid,"stop")
        if tracked:
            try: p.wait(timeout=45)
            except subprocess.TimeoutExpired: p.terminate()
        elif not sent:
            for pid in pids:
                try: os.kill(pid, __import__("signal").SIGTERM)
                except ProcessLookupError: pass
        deadline=time.time()+45
        while time.time()<deadline and server_processes(sid):
            if tracked and p.poll() is not None: break
            time.sleep(0.25)
        remaining=server_processes(sid)
        if remaining:
            for pid in remaining:
                try: os.kill(pid, __import__("signal").SIGKILL)
                except ProcessLookupError: pass
            time.sleep(0.5)
        if server_processes(sid): raise ValueError("Minecraft process is still present; check server state before starting again.")
        (safe_dir(sid)/"console.log").unlink(missing_ok=True)
        (safe_dir(sid)/"console.stdin").unlink(missing_ok=True)
        return {"status":"stopped"}
    except Exception as e:
        if isinstance(e,ValueError): raise
        raise ValueError("Could not stop Minecraft cleanly: "+str(e))

def ensure_bore_binary():
    """Download the official static Bore release for supported Linux VPS architectures."""
    target=ROOT/"bin"/"bore"
    if target.is_file() and os.access(target,os.X_OK): return str(target)
    machine=platform.machine().lower()
    arch={"x86_64":"x86_64-unknown-linux-musl","amd64":"x86_64-unknown-linux-musl","aarch64":"aarch64-unknown-linux-musl","arm64":"aarch64-unknown-linux-musl"}.get(machine)
    if not arch: raise ValueError("Bore auto-install currently supports Linux x86_64 and ARM64 VPS hosts.")
    req=urllib.request.Request("https://api.github.com/repos/ekzhang/bore/releases/latest",headers={"User-Agent":"OMCP/0.8","Accept":"application/vnd.github+json"})
    with urllib.request.urlopen(req,timeout=30) as r: release=json.load(r)
    tag=str(release.get("tag_name","")).lstrip("v")
    asset=next((x for x in release.get("assets",[]) if x.get("name")==("bore-v"+tag+"-"+arch+".tar.gz")),None)
    if not asset: raise ValueError("Official Bore release has no binary for "+machine)
    with urllib.request.urlopen(asset["browser_download_url"],timeout=90) as r: archive=r.read()
    import io
    with tarfile.open(fileobj=io.BytesIO(archive),mode="r:gz") as tar:
        member=next((m for m in tar.getmembers() if m.isfile() and posixpath.basename(m.name)=="bore"),None)
        if not member: raise ValueError("Bore release archive did not contain its executable")
        stream=tar.extractfile(member)
        if not stream: raise ValueError("Could not read Bore executable from release archive")
        binary=stream.read()
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix(".new"); temp.write_bytes(binary); os.chmod(temp,0o755); os.replace(temp,target)
    return str(target)

def enable_minekube(sid, endpoint=""):
    folder=safe_dir(sid); meta=json.loads((folder/"omcp.json").read_text())
    software=str(meta.get("software","paper")).lower()
    asset_name={"paper":"connect-spigot.jar","purpur":"connect-spigot.jar","spigot":"connect-spigot.jar","velocity":"connect-velocity.jar"}.get(software)
    if not asset_name: raise ValueError("Minekube Connect plugin is enabled for Paper, Purpur, Spigot and Velocity. Folia and Waterfall compatibility is not assumed.")
    endpoint=str(endpoint or "").strip().lower()
    if endpoint and not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,31}",endpoint): raise ValueError("Endpoint must be 2-32 lowercase letters, numbers or hyphens.")
    req=urllib.request.Request("https://api.github.com/repos/minekube/connect-java/releases/latest",headers={"User-Agent":"OMCP/0.8","Accept":"application/vnd.github+json"})
    with urllib.request.urlopen(req,timeout=30) as r: release=json.load(r)
    asset=next((x for x in release.get("assets",[]) if x.get("name")==asset_name),None)
    if not asset: raise ValueError("Official Minekube release is missing "+asset_name)
    plugins=folder/"plugins"; plugins.mkdir(exist_ok=True)
    jar=plugins/asset_name
    with urllib.request.urlopen(asset["browser_download_url"],timeout=90) as r, jar.open("wb") as out: shutil.copyfileobj(r,out)
    if jar.stat().st_size<100000 or not zipfile.is_zipfile(jar):
        jar.unlink(missing_ok=True); raise ValueError("Downloaded Minekube plugin failed archive validation.")
    if software in ("paper","purpur","folia","spigot"):
        props=folder/"server.properties"
        raw=props.read_text(errors="replace") if props.exists() else ""
        if re.search(r"(?m)^enforce-secure-profile=",raw):
            raw=re.sub(r"(?m)^enforce-secure-profile=.*$","enforce-secure-profile=false",raw)
        else: raw+="\nenforce-secure-profile=false\n"
        props.write_text(raw)
    if endpoint:
        cfg=plugins/"connect"/"config.yml"; cfg.parent.mkdir(parents=True,exist_ok=True)
        existing=cfg.read_text(errors="replace") if cfg.exists() else ""
        if re.search(r"(?m)^endpoint:",existing): existing=re.sub(r"(?m)^endpoint:.*$", "endpoint: "+endpoint, existing)
        else: existing=existing.rstrip()+"\nendpoint: "+endpoint+"\n"
        cfg.write_text(existing)
    MINEKUBE_STATE[sid]={"installed":True,"endpoint":endpoint,"version":release.get("tag_name","latest"),"installed_at":int(time.time())}
    return minekube_info(sid)

def minekube_info(sid):
    folder=safe_dir(sid); meta=json.loads((folder/"omcp.json").read_text())
    software=str(meta.get("software","paper")).lower()
    plugin=folder/"plugins"/({"velocity":"connect-velocity.jar","waterfall":"connect-bungee.jar"}.get(software,"connect-spigot.jar"))
    state=MINEKUBE_STATE.get(sid,{})
    logs=folder/"console.log"
    raw=logs.read_text(errors="replace")[-100000:] if logs.exists() else ""
    match=re.search(r"(?:Your public address|Public address|Endpoint address):\s*([a-z0-9-]+\.play\.minekube\.net)",raw,re.I)
    configured=state.get("endpoint","")
    config_file=folder/"plugins"/"connect"/"config.yml"
    if not configured and config_file.exists():
        found=re.search(r"(?m)^endpoint:\s*([a-z0-9-]{2,32})\s*$",config_file.read_text(errors="replace"))
        if found: configured=found.group(1)
    active=bool(re.search(r"Enabling connect",raw,re.I))
    address=match.group(1) if match else (configured+".play.minekube.net" if configured and active else None)
    installed=plugin.is_file()
    return {"status":"running" if address and server_running(sid) else ("installed" if installed else "stopped"),"provider":"minekube","address":address,"installed":installed,"restartRequired":installed and not address and not server_running(sid),"logs":raw[-5000:] if raw else "Install the Connect plugin, then start/restart this server. Minekube will print its public address in the console."}

def start_tunnel(sid, provider):
    folder=safe_dir(sid); meta=json.loads((folder/"omcp.json").read_text()); port=int(meta.get("port",25565))
    if provider=="minekube": return enable_minekube(sid, "")
    if provider not in ("pinggy","bore"): raise ValueError("Unknown routing provider")
    if not server_running(sid): raise ValueError("Start the Minecraft server before starting its TCP tunnel.")
    ready=False
    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1",port),timeout=0.5): ready=True
            break
        except OSError: time.sleep(0.5)
    if not ready: raise ValueError("Minecraft process exists, but port "+str(port)+" is not accepting TCP connections yet. Wait for the console to say Done, then retry.")
    if provider=="bore":
        bore=ensure_bore_binary()
        with TUNNEL_LOCK:
            old=TUNNELS.get(sid)
            if old and old["proc"].poll() is None: raise ValueError("A tunnel is already running for this server")
            proc=subprocess.Popen([bore,"local",str(port),"--to","bore.pub"],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True)
            entry={"proc":proc,"provider":"bore","lines":[],"address":None,"started":int(time.time())}; TUNNELS[sid]=entry
        def collect_bore():
            try:
                for line in proc.stdout:
                    line=line.rstrip()
                    with TUNNEL_LOCK:
                        entry["lines"].append(line); entry["lines"]=entry["lines"][-80:]
                        match=re.search(r"(?:bore\.pub:|listening at\s+)(?:tcp://)?(?:bore\.pub:)?(\d{2,5})",line,re.I)
                        if match: entry["address"]="bore.pub:"+match.group(1)
            except Exception as e:
                with TUNNEL_LOCK: entry["lines"].append("Bore output error: "+str(e))
        threading.Thread(target=collect_bore,daemon=True).start()
        deadline=time.time()+25
        while time.time()<deadline:
            if entry.get("address"): return {"status":"running","provider":"bore","port":port,"address":entry["address"],"logs":"\n".join(entry["lines"][-20:])}
            if proc.poll() is not None:
                time.sleep(0.2); detail="\n".join(entry["lines"][-30:]) or "Bore exited without returning a port."
                raise ValueError("Bore tunnel exited (code "+str(proc.returncode)+"). "+detail[-1600:])
            time.sleep(0.2)
        return {"status":"starting","provider":"bore","port":port,"address":entry.get("address"),"logs":"\n".join(entry["lines"][-20:])}
    ssh=shutil.which("ssh")
    if not ssh: raise ValueError("OpenSSH client is not installed")
    with TUNNEL_LOCK:
        old=TUNNELS.get(sid)
        if old and old["proc"].poll() is None: raise ValueError("A tunnel is already running for this server")
        askpass=ROOT/"pinggy-askpass.sh"
        askpass.write_text("#!/bin/sh\nprintf '\\n'\n"); os.chmod(askpass,0o700)
        env=os.environ.copy(); env["SSH_ASKPASS"]=str(askpass); env["SSH_ASKPASS_REQUIRE"]="force"; env["DISPLAY"]=env.get("DISPLAY","omcp:0")
        cmd=[ssh,"-T","-p","443","-o","ConnectTimeout=20","-o","ConnectionAttempts=2","-o","RequestTTY=no","-o","BatchMode=no","-o","NumberOfPasswordPrompts=1","-o","PreferredAuthentications=password","-o","PasswordAuthentication=yes","-o","KbdInteractiveAuthentication=no","-o","PubkeyAuthentication=no","-o","StrictHostKeyChecking=accept-new","-o","ServerAliveInterval=20","-o","ServerAliveCountMax=3","-o","ExitOnForwardFailure=yes","-R0:127.0.0.1:"+str(meta["port"]),"tcp@free.pinggy.io"]
        proc=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True,env=env)
        entry={"proc":proc,"provider":"pinggy","lines":[],"address":None,"started":int(time.time())}; TUNNELS[sid]=entry
    def collect():
        try:
            for line in proc.stdout:
                line=line.rstrip()
                with TUNNEL_LOCK:
                    entry["lines"].append(line); entry["lines"]=entry["lines"][-80:]
                    match=re.search(r"tcp://((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}):(\d{2,5})",line)
                    if match: entry["address"]=match.group(1)+":"+match.group(2)
        except Exception as e:
            with TUNNEL_LOCK: entry["lines"].append("Tunnel output error: "+str(e))
    threading.Thread(target=collect,daemon=True).start()
    deadline=time.time()+25
    while time.time()<deadline:
        if entry.get("address"):
            return {"status":"running","provider":"pinggy","port":meta["port"],"address":entry["address"],"logs":"\n".join(entry["lines"][-20:])}
        if proc.poll() is not None:
            time.sleep(0.2)
            detail="\n".join(entry["lines"][-30:]) or "SSH exited without returning a tunnel address."
            raise ValueError("Pinggy tunnel process exited (code "+str(proc.returncode)+"). "+detail[-1800:])
        time.sleep(0.2)
    return {"status":"starting","provider":"pinggy","port":meta["port"],"address":entry["address"],"logs":"\n".join(entry["lines"][-20:])}

def tunnel_info(sid):
    with TUNNEL_LOCK:
        entry=TUNNELS.get(sid)
        if entry:
            p=entry["proc"]; alive=p.poll() is None
            if alive:
                status=("running" if entry["address"] else "starting")
                return {"status":status,"provider":entry["provider"],"address":entry["address"],"logs":"\n".join(entry["lines"][-30:])}
    if MINEKUBE_STATE.get(sid) or (safe_dir(sid)/"plugins"/"connect-spigot.jar").exists() or (safe_dir(sid)/"plugins"/"connect-velocity.jar").exists() or (safe_dir(sid)/"plugins"/"connect-bungee.jar").exists():
        return minekube_info(sid)
    if entry: return {"status":"stopped","provider":entry["provider"],"address":None,"logs":"Routing process has stopped."}
    return {"status":"stopped","provider":None,"address":None,"logs":""}

def stop_tunnel(sid):
    with TUNNEL_LOCK:
        entry=TUNNELS.get(sid)
        if not entry: return {"status":"stopped"}
        if entry.get("provider")=="minekube": return {"status":"installed","provider":"minekube","address":minekube_info(sid).get("address"),"logs":"Minekube is managed by the server plugin. Stop the Minecraft server to disconnect it."}
        p=entry["proc"]
        if p.poll() is None:
            p.terminate()
            try: p.wait(timeout=5)
            except subprocess.TimeoutExpired: p.kill()
        return {"status":"stopped"}

def plugin_search(query):
    query=str(query or "").strip()
    if len(query)>100: raise ValueError("Search query is too long")
    ua={"User-Agent":"OMCP/0.7 (https://github.com/nmronion-alt/onion-hub)"}
    results=[]; errors=[]
    facets='[["project_type:plugin"],["categories:paper"]]'
    params="limit=10&index=downloads&facets="+quote(facets)
    if query: params+="&query="+quote(query)
    req=urllib.request.Request("https://api.modrinth.com/v2/search?"+params,headers=ua)
    try:
        with urllib.request.urlopen(req,timeout=18) as r: data=json.load(r)
        for x in data.get("hits",[]):
            results.append({"id":x.get("project_id"),"slug":x.get("slug"),"name":x.get("title"),"description":x.get("description",""),"downloads":x.get("downloads",0),"source":"modrinth"})
    except Exception as e:
        errors.append("Modrinth: "+str(e)[:180])
    try:
        endpoint=("https://api.spiget.org/v2/search/resources/"+quote(query,safe="") if query else "https://api.spiget.org/v2/resources")
        endpoint+=("?size=8&field=name&sort=-downloads" if query else "?size=8&sort=-downloads")
        req=urllib.request.Request(endpoint,headers=ua)
        with urllib.request.urlopen(req,timeout=18) as r: items=json.load(r)
        for x in items if isinstance(items,list) else []:
            rid=x.get("id")
            if rid is not None:
                results.append({"id":str(rid),"name":x.get("name","Spigot resource"),"description":x.get("tag","") or x.get("description",""),"downloads":x.get("downloads",0),"source":"spiget"})
    except Exception as e:
        errors.append("Spiget: "+str(e)[:180])
    results.sort(key=lambda x:int(x.get("downloads") or 0),reverse=True)
    if not results and errors: raise ValueError("Plugin catalogues could not be reached. "+" | ".join(errors))
    return {"plugins":results[:16],"warnings":errors}

def install_plugin(sid, project_id, source="modrinth"):
    folder=safe_dir(sid); meta=json.loads((folder/"omcp.json").read_text())
    if meta.get("software","paper") not in ("paper","purpur","folia","spigot"): raise ValueError("The plugin installer supports Paper, Purpur, Folia and Spigot game servers only.")
    # Plugin JARs can be placed while online; Paper loads them on next restart.
    if source=="spiget":
        if not str(project_id).isdigit(): raise ValueError("Invalid Spiget resource ID")
        req=urllib.request.Request("https://api.spiget.org/v2/resources/"+str(int(project_id)),headers={"User-Agent":"OMCP/0.6"})
        with urllib.request.urlopen(req,timeout=20) as r: resource=json.load(r)
        # Let Spiget resolve external download redirects; the JAR signature/size checks below still validate the result.
        req=urllib.request.Request("https://api.spiget.org/v2/resources/"+str(int(project_id))+"/download",headers={"User-Agent":"OMCP/0.6"})
        with urllib.request.urlopen(req,timeout=60) as r:
            raw=r.read(50*1024*1024+1)
            cd=r.headers.get("Content-Disposition","")
        if len(raw)>50*1024*1024 or not zipfile.is_zipfile(__import__("io").BytesIO(raw)): raise ValueError("Spiget download is not a valid JAR or exceeds 50 MB")
        match=re.search(r'filename="?([^";]+)',cd)
        filename=Path(match.group(1) if match else (str(resource.get("name","plugin")).replace(" ","_")+".jar")).name
        if not filename.lower().endswith(".jar"): filename+=".jar"
        if not re.fullmatch(r"[A-Za-z0-9_. -]{1,120}\.jar",filename): raise ValueError("Unsafe plugin filename")
        dest=folder/"plugins"; dest.mkdir(exist_ok=True); target=dest/filename
        if target.exists(): raise ValueError("A plugin with this filename is already installed")
        tmp=target.with_name(target.name+".omcp-tmp")
        try:
            tmp.write_bytes(raw); os.replace(tmp,target)
        finally:
            if tmp.exists(): tmp.unlink()
        return {"installed":filename,"path":"plugins/"+filename,"source":"spiget","restartRequired":True}
    if source!="modrinth": raise ValueError("Unknown plugin catalogue")
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,64}",str(project_id)): raise ValueError("Invalid plugin project ID")
    req=urllib.request.Request("https://api.modrinth.com/v2/project/"+project_id+"/version",headers={"User-Agent":"OMCP/0.6 (https://github.com/nmronion-alt/onion-hub)"})
    with urllib.request.urlopen(req,timeout=20) as r: versions=json.load(r)
    compatible=[v for v in versions if meta["version"] in v.get("game_versions",[]) and any(x.lower() in ("paper","spigot","purpur","folia") for x in v.get("loaders",[]))]
    if not compatible: raise ValueError("No Paper-compatible release found for Minecraft "+meta["version"])
    compatible.sort(key=lambda v:v.get("date_published",""),reverse=True)
    chosen=compatible[0]; files=chosen.get("files",[])
    file=next((x for x in files if x.get("primary")),files[0] if files else None)
    if not file: raise ValueError("Plugin release has no downloadable file")
    filename=Path(file.get("filename","")).name
    if not filename.lower().endswith(".jar") or not re.fullmatch(r"[A-Za-z0-9_. -]{1,120}\.jar",filename): raise ValueError("Plugin download is not a valid JAR filename")
    with urllib.request.urlopen(urllib.request.Request(file["url"],headers={"User-Agent":"OMCP/0.5"}),timeout=60) as r: raw=r.read(50*1024*1024+1)
    if len(raw)>50*1024*1024 or not zipfile.is_zipfile(__import__("io").BytesIO(raw)): raise ValueError("Downloaded plugin JAR failed validation or exceeds 50 MB")
    dest=folder/"plugins"; dest.mkdir(exist_ok=True); target=dest/filename
    if target.exists(): raise ValueError("A plugin with this filename is already installed")
    tmp=target.with_name(target.name+".omcp-tmp")
    try:
        tmp.write_bytes(raw); os.replace(tmp,target)
    finally:
        if tmp.exists(): tmp.unlink()
    return {"installed":filename,"path":"plugins/"+filename,"version":chosen.get("version_number"),"restartRequired":True}

def server_metrics(sid):
    folder=safe_dir(sid); pids=server_processes(sid); pid=pids[0] if pids else None
    running=pid is not None
    memory=0; cpu=None
    if running:
        try:
            stat=Path("/proc/%s/stat"%pid).read_text()
            fields=stat[stat.rfind(")")+2:].split()
            ticks=int(fields[11])+int(fields[12]); now=time.time(); prev=METRIC_PREV.get(sid)
            cpu=round(min(100.0,max(0.0,((ticks-prev[1])/(os.sysconf("SC_CLK_TCK")*max(.1,now-prev[0])))*100.0)),1) if prev else 0.0
            METRIC_PREV[sid]=(now,ticks)
        except Exception: cpu=0.0
        try:
            for line in Path("/proc/%s/status"%pid).read_text().splitlines():
                if line.startswith("VmRSS:"): memory=int(line.split()[1])*1024; break
        except Exception: memory=0
    else: METRIC_PREV.pop(sid,None)
    disk=0
    for f in folder.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink(): disk+=f.stat().st_size
        except OSError: pass
    return {"status":"running" if running else "stopped","cpuLoad":cpu,"memoryUsed":memory if running else None,"diskUsed":disk,"networkInRate":None,"networkOutRate":None}

def server_path(folder, rel):
    rel=str(rel or "")
    if not rel or rel.startswith("/") or "\\" in rel or any(x in ("",".","..") for x in rel.split("/")):
        raise ValueError("Invalid relative path")
    target=folder/rel; cur=folder
    for part in rel.split("/"):
        cur=cur/part
        if cur.is_symlink(): raise ValueError("Symlinks are not allowed")
    if folder.resolve() not in target.resolve().parents: raise ValueError("Path outside server")
    return target

def body(h):
    n=int(h.headers.get("Content-Length","0"))
    if n>1048576: raise ValueError("Request too large")
    return json.loads(h.rfile.read(n) or b"{}")

def send(h,code,obj,typ="application/json; charset=utf-8"):
    raw=obj if isinstance(obj,bytes) else json.dumps(obj).encode()
    h.send_response(code); h.send_header("Content-Type",typ); h.send_header("Cache-Control","no-store")
    h.send_header("X-Content-Type-Options","nosniff"); h.send_header("Content-Length",str(len(raw))); h.end_headers(); h.wfile.write(raw)


BACKUP_CONFIG=ROOT/"backup-config.json"
BACKUP_CONFIG_LOCK=threading.RLock()

def load_backup_config():
    try:
        data=json.loads(BACKUP_CONFIG.read_text())
        return data if isinstance(data,dict) else {"google_drive":{},"schedules":{}}
    except FileNotFoundError:
        return {"google_drive":{},"schedules":{}}
    except Exception:
        return {"google_drive":{},"schedules":{}}

def save_backup_config(data):
    tmp=BACKUP_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(data,indent=2),encoding="utf-8")
    os.chmod(tmp,0o600)
    os.replace(tmp,BACKUP_CONFIG)
    os.chmod(BACKUP_CONFIG,0o600)

def google_drive_configured(cfg=None):
    cfg=cfg or load_backup_config()
    drive=cfg.get("google_drive",{})
    return all(drive.get(k) for k in ("client_id","client_secret","refresh_token"))

def google_drive_upload(path):
    cfg=load_backup_config().get("google_drive",{})
    if not all(cfg.get(k) for k in ("client_id","client_secret","refresh_token")):
        raise ValueError("Google Drive is not connected. Save OAuth Client ID, Client Secret and Refresh Token in Backups settings.")
    token_body=urlencode({"client_id":cfg["client_id"],"client_secret":cfg["client_secret"],"refresh_token":cfg["refresh_token"],"grant_type":"refresh_token"}).encode()
    req=urllib.request.Request("https://oauth2.googleapis.com/token",data=token_body,headers={"Content-Type":"application/x-www-form-urlencoded"},method="POST")
    with urllib.request.urlopen(req,timeout=30) as response: token=json.load(response)
    access=token.get("access_token")
    if not access: raise ValueError("Google did not return an access token. Reconnect Drive and check the refresh token.")
    p=Path(path); size=p.stat().st_size
    metadata={"name":p.name}
    if cfg.get("folder_id"): metadata["parents"]=[cfg["folder_id"]]
    init=urllib.request.Request("https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,name,webViewLink",data=json.dumps(metadata).encode(),headers={"Authorization":"Bearer "+access,"Content-Type":"application/json; charset=UTF-8","X-Upload-Content-Type":"application/zip","X-Upload-Content-Length":str(size)},method="POST")
    with urllib.request.urlopen(init,timeout=30) as response: session=response.headers.get("Location")
    if not session: raise ValueError("Google Drive did not return a resumable upload session.")
    uploaded=0
    with p.open("rb") as stream:
        while uploaded<size:
            chunk=stream.read(8*1024*1024)
            if not chunk: break
            end=uploaded+len(chunk)-1
            put=urllib.request.Request(session,data=chunk,headers={"Authorization":"Bearer "+access,"Content-Type":"application/zip","Content-Length":str(len(chunk)),"Content-Range":"bytes "+str(uploaded)+"-"+str(end)+"/"+str(size)},method="PUT")
            try:
                with urllib.request.urlopen(put,timeout=180) as response:
                    result=json.loads(response.read() or b"{}") if response.status in (200,201) else {}
            except urllib.error.HTTPError as e:
                if e.code==308: result={}
                else: raise
            uploaded=end+1
    if uploaded!=size: raise ValueError("Google Drive upload ended early ("+str(uploaded)+"/"+str(size)+" bytes).")
    return {"id":result.get("id",""),"name":result.get("name",p.name),"webViewLink":result.get("webViewLink","")}

def create_live_backup(sid):
    folder=safe_dir(sid); running=server_running(sid); paused=False
    if running:
        if not send_console_command(sid,"save-off"): raise ValueError("Could not pause world saving for a consistent live backup.")
        paused=True
        try:
            send_console_command(sid,"save-all flush")
            time.sleep(2.5)
        except Exception: pass
    try:
        dest=ROOT/"backups"; dest.mkdir(exist_ok=True)
        zpath=dest/(sid+"-"+time.strftime("%Y%m%d-%H%M%S")+".zip")
        with zipfile.ZipFile(zpath,"w",zipfile.ZIP_DEFLATED,compresslevel=3) as z:
            for f in folder.rglob("*"):
                if f.is_file() and not f.is_symlink() and f.name not in ("console.stdin",):
                    z.write(f,f.relative_to(folder))
        return {"backup":zpath.name,"bytes":zpath.stat().st_size,"path":str(zpath)}
    finally:
        if paused:
            try: send_console_command(sid,"save-on")
            except Exception: pass

def prune_uploaded_backups(sid, keep=3):
    dest=ROOT/"backups"
    items=sorted((p for p in dest.glob(sid+"-*.zip") if p.is_file() and not p.is_symlink()),key=lambda p:p.stat().st_mtime,reverse=True)
    for old in items[max(0,int(keep)):]:
        try: old.unlink()
        except OSError: pass

def backup_scheduler_loop():
    while True:
        try:
            cfg=load_backup_config()
            schedules=cfg.get("schedules",{})
            now=int(time.time())
            for sid,item in list(schedules.items()):
                if not re.fullmatch(r"[a-f0-9]{8}",sid) or not isinstance(item,dict) or not item.get("enabled"): continue
                interval=max(15,min(10080,int(item.get("interval_minutes",360))))
                if now-int(item.get("last_run",0))<interval*60: continue
                if not server_running(sid): continue
                try:
                    result=create_live_backup(sid)
                    provider=item.get("provider","google_drive")
                    cloud=google_drive_upload(result["path"]) if provider=="google_drive" else {"id":"","name":result["backup"]}
                    if provider=="google_drive": prune_uploaded_backups(sid,3)
                    with BACKUP_CONFIG_LOCK:
                        latest=load_backup_config(); sched=latest.setdefault("schedules",{}).setdefault(sid,{})
                        sched["last_run"]=now; sched["last_status"]=("Uploaded "+result["backup"]+" to Google Drive") if provider=="google_drive" else ("Saved locally: "+result["backup"]); sched["last_file_id"]=cloud.get("id","")
                        save_backup_config(latest)
                    print("OMCP scheduled backup uploaded: "+sid+" "+result["backup"],flush=True)
                except Exception as e:
                    with BACKUP_CONFIG_LOCK:
                        latest=load_backup_config(); sched=latest.setdefault("schedules",{}).setdefault(sid,{})
                        sched["last_run"]=now; sched["last_status"]="ERROR: "+str(e)[:500]
                        save_backup_config(latest)
                    print("OMCP scheduled backup failed for "+sid+": "+str(e),flush=True)
        except Exception as e:
            print("OMCP backup scheduler error: "+str(e),flush=True)
        time.sleep(20)



def read_server_properties(sid):
    folder=safe_dir(sid); path=folder/"server.properties"
    values={}
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            raw=line.strip()
            if not raw or raw.startswith("#") or "=" not in raw: continue
            k,v=raw.split("=",1); values[k.strip()]=v.strip()
    return values

def write_server_properties(sid, changes):
    folder=safe_dir(sid); path=folder/"server.properties"
    if server_running(sid): raise ValueError("Stop the server before changing server.properties; restart after saving.")
    allowed={
        "max-players":("int",1,1000),"gamemode":("enum",["survival","creative","adventure","spectator"]),
        "difficulty":("enum",["peaceful","easy","normal","hard"]),"white-list":("bool",),
        "online-mode":("bool",),"allow-flight":("bool",),"force-gamemode":("bool",),
        "spawn-protection":("int",0,1000000),"require-resource-pack":("bool",),
        "resource-pack":("url",),"resource-pack-prompt":("text",),"level-name":("world",)
    }
    current=read_server_properties(sid)
    for key,value in changes.items():
        if key not in allowed: raise ValueError("Unsupported server.properties option: "+str(key))
        spec=allowed[key]; value=str(value)
        if spec[0]=="bool" and value.lower() not in ("true","false"): raise ValueError(key+" must be true or false")
        if spec[0]=="int":
            n=int(value)
            if not spec[1]<=n<=spec[2]: raise ValueError(key+" is outside the allowed range")
            value=str(n)
        if spec[0]=="enum" and value not in spec[1]: raise ValueError("Invalid value for "+key)
        if spec[0]=="url" and value and not re.match(r"^https://",value): raise ValueError("Resource pack URL must use HTTPS")
        if spec[0]=="world" and (not re.fullmatch(r"[A-Za-z0-9 _.-]{1,64}",value) or value in (".","..")): raise ValueError("Invalid world name")
        if spec[0]=="text" and len(value)>500: raise ValueError("Prompt is too long")
        current[key]=value
    lines=[]
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key=line.split("=",1)[0].strip()
                if key in current:
                    lines.append(key+"="+current.pop(key)); continue
            lines.append(line)
    lines.extend(k+"="+v for k,v in current.items())
    tmp=path.with_name(path.name+".tmp"); tmp.write_text("\\n".join(lines)+"\\n",encoding="utf-8"); os.replace(tmp,path)
    return read_server_properties(sid)

def list_worlds(sid):
    folder=safe_dir(sid); props=read_server_properties(sid); active=props.get("level-name","world")
    out=[]
    for p in sorted(folder.iterdir(),key=lambda x:x.name.casefold()):
        if p.is_dir() and not p.is_symlink() and (p.name==active or (p/"level.dat").exists()):
            size=0
            for item in p.rglob("*"):
                try:
                    if item.is_file() and not item.is_symlink(): size+=item.stat().st_size
                except OSError: pass
            out.append({"name":p.name,"active":p.name==active,"bytes":size})
    return out

def delete_world(sid,name):
    if server_running(sid): raise ValueError("Stop the server before deleting a world.")
    if not re.fullmatch(r"[A-Za-z0-9 _.-]{1,64}",name) or name in (".",".."): raise ValueError("Invalid world name")
    folder=safe_dir(sid); active=read_server_properties(sid).get("level-name","world")
    if name==active: raise ValueError("The active world cannot be deleted. Change level-name first and restart.")
    target=folder/name
    if not target.is_dir() or target.is_symlink() or not (target/"level.dat").exists(): raise ValueError("World folder not found or level.dat is missing")
    shutil.rmtree(target)
    return {"deleted":name}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args): print(fmt%args,flush=True)
    def auth(self):
        self.username=session_user(self)
        return self.username is not None
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/api/health": return send(self,200,{"ok":True,"name":"OMCP"})
        if path=="/api/setup/status": return send(self,200,{"setupRequired":len(load_users())==0,"accountCount":len(load_users())})
        if path=="/" or path=="/index.html":
            try: return send(self,200,WEB.read_bytes(),"text/html; charset=utf-8")
            except Exception: return send(self,404,{"error":"UI file missing"})
        if not self.auth(): return send(self,401,{"error":"Admin key required"})
        try:
            if path=="/api/users":
                if load_users().get(self.username,{}).get("role")!="admin": return send(self,403,{"error":"Admin permission required"})
                return send(self,200,{"users":[{"username":u,"role":v.get("role","user")} for u,v in load_users().items()]})
            if path=="/api/me":
                u=load_users().get(self.username)
                if not u: return send(self,401,{"error":"Account no longer exists"})
                return send(self,200,{"user":{"username":self.username,"role":u.get("role","user")}})
            if path=="/api/servers": return send(self,200,{"servers":servers()})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/properties",path)
            if x: return send(self,200,{"properties":read_server_properties(x.group(1)),"running":server_running(x.group(1))})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/worlds",path)
            if x: return send(self,200,{"worlds":list_worlds(x.group(1)),"running":server_running(x.group(1))})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/sftp",path)
            if x: return send(self,200,sftp_info(x.group(1)))
            x=re.fullmatch(r"/api/software/([a-z]+)/versions",path)
            if x: return send(self,200,{"software":x.group(1),"versions":software_versions(x.group(1))})
            if path=="/api/metrics":
                m={}
                for line in Path("/proc/meminfo").read_text().splitlines():
                    k,v=line.split(":",1); m[k]=int(v.strip().split()[0])*1024
                total=m.get("MemTotal",0); used=total-m.get("MemAvailable",0)
                return send(self,200,{"memoryTotal":total,"memoryUsed":used,"cpuCount":os.cpu_count() or 1})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/tunnel",path)
            if x: return send(self,200,tunnel_info(x.group(1)))
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/metrics",path)
            if x: return send(self,200,server_metrics(x.group(1)))
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/logs",path)
            if x:
                sid=x.group(1); f=safe_dir(sid)/"console.log"
                online=server_running(sid)
                logs=f.read_text(errors="replace")[-80000:] if online and f.exists() else ""
                plugin_dir=safe_dir(sid)/"plugins"
                installed=sorted(p.stem for p in plugin_dir.glob("*.jar") if p.is_file() and not p.is_symlink()) if plugin_dir.is_dir() else []
                enabled=set(re.findall(r"Enabling\s+([^\s]+)",logs))
                failed=set(re.findall(r"(?:Could not load|Failed to load|Error loading)\s+(?:plugin\s+)?([A-Za-z0-9_.-]+)",logs,re.I))
                return send(self,200,{"status":"running" if online else "offline","logs":logs,"plugins":{"installed":len(installed),"enabled":len(enabled),"failed":len(failed),"names":installed}})
            if path=="/api/backups/google/config":
                cfg=load_backup_config(); drive=cfg.get("google_drive",{})
                return send(self,200,{"configured":google_drive_configured(cfg),"clientIdSaved":bool(drive.get("client_id")),"clientSecretSaved":bool(drive.get("client_secret")),"refreshTokenSaved":bool(drive.get("refresh_token")),"folderId":drive.get("folder_id","")})
            sx=re.fullmatch(r"/api/servers/([a-f0-9]{8})/backup/schedule",path)
            if sx:
                cfg=load_backup_config(); item=cfg.get("schedules",{}).get(sx.group(1),{})
                return send(self,200,{"schedule":item,"driveConfigured":google_drive_configured(cfg)})
            if path=="/api/backups":
                dest=ROOT/"backups"; dest.mkdir(exist_ok=True)
                items=[]
                for f in sorted(dest.glob("*.zip"),key=lambda p:p.stat().st_mtime,reverse=True):
                    if f.is_file() and not f.is_symlink():
                        items.append({"name":f.name,"bytes":f.stat().st_size,"created":int(f.stat().st_mtime)})
                return send(self,200,{"backups":items})
            x=re.fullmatch(r"/api/backups/([a-f0-9]{8}-[0-9]{8}-[0-9]{6}\.zip)/download",path)
            if x:
                f=(ROOT/"backups"/x.group(1)).resolve()
                if f.parent!=(ROOT/"backups").resolve() or not f.is_file() or f.is_symlink(): raise ValueError("Backup not found")
                raw=f.read_bytes()
                self.send_response(200); self.send_header("Content-Type","application/zip")
                self.send_header("Content-Disposition",'attachment; filename="'+f.name+'"')
                self.send_header("Content-Length",str(len(raw))); self.send_header("Cache-Control","no-store")
                self.end_headers(); self.wfile.write(raw); return
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/settings",path)
            if x:
                sid=x.group(1); meta=json.loads((safe_dir(sid)/"omcp.json").read_text())
                return send(self,200,{"name":meta.get("name","Minecraft"),"memory":meta.get("memory",2),"memoryMax":physical_ram_gb(),"javaPath":meta.get("javaPath",""),"runtimes":java_runtimes()})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/plugins/search",path)
            if x:
                sid=x.group(1); meta=json.loads((safe_dir(sid)/"omcp.json").read_text())
                if meta.get("software","paper") not in ("paper","purpur","folia","spigot"): raise ValueError("Plugin installation is available for Paper, Purpur, Folia and Spigot game servers only")
                q=parse_qs(urlparse(self.path).query).get("q",[""])[0]
                return send(self,200,plugin_search(q))
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/download",path)
            if x:
                folder=safe_dir(x.group(1)); rel=parse_qs(urlparse(self.path).query).get("path",[""])[0]
                f=server_path(folder,rel)
                if not f.is_file() or f.is_symlink(): raise ValueError("Regular file not found")
                size=f.stat().st_size
                filename=re.sub(r"[^A-Za-z0-9_. -]","_",f.name)
                self.send_response(200); self.send_header("Content-Type","application/octet-stream")
                self.send_header("Content-Disposition",'attachment; filename="'+filename+'"')
                self.send_header("Content-Length",str(size)); self.send_header("Cache-Control","no-store")
                self.end_headers()
                with f.open("rb") as stream:
                    shutil.copyfileobj(stream,self.wfile)
                return
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/files",path)
            if x:
                folder=safe_dir(x.group(1)); rel=self.headers.get("X-OMCP-Path","")
                f=(folder/rel).resolve()
                if folder not in f.parents and f!=folder: raise ValueError("Path outside server")
                if f.is_symlink(): raise ValueError("Symlink blocked")
                if f.is_dir(): return send(self,200,{"entries":[{"name":a.name,"directory":a.is_dir(),"size":a.stat().st_size if a.is_file() else 0} for a in sorted(f.iterdir(),key=lambda p:(not p.is_dir(),p.name.casefold())) if not a.is_symlink()]})
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
                    users[username]={"role":"admin","created":int(time.time()),"passwordless_admin":True}
                    save_users(users)
                else:
                    canonical=next((u for u in users if u.strip().casefold()==username.strip().casefold()),None)
                    record=users.get(canonical) if canonical else None
                    if not record: return send(self,401,{"error":"Unknown username. Check that this is the same VPS/data folder where your admin account was created."})
                    if record.get("role")!="admin" and not password_ok(password,record):
                        return send(self,401,{"error":"Incorrect username or password."})
                    username=canonical
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
                if any(u.casefold()==username.casefold() for u in users): return send(self,409,{"error":"Username already exists"})
                username=username.lower()
                users[username]={"password":password_hash(password),"role":"user","created":int(time.time())}
                save_users(users)
                return send(self,201,{"user":{"username":username,"role":"user"}})
            except Exception as e: return send(self,400,{"error":str(e)})
        try:
            d=body(self)
            tx=re.fullmatch(r"/api/servers/([a-f0-9]{8})/tunnel/(start|stop)",path)
            if tx:
                sid,action=tx.groups()
                if action=="start": return send(self,200,start_tunnel(sid,str(d.get("provider","pinggy"))))
                return send(self,200,stop_tunnel(sid))
            if path=="/api/backups/google/config":
                if load_users().get(self.username,{}).get("role")!="admin": return send(self,403,{"error":"Admin permission required to change cloud credentials"})
                cfg=load_backup_config(); drive=cfg.setdefault("google_drive",{})
                for key in ("client_id","client_secret","refresh_token","folder_id"):
                    value=str(d.get(key,"")).strip()
                    if value: drive[key]=value
                if d.get("clear"):
                    cfg["google_drive"]={}
                save_backup_config(cfg)
                return send(self,200,{"configured":google_drive_configured(cfg)})
            bs=re.fullmatch(r"/api/servers/([a-f0-9]{8})/backup/schedule",path)
            if bs:
                sid=bs.group(1); enabled=bool(d.get("enabled",False)); interval=int(d.get("interval_minutes",360))
                if not 15<=interval<=10080: raise ValueError("Backup interval must be between 15 minutes and 7 days.")
                cfg=load_backup_config()
                provider=str(d.get("provider","google_drive"))\n                if provider not in ("google_drive","local"): raise ValueError("Unsupported backup destination")\n                if enabled and provider=="google_drive" and not google_drive_configured(cfg): raise ValueError("Connect Google Drive before enabling Google Drive backups, or choose Local VPS storage.")
                schedules=cfg.setdefault("schedules",{}); old=schedules.get(sid,{})
                schedules[sid]={"enabled":enabled,"interval_minutes":interval,"provider":provider,"last_run":old.get("last_run",0),"last_status":old.get("last_status","Not run yet"),"last_file_id":old.get("last_file_id","")}
                save_backup_config(cfg)
                return send(self,200,{"saved":True,"schedule":schedules[sid],"driveConfigured":google_drive_configured(cfg)})
            if path=="/api/servers": return send(self,201,{"server":create(d)})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/properties",path)
            if x: return send(self,200,{"saved":True,"properties":write_server_properties(x.group(1),d.get("properties",{})),"apply":"restart"})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/worlds/delete",path)
            if x: return send(self,200,delete_world(x.group(1),str(d.get("name",""))))
            mx=re.fullmatch(r"/api/servers/([a-f0-9]{8})/minekube/install",path)
            if mx: return send(self,200,enable_minekube(mx.group(1),str(d.get("endpoint",""))))
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/sftp/reset",path)
            if x: return send(self,200,reset_sftp_password(x.group(1)))
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/plugins/install",path)
            if x: return send(self,200,install_plugin(x.group(1),str(d.get("projectId","")),str(d.get("source","modrinth"))))
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/settings",path)
            if x:
                sid=x.group(1); folder=safe_dir(sid); meta=json.loads((folder/"omcp.json").read_text())
                name=str(d.get("name",meta.get("name","Minecraft"))).strip()
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{1,31}",name): raise ValueError("Server name must be 2-32 characters: letters, numbers, spaces, _ or -")
                mem=int(d.get("memory",meta.get("memory",2)))
                maximum=physical_ram_gb()
                if not 1<=mem<=maximum: raise ValueError("Memory must be between 1 GB and available host RAM ("+str(maximum)+" GB)")
                java_path=str(d.get("javaPath","")).strip()
                valid={r["path"] for r in java_runtimes()}
                if java_path and java_path not in valid: raise ValueError("Selected Java runtime is not installed. Refresh the page and choose an available runtime.")
                meta["name"]=name; meta["memory"]=mem
                if java_path: meta["javaPath"]=java_path
                else: meta.pop("javaPath",None)
                atomic_json(folder/"omcp.json",meta)
                check=json.loads((folder/"omcp.json").read_text())
                return send(self,200,{"saved":True,"name":check["name"],"memory":check["memory"],"javaPath":check.get("javaPath",""),"apply":"next-start"})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/reinstall",path)
            if x:
                sid=x.group(1); folder=safe_dir(sid); meta=json.loads((folder/"omcp.json").read_text())
                if server_running(sid): raise ValueError("Stop the server before reinstalling.")
                dest=ROOT/"backups"; dest.mkdir(exist_ok=True)
                backup=dest/(sid+"-"+time.strftime("%Y%m%d-%H%M%S")+".zip")
                with zipfile.ZipFile(backup,"w",zipfile.ZIP_DEFLATED) as z:
                    for f in folder.rglob("*"):
                        if f.is_file() and not f.is_symlink(): z.write(f,f.relative_to(folder))
                temp=folder/"server.jar.new"
                try:
                    download_server_jar(meta.get("software","paper"),meta["version"],temp)
                    os.replace(temp,folder/"server.jar")
                finally:
                    if temp.exists(): temp.unlink()
                return send(self,200,{"reinstalled":True,"backup":backup.name})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/upgrade",path)
            if x:
                result=upgrade_server(x.group(1),str(d.get("version","")).strip(),str(d.get("software","")).strip() or None,bool(d.get("wipe",False)))
                return send(self,200,result)
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/(start|stop|restart|command|backup)",path)
            if x:
                sid,act=x.groups()
                if act=="start": result=start(sid)
                elif act=="stop": result=stop(sid)
                elif act=="restart": stop(sid); result=start(sid)
                elif act=="command":
                    cmd=str(d.get("command",""))
                    if not server_running(sid): raise ValueError("Server stopped")
                    if not cmd or len(cmd)>500 or "\n" in cmd or "\r" in cmd: raise ValueError("Invalid command")
                    if not send_console_command(sid,cmd): raise ValueError("Console input is unavailable. Restart this server once to enable persistent console commands.")
                    result={"sent":True}
                else:
                    result=create_live_backup(sid)
                    result.pop("path",None)
                return send(self,200,result)
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/rename",path)
            if x:
                folder=safe_dir(x.group(1)); old=server_path(folder,str(d.get("path","")))
                name=str(d.get("name","")).strip()
                if not old.exists() or old.is_symlink(): raise ValueError("File or folder not found")
                if not name or name in (".","..") or "/" in name or "\\" in name or len(name)>180: raise ValueError("Enter a valid new name without path separators")
                new=old.with_name(name)
                if new.exists(): raise ValueError("A file or folder with that name already exists")
                if new.parent.resolve()!=old.parent.resolve(): raise ValueError("Rename must stay in the same folder")
                old.rename(new)
                return send(self,200,{"renamed":True,"path":str(new.relative_to(folder))})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/(mkdir|upload)",path)
            if x:
                sid,kind=x.groups(); folder=safe_dir(sid); target=server_path(folder,d.get("path",""))
                if kind=="mkdir":
                    target.mkdir(parents=True,exist_ok=True)
                    return send(self,200,{"created":True,"path":str(target.relative_to(folder))})
                chunk=base64.b64decode(str(d.get("chunk","")),validate=True)
                if len(chunk)>600000: raise ValueError("Upload chunk too large")
                offset=int(d.get("offset",0))
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.is_symlink(): raise ValueError("Symlink blocked")
                if d.get("truncate"):
                    if offset!=0: raise ValueError("First upload chunk must start at offset 0")
                    mode="wb"
                else:
                    if not target.exists() or target.stat().st_size!=offset: raise ValueError("Upload offset mismatch; restart the upload")
                    mode="ab"
                with target.open(mode) as out: out.write(chunk)
                return send(self,200,{"uploaded":len(chunk),"size":target.stat().st_size})
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/files",path)
            if x:
                folder=safe_dir(x.group(1)); f=server_path(folder,str(d.get("path","")))
                if f.exists() and (f.is_symlink() or not f.is_file()): raise ValueError("Only regular files can be edited")
                raw=str(d.get("content","")).encode("utf-8")
                if len(raw)>900000: raise ValueError("File too large (maximum 900 KB)")
                f.parent.mkdir(parents=True,exist_ok=True)
                tmp=f.with_name(f.name+".omcp-tmp")
                try:
                    with tmp.open("wb") as out:
                        out.write(raw); out.flush(); os.fsync(out.fileno())
                    if f.exists(): os.chmod(tmp,f.stat().st_mode & 0o777)
                    os.replace(tmp,f)
                finally:
                    if tmp.exists(): tmp.unlink()
                if not f.is_file() or f.read_bytes()!=raw: raise ValueError("Save verification failed: the file on disk does not match the editor")
                return send(self,200,{"saved":True,"bytes":len(raw),"path":str(f.relative_to(folder))})
            return send(self,404,{"error":"Not found"})
        except Exception as e: return send(self,400,{"error":str(e)})
    def do_DELETE(self):
        if not self.auth(): return send(self,401,{"error":"Login required"})
        path=urlparse(self.path).path
        sm=re.fullmatch(r"/api/servers/([a-f0-9]{8})",path)
        if sm:
            try:
                sid=sm.group(1); d=body(self); folder=safe_dir(sid)
                if server_running(sid): raise ValueError("Stop the server before deleting it.")
                if d.get("confirm")!="DELETE": raise ValueError('Type DELETE to confirm permanent server removal.')
                dest=ROOT/"backups"; dest.mkdir(exist_ok=True)
                backup=dest/(sid+"-before-delete-"+time.strftime("%Y%m%d-%H%M%S")+".zip")
                with zipfile.ZipFile(backup,"w",zipfile.ZIP_DEFLATED,compresslevel=3) as z:
                    for f in folder.rglob("*"):
                        if f.is_file() and not f.is_symlink(): z.write(f,f.relative_to(folder))
                shutil.rmtree(folder)
                return send(self,200,{"deleted":sid,"backup":backup.name})
            except Exception as e: return send(self,400,{"error":str(e)})
        fm=re.fullmatch(r"/api/servers/([a-f0-9]{8})/files",path)
        if fm:
            try:
                d=body(self); folder=safe_dir(fm.group(1))
                paths=d.get("paths") if isinstance(d.get("paths"),list) else [d.get("path","")]
                if not paths or len(paths)>200: raise ValueError("Select between 1 and 200 files or folders")
                targets=[]
                for rel in paths:
                    target=server_path(folder,str(rel))
                    if target==folder or not target.exists() or target.is_symlink(): raise ValueError("Invalid file or folder: "+str(rel))
                    if target.is_dir():
                        for child in target.rglob("*"):
                            if child.is_symlink(): raise ValueError("Folder contains a symlink; refusing recursive delete")
                    targets.append(target)
                unique=[]
                for target in sorted(targets,key=lambda p:len(p.parts)):
                    if not any(parent==target or parent in target.parents for parent in unique): unique.append(target)
                for target in unique:
                    if target.is_dir(): shutil.rmtree(target)
                    else: target.unlink()
                return send(self,200,{"deleted":len(unique)})
            except Exception as e: return send(self,400,{"error":str(e)})
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

start_sftp_service()
threading.Thread(target=backup_scheduler_loop,daemon=True,name="omcp-backup-scheduler").start()
print("OMCP listening at http://%s:%s"%(HOST,PORT),flush=True)
ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
