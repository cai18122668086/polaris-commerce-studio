"""Prepare an immutable video-only overlay from inspected live configuration.

Contains inherited secrets only in server-local 0600 files. It never applies
Compose, changes users, restarts existing services, or performs migrations.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,os,re,secrets,subprocess,sys
from pathlib import Path
from typing import Any

VIDEO_KEYS = {"POLARIS_VIDEO_PROVIDERS_ENABLED", "POLARIS_QUANYU_API_KEY", "POLARIS_WUYE_API_KEY", "POLARIS_VIDEO_TAO_TTS_ENABLED", "POLARIS_TAO_API_KEY", "POLARIS_VIDEO_TAO_TTS_MODEL", "POLARIS_VIDEO_SCRIPT_PLANNING_ENABLED", "POLARIS_VIDEO_SCRIPT_API_KEY", "POLARIS_VIDEO_SCRIPT_BASE_URL", "POLARIS_VIDEO_SCRIPT_MODEL", "POLARIS_VIDEO_EXTRACT_ENABLED", "POLARIS_VIDEO_EXTRACT_API_KEY", "POLARIS_VIDEO_COSYVOICE_ENABLED", "POLARIS_VIDEO_COSYVOICE_API_KEY", "POLARIS_VIDEO_COSYVOICE_PLATFORM", "POLARIS_VIDEO_COSYVOICE_WORKSPACE_ID", "POLARIS_VIDEO_COSYVOICE_MODEL"}

def escaped(value: Any) -> Any:
    if isinstance(value,str): return value.replace("$","$$")
    if isinstance(value,list): return [escaped(item) for item in value]
    if isinstance(value,dict): return {key:escaped(item) for key,item in value.items()}
    return value

def caddy_with_video(source: str) -> str:
    marker="\thandle @api {"
    if source.count(marker)!=1 or "reverse_proxy video-api:8000" in source:
        raise ValueError("Unexpected or already-updated Caddy input")
    body="\trequest_body {\n\t\tmax_size 25MB\n\t}"
    if source.count(body)!=1: raise ValueError("Unexpected primary body limit")
    source=source.replace(body,"\t@video_request path /api/v1/video-studio/*\n\trequest_body @video_request {\n\t\tmax_size 55MB\n\t}\n\t@standard_request not path /api/v1/video-studio/*\n\trequest_body @standard_request {\n\t\tmax_size 25MB\n\t}",1)
    return source.replace(marker,marker+"\n\t\t@video_studio path /api/v1/video-studio/*\n\t\thandle @video_studio {\n\t\t\treverse_proxy video-api:8000\n\t\t}",1)

def private(path: Path,data: str) -> None:
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as stream: stream.write(data)

def inspect(role: str) -> dict[str,Any]:
    return json.loads(subprocess.check_output(["docker","inspect","polaris-production-"+role+"-1"]))[0]

def observed_service(live: dict[str,Any],config: dict[str,Any]) -> dict[str,Any]:
    role=live["Config"]["Labels"]["com.docker.compose.service"]
    service=copy.deepcopy(config["services"][role])
    service.pop("depends_on",None);service.pop("build",None)
    service["image"]=live["Image"];service["pull_policy"]="never"
    service["environment"]=escaped(dict(item.split("=",1) for item in live["Config"]["Env"]))
    service["command"]=escaped(live["Config"].get("Cmd"))
    service["entrypoint"]=escaped(live["Config"].get("Entrypoint"))
    service["networks"]={name:{"aliases":value.get("Aliases") or []} for name,value in live["NetworkSettings"]["Networks"].items()}
    service["volumes"]=[{"type":m["Type"],"source":m.get("Name") if m["Type"]=="volume" else m["Source"],"target":m["Destination"],"read_only":not m["RW"]} for m in live["Mounts"] if m["Type"] in {"bind","volume"}]
    return service

def prepare(revision: str,backend: str,frontend: str,video: dict[str,str],expected: dict[str,Any]) -> dict[str,Any]:
    if not re.fullmatch(r"[0-9a-f]{40}",revision): raise ValueError("Full revision required")
    if not all(re.fullmatch(r"sha256:[0-9a-f]{64}",v) for v in [backend,frontend]): raise ValueError("Immutable images required")
    if set(video)-VIDEO_KEYS: raise ValueError("Unsupported runtime setting")
    if video.get("POLARIS_VIDEO_COSYVOICE_ENABLED")!="true" or not video.get("POLARIS_VIDEO_COSYVOICE_API_KEY"): raise ValueError("Configured voice runtime required")
    root=Path("/etc/polaris/video-studio-"+revision[:12]);root.mkdir(mode=0o700)
    services={};live={}
    for role in ["api","frontend","caddy"]:
        live[role]=inspect(role)
        if live[role]["Image"]!=expected["services"][role]["image"]: raise ValueError("Live baseline changed: "+role)
        source=live[role]["Config"]["Labels"]["com.docker.compose.project.config_files"]
        config=json.loads(subprocess.check_output(["docker","compose","-f",source,"config","--format","json"]))
        services[role]=observed_service(live[role],config)
    baseline=copy.deepcopy(services)
    old_caddy=next(m["source"] for m in services["caddy"]["volumes"] if m["target"]=="/etc/caddy/Caddyfile")
    old=Path(old_caddy).read_text();new=caddy_with_video(old)
    caddy=Path("/opt/polaris/releases")/revision/"deploy/Caddyfile.video-studio"
    private(caddy,new);private(root/"Caddyfile.before",old)
    for m in services["caddy"]["volumes"]:
        if m["target"]=="/etc/caddy/Caddyfile":m["source"]=str(caddy)
    api=services.pop("api");runtime=dict(item.split("=",1) for item in live["api"]["Config"]["Env"])
    runtime.update(video)
    runtime.update(POLARIS_VIDEO_MEDIA_DIR="/app/.data/video-studio",POLARIS_AUTO_PROCESS_JOBS="false",POLARIS_ECOMMERCE_STARTUP_RECOVERY_ENABLED="false",POLARIS_ECOMMERCE_LOGIN_ENABLED="false",POLARIS_RETENTION_ENABLED="false",POLARIS_AURORA_WORK_ROOT="/tmp/aurora-main-image",POLARIS_VIDEO_EDITING_HANDOFF_SECRET=secrets.token_urlsafe(48))
    api.update(image=backend,environment=escaped(runtime),volumes=[{"type":"volume","source":"polaris_video_studio_data","target":"/app/.data/video-studio"}],mem_limit="1610612736",cpus=1.0)
    api["networks"]={name:{"aliases":["video-api"]} for name in api["networks"]}
    api["labels"]={**api.get("labels",{}),"com.polaris.video.revision":revision}
    services["video-api"]=api;services["frontend"]["image"]=frontend
    services["frontend"]["labels"]={**services["frontend"].get("labels",{}),"com.polaris.video.revision":revision}
    networks={name:{"name":name,"external":True} for service in services.values() for name in service["networks"]}
    volumes={m["source"]:{"name":m["source"],"external":True} for service in services.values() for m in service.get("volumes",[]) if m["type"]=="volume"}
    volumes["polaris_video_studio_data"]={"name":"polaris-production_video_studio_data","external":True}
    active={"name":"polaris-production","services":services,"networks":networks,"volumes":volumes}
    previous={"name":"polaris-production","services":{k:baseline[k] for k in ["frontend","caddy"]},"networks":networks,"volumes":{k:v for k,v in volumes.items() if k!="polaris_video_studio_data"}}
    private(root/"active.compose.private.json",json.dumps(active,indent=2));private(root/"rollback.compose.private.json",json.dumps(previous,indent=2))
    if any("\n" in str(v) for v in runtime.values()): raise ValueError("Multiline runtime values unsupported")
    private(root/"runtime.env","\n".join(k+"="+str(v) for k,v in runtime.items())+"\n")
    caddy_env=dict(item.split("=",1) for item in live["caddy"]["Config"]["Env"])
    private(root/"caddy.env","\n".join(k+"="+str(v) for k,v in caddy_env.items())+"\n")
    manifest={"revision":revision,"backend_image":backend,"frontend_image":frontend,"baseline":{k:{"id":v["Id"],"image":v["Image"]} for k,v in live.items()},"caddy_before_sha256":hashlib.sha256(old.encode()).hexdigest(),"caddy_after_sha256":hashlib.sha256(new.encode()).hexdigest(),"root":str(root),"only_gray_email":"1474953130@qq.com"}
    private(root/"manifest.json",json.dumps(manifest,indent=2))
    subprocess.run(["docker","compose","-f",str(root/"active.compose.private.json"),"config","--quiet"],check=True)
    subprocess.run(["docker","compose","-f",str(root/"rollback.compose.private.json"),"config","--quiet"],check=True)
    return manifest

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--revision",required=True);parser.add_argument("--backend-image",required=True);parser.add_argument("--frontend-image",required=True);parser.add_argument("--baseline",required=True);args=parser.parse_args()
    manifest=prepare(args.revision,args.backend_image,args.frontend_image,json.load(sys.stdin),json.loads(Path(args.baseline).read_text()))
    print(json.dumps(manifest))
