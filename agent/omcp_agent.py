#!/usr/bin/env python3
import base64, json, os, re, secrets, shutil, subprocess, threading, urllib.request, zipfile, time, socket
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

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
TUNNELS={}; TUNNEL_LOCK=threading.RLock(); METRIC_PREV={}

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
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{1,23}',name): raise ValueError('Name must be 2-24 letters, numbers, _ or -')
    if not re.fullmatch(r'\d{1,2}\.\d{1,2}(?:\.\d{1,2})?',ver): raise ValueError('Invalid Minecraft version')
    if software not in ('paper','vanilla','fabric'): raise ValueError('This build currently supports Paper, Vanilla and Fabric. Forge, Spigot and Velocity are not available yet.')
    if not 1<=mem<=physical_ram_gb() or not 1024<=port<=65535: raise ValueError('RAM must be between 1 GB and host RAM ('+str(physical_ram_gb())+' GB); port 1024-65535')
    if not d.get('eulaAccepted'): raise ValueError('Accept the Minecraft EULA first')
    if not shutil.which('java'): raise ValueError('Java runtime not found')
    if any(s['name'].lower()==name.lower() or s['port']==port for s in servers()): raise ValueError('Name or port already used')
    sid=secrets.token_hex(4); folder=safe_dir(sid); folder.mkdir(mode=0o750)
    try:
        jar=folder/'server.jar'
        if software=='paper':
            api='https://fill.papermc.io/v3/projects/paper/versions/'+ver+'/builds?channel=STABLE&limit=1'
            req=urllib.request.Request(api,headers={'User-Agent':'OMCP/0.3 (https://github.com/nmronion-alt/onion-hub)','Accept':'application/json'})
            try:
                with urllib.request.urlopen(req,timeout=30) as r: builds=json.load(r)
            except Exception as e: raise ValueError('Paper download API failed for '+ver+': '+str(e))
            stable=next((x for x in builds if x.get('channel')=='STABLE' and x.get('downloads',{}).get('server:default',{}).get('url')),None)
            if not stable: raise ValueError('No stable Paper build found for Minecraft '+ver+'. Check that this Paper version exists.')
            url=stable['downloads']['server:default']['url']
        elif software=='fabric':
            headers={'User-Agent':'OMCP/0.3','Accept':'application/json'}
            try:
                with urllib.request.urlopen(urllib.request.Request('https://meta.fabricmc.net/v2/versions/loader/'+ver,headers=headers),timeout=30) as r: loaders=json.load(r)
                with urllib.request.urlopen(urllib.request.Request('https://meta.fabricmc.net/v2/versions/installer',headers=headers),timeout=30) as r: installers=json.load(r)
            except Exception as e: raise ValueError('Fabric metadata request failed: '+str(e))
            loader=next((x['loader']['version'] for x in loaders if x.get('loader',{}).get('stable')),None)
            installer=next((x['version'] for x in installers if x.get('stable')),None)
            if not loader or not installer: raise ValueError('No stable Fabric loader/installer found for '+ver)
            url='https://meta.fabricmc.net/v2/versions/loader/'+ver+'/'+loader+'/'+installer+'/server/jar'
        else:
            req=urllib.request.Request('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json',headers={'User-Agent':'OMCP/0.2'})
            with urllib.request.urlopen(req,timeout=30) as r: manifest=json.load(r)
            item=next((x for x in manifest['versions'] if x['id']==ver and x['type'] in ('release','snapshot')),None)
            if not item: raise ValueError('Minecraft version not found in official manifest')
            with urllib.request.urlopen(urllib.request.Request(item['url'],headers={'User-Agent':'OMCP/0.2'}),timeout=30) as r: meta=json.load(r)
            url=meta.get('downloads',{}).get('server',{}).get('url')
            if not url: raise ValueError('No official Vanilla server download for this version')
        req=urllib.request.Request(url,headers={'User-Agent':'OMCP/0.2 (https://github.com/nmronion-alt/onion-hub)'})
        with urllib.request.urlopen(req,timeout=180) as r, jar.open('wb') as out: shutil.copyfileobj(r,out)
        (folder/'eula.txt').write_text('eula=true\n')
        (folder/'server.properties').write_text('server-port='+str(port)+'\n')
        (folder/'omcp.json').write_text(json.dumps({'name':name,'version':ver,'software':software,'memory':mem,'port':port},indent=2))
        return next(s for s in servers() if s['id']==sid)
    except Exception:
        shutil.rmtree(folder,ignore_errors=True)
        raise

def download_server_jar(software, ver, destination):
    headers={"User-Agent":"OMCP/0.4 (https://github.com/nmronion-alt/onion-hub)","Accept":"application/json"}
    if software=="paper":
        api="https://fill.papermc.io/v3/projects/paper/versions/"+ver+"/builds?channel=STABLE&limit=1"
        with urllib.request.urlopen(urllib.request.Request(api,headers=headers),timeout=30) as r: builds=json.load(r)
        stable=next((x for x in builds if x.get("channel")=="STABLE" and x.get("downloads",{}).get("server:default",{}).get("url")),None)
        if not stable: raise ValueError("No stable Paper build found for Minecraft "+ver)
        url=stable["downloads"]["server:default"]["url"]
    elif software=="fabric":
        with urllib.request.urlopen(urllib.request.Request("https://meta.fabricmc.net/v2/versions/loader/"+ver,headers=headers),timeout=30) as r: loaders=json.load(r)
        with urllib.request.urlopen(urllib.request.Request("https://meta.fabricmc.net/v2/versions/installer",headers=headers),timeout=30) as r: installers=json.load(r)
        loader=next((x["loader"]["version"] for x in loaders if x.get("loader",{}).get("stable")),None)
        installer=next((x["version"] for x in installers if x.get("stable")),None)
        if not loader or not installer: raise ValueError("No stable Fabric loader found for "+ver)
        url="https://meta.fabricmc.net/v2/versions/loader/"+ver+"/"+loader+"/"+installer+"/server/jar"
    elif software=="vanilla":
        with urllib.request.urlopen(urllib.request.Request("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",headers=headers),timeout=30) as r: manifest=json.load(r)
        item=next((x for x in manifest["versions"] if x["id"]==ver and x["type"] in ("release","snapshot")),None)
        if not item: raise ValueError("Minecraft version not found in official manifest")
        with urllib.request.urlopen(urllib.request.Request(item["url"],headers=headers),timeout=30) as r: meta=json.load(r)
        url=meta.get("downloads",{}).get("server",{}).get("url")
        if not url: raise ValueError("No official Vanilla server download for "+ver)
    else: raise ValueError("Unsupported server software")
    req=urllib.request.Request(url,headers={"User-Agent":headers["User-Agent"]})
    with urllib.request.urlopen(req,timeout=180) as r, destination.open("wb") as out: shutil.copyfileobj(r,out)
    if destination.stat().st_size<100000 or not zipfile.is_zipfile(destination):
        destination.unlink(missing_ok=True)
        raise ValueError("Downloaded server jar failed validation")

def upgrade_server(sid, ver):
    folder=safe_dir(sid); meta=json.loads((folder/"omcp.json").read_text())
    if not re.fullmatch(r"\d{1,2}\.\d{1,2}(?:\.\d{1,2})?",ver): raise ValueError("Invalid Minecraft version")
    if server_running(sid): raise ValueError("Stop the server before changing its version")
    software=meta.get("software","paper")
    dest=ROOT/"backups"; dest.mkdir(exist_ok=True)
    backup=dest/(sid+"-"+time.strftime("%Y%m%d-%H%M%S")+".zip")
    with zipfile.ZipFile(backup,"w",zipfile.ZIP_DEFLATED) as z:
        for f in folder.rglob("*"):
            if f.is_file() and not f.is_symlink(): z.write(f,f.relative_to(folder))
    temp=folder/"server.jar.new"
    try:
        download_server_jar(software,ver,temp)
        os.replace(temp,folder/"server.jar")
        meta["version"]=ver
        (folder/"omcp.json").write_text(json.dumps(meta,indent=2))
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
    if not java or not os.path.isfile(java) or not os.access(java,os.X_OK): raise ValueError("Selected Java runtime is missing or not executable. Choose a valid Java runtime in Server Settings.")
    jar=folder/("server.jar" if (folder/"server.jar").is_file() else "paper.jar")
    if not jar.is_file() or jar.stat().st_size<100000: raise ValueError("Server JAR is missing or incomplete. Check the server files or use Reinstall server.")
    memory=int(m.get("memory",2))
    if memory<1 or memory>physical_ram_gb(): raise ValueError("Saved RAM setting is invalid for this host. Open Server Settings and save a valid memory limit.")
    log_path=folder/"console.log"
    try:
        with log_path.open("wb",buffering=0) as log:
            log.write(("\n[OMCP] Starting with Java: "+java+" | RAM: "+str(memory)+" GB | JAR: "+jar.name+"\n").encode())
            p=subprocess.Popen([java,f"-Xms{min(1,memory)}G",f"-Xmx{memory}G","-jar",str(jar),"nogui"],cwd=folder,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    except Exception as e:
        raise ValueError("Could not launch Minecraft: "+str(e))
    PROCS[sid]=p
    time.sleep(0.25)
    if p.poll() is not None:
        tail=log_path.read_text(errors="replace")[-1800:] if log_path.exists() else ""
        raise ValueError("Minecraft exited during startup (exit "+str(p.returncode)+"). Console: "+tail[-1200:])
    return {"status":"starting","pid":p.pid}

def stop(sid):
    p=PROCS.get(sid)
    tracked=p is not None and p.poll() is None
    pids=server_processes(sid)
    if not pids:
        (safe_dir(sid)/"console.log").unlink(missing_ok=True)
        return {"status":"stopped"}
    try:
        if tracked and p.stdin:
            p.stdin.write(b"stop\n"); p.stdin.flush()
            try: p.wait(timeout=45)
            except subprocess.TimeoutExpired: p.terminate()
        else:
            # A post-restart orphan has no console pipe; SIGTERM runs JVM shutdown hooks.
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
        return {"status":"stopped"}
    except Exception as e:
        if isinstance(e,ValueError): raise
        raise ValueError("Could not stop Minecraft cleanly: "+str(e))

def start_tunnel(sid, provider):
    folder=safe_dir(sid); meta=json.loads((folder/"omcp.json").read_text())
    if provider!="pinggy": raise ValueError("Bore and Minekube need provider-specific setup/credentials and are not enabled yet. Select Pinggy for the available adapter.")
    if not server_running(sid): raise ValueError("Start the Minecraft server before starting its TCP tunnel.")
    ssh=shutil.which("ssh")
    if not ssh: raise ValueError("OpenSSH client is not installed")
    port=int(meta.get("port",25565))
    ready=False
    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1",port),timeout=0.5): ready=True
            break
        except OSError: time.sleep(0.5)
    if not ready: raise ValueError("Minecraft process exists, but port "+str(port)+" is not accepting TCP connections yet. Wait for the console to say Done, then retry.")
    with TUNNEL_LOCK:
        old=TUNNELS.get(sid)
        if old and old["proc"].poll() is None: raise ValueError("A tunnel is already running for this server")
        askpass=ROOT/"pinggy-askpass.sh"
        askpass.write_text("#!/bin/sh\nprintf '\\n'\n"); os.chmod(askpass,0o700)
        env=os.environ.copy(); env["SSH_ASKPASS"]=str(askpass); env["SSH_ASKPASS_REQUIRE"]="force"; env["DISPLAY"]=env.get("DISPLAY","omcp:0")
        cmd=[ssh,"-T","-p","443","-o","ConnectTimeout=20","-o","ConnectionAttempts=2","-o","RequestTTY=no","-o","BatchMode=no","-o","NumberOfPasswordPrompts=1","-o","PreferredAuthentications=keyboard-interactive,password","-o","PubkeyAuthentication=no","-o","StrictHostKeyChecking=accept-new","-o","ServerAliveInterval=20","-o","ServerAliveCountMax=3","-o","ExitOnForwardFailure=yes","-R0:127.0.0.1:"+str(meta["port"]),"tcp@free.pinggy.io"]
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
            return {"status":"running","provider":"pinggy","port":meta["port"],"address":entry["address"],"logs":"\\n".join(entry["lines"][-20:])}
        if proc.poll() is not None:
            time.sleep(0.2)
            detail="\\n".join(entry["lines"][-30:]) or "SSH exited without returning a tunnel address."
            raise ValueError("Pinggy tunnel process exited (code "+str(proc.returncode)+"). "+detail[-1800:])
        time.sleep(0.2)
    return {"status":"starting","provider":"pinggy","port":meta["port"],"address":entry["address"],"logs":"\\n".join(entry["lines"][-20:])}

def tunnel_info(sid):
    with TUNNEL_LOCK:
        entry=TUNNELS.get(sid)
        if not entry: return {"status":"stopped","provider":None,"address":None,"logs":""}
        p=entry["proc"]; alive=p.poll() is None
        status=("running" if entry["address"] else "starting") if alive else "stopped"
        return {"status":status,"provider":entry["provider"],"address":entry["address"],"logs":"\\n".join(entry["lines"][-30:])}

def stop_tunnel(sid):
    with TUNNEL_LOCK:
        entry=TUNNELS.get(sid)
        if not entry: return {"status":"stopped"}
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
    if meta.get("software","paper")!="paper": raise ValueError("The plugin installer currently supports Paper servers only.")
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
                return send(self,200,{"status":"running" if online else "offline","logs":f.read_text(errors="replace")[-20000:] if online and f.exists() else ""})
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
                if meta.get("software","paper")!="paper": raise ValueError("Plugin installer currently supports Paper servers only")
                q=parse_qs(urlparse(self.path).query).get("q",[""])[0]
                return send(self,200,plugin_search(q))
            x=re.fullmatch(r"/api/servers/([a-f0-9]{8})/download",path)
            if x:
                folder=safe_dir(x.group(1)); rel=parse_qs(urlparse(self.path).query).get("path",[""])[0]
                f=server_path(folder,rel)
                if not f.is_file() or f.is_symlink(): raise ValueError("Regular file not found")
                size=f.stat().st_size
                self.send_response(200); self.send_header("Content-Type","application/octet-stream")
                self.send_header("Content-Disposition",'attachment; filename="'+f.name.replace('"','')+'"')
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
            if path=="/api/servers": return send(self,201,{"server":create(d)})
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
                result=upgrade_server(x.group(1),str(d.get("version","")).strip())
                return send(self,200,result)
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
        fm=re.fullmatch(r"/api/servers/([a-f0-9]{8})/files",path)
        if fm:
            try:
                d=body(self); folder=safe_dir(fm.group(1)); target=server_path(folder,str(d.get("path","")))
                if not target.exists() or target.is_symlink(): raise ValueError("File or folder not found")
                if target.is_dir():
                    if any(target.iterdir()): raise ValueError("Folder is not empty")
                    target.rmdir()
                else: target.unlink()
                return send(self,200,{"deleted":True})
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

print("OMCP listening at http://%s:%s"%(HOST,PORT),flush=True)
ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
