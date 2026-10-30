"""Immutable Polaris suite release; runtime secrets never leave the server.

Build and prepare do not replace running applications. Activate requires an idle
queue, retained rollback images, a private database backup and exact baselines.
The additive migration records explicit processing consent without rewriting users or credits.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

REPO = Path(__file__).resolve().parents[2]
ROLES = ("api", "worker", "replica-api", "replica-worker", "detail-api",
         "detail-worker", "dispatcher", "frontend")
WORKERS = ("dispatcher", "worker", "replica-worker", "detail-worker")
APIS = ("api", "replica-api", "detail-api")
ENV = {**os.environ, "COMPOSE_IGNORE_ORPHANS": "true"}
OLD_SCHEMA = "20261030_0033"
NEW_SCHEMA = "20261030_0034"

spec = importlib.util.spec_from_file_location(
    "native_release_helpers", REPO / "deploy/release_replica_native.py")
assert spec and spec.loader
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def out(args, **kwargs):
    return subprocess.check_output(args, **kwargs)


def inspect(role):
    return json.loads(out(["docker", "inspect", "polaris-production-" + role + "-1"]))[0]


def sql(query):
    return out(["docker", "exec", "polaris-production-postgres-1", "psql", "-U",
        "polaris", "-d", "polaris", "-At", "-v", "ON_ERROR_STOP=1", "-c", query]).decode().strip()


def idle():
    assert sql("SELECT (SELECT count(*) FROM job_attempts WHERE status IN "
        "('claimed','running')) + (SELECT count(*) FROM jobs WHERE status IN "
        "('queued','planning','processing','cancelling')) + (SELECT count(*) FROM "
        "replica_documents WHERE status IN ('fetching','analysing'))") == "0", \
        "Work is active; defer without cancelling or retrying user tasks"


def healthy(role):
    for _ in range(75):
        row = inspect(role)
        if row["State"].get("Health", {}).get("Status") == "healthy":
            return row
        assert row["State"]["Status"] not in {"exited", "dead"}, role + " stopped"
        time.sleep(2)
    raise RuntimeError(role + " readiness timeout")


def protected():
    names = out(["docker", "ps", "-a", "--format", "{{.Names}}"]
    ).decode().splitlines()
    result = {}
    for name in names:
        if name not in {"polaris-production-" + role + "-1" for role in ROLES}:
            row = json.loads(out(["docker", "inspect", name]))[0]
            result[name] = {"id": row["Id"], "image": row["Image"]}
    return result


def compose(root, filename, *arguments):
    subprocess.run(["docker", "compose", "-f", str(root / filename), *arguments],
                   check=True, env=ENV)


def source_hashes():
    paths = []
    for folder in ("backend/app", "backend/skill_sources", "backend/source_manifests",
                   "backend/migrations"):
        paths.extend(path for path in (REPO / folder).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    return {path.relative_to(REPO / "backend").as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def build_base(role, live, root):
    image = json.loads(out(["docker", "image", "inspect", live["Image"]]))[0]
    layers = len(image["RootFS"]["Layers"])
    tag = "polaris/audit-base-" + role + ":" + live["Image"][7:19]
    if layers <= 80:
        subprocess.run(["docker", "tag", live["Image"], tag], check=True)
        return tag
    # The running root is read-only and Docker export omits all mounted volumes.
    # Reading its already-mounted filesystem avoids the old image's overlay
    # lowerdir limit. Runtime configuration is restored from inspect, below.
    assert live["HostConfig"]["ReadonlyRootfs"]
    current = inspect(role)
    assert (current["Id"], current["Image"]) == (live["Id"], live["Image"])
    tag = "polaris/audit-flat-" + role + ":" + live["Image"][7:19]
    existing = subprocess.run(["docker", "image", "inspect", tag], capture_output=True)
    if existing.returncode == 0:
        cached = json.loads(existing.stdout)[0]
        for path in Path("/etc/polaris").glob("audit-20261030-*/flattened-" + role + ".json"):
            proof = json.loads(path.read_text())
            if (
                proof["observed_image"] == live["Image"]
                and proof["flattened_image"] == cached["Id"]
                and proof.get("read_only_export") is True
                and proof.get("mounted_volumes_excluded") is True
                and len(cached["RootFS"]["Layers"]) == 1
            ):
                helpers.private(root / ("flattened-" + role + ".json"), proof)
                print(json.dumps({"reused_verified_base": role}), flush=True)
                return tag
    exporter = subprocess.Popen(["docker", "export", current["Id"]], stdout=subprocess.PIPE)
    try:
        flattened = out(["docker", "import", "-", tag], stdin=exporter.stdout).decode().strip()
    finally:
        if exporter.stdout:
            exporter.stdout.close()
        assert exporter.wait() == 0, "Read-only image export failed"
    helpers.private(root / ("flattened-" + role + ".json"), {
        "observed_image": live["Image"], "observed_container": live["Id"],
        "original_layers": layers, "flattened_image": flattened,
        "read_only_export": True, "mounted_volumes_excluded": True,
    })
    print(json.dumps({"flattened": role, "original_layers": layers,
                      "base_image": flattened}), flush=True)
    return tag


def verify_image_files(image, hashes):
    script = """import hashlib,json,pathlib,sys
hashes=json.load(sys.stdin)
bad=[]
for name,expected in hashes.items():
    path=pathlib.Path('/app')/name
    if not path.is_file():
        bad.append({'path':name,'reason':'missing'})
    elif hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        bad.append({'path':name,'reason':'hash mismatch'})
assert not bad,json.dumps(bad)
print(len(hashes))
"""
    checked = out(["docker", "run", "--rm", "-i", "--network", "none",
                   "--read-only", "--cap-drop", "ALL", "--security-opt",
                   "no-new-privileges", "--entrypoint", "python", image,
                   "-c", script], input=json.dumps(hashes).encode()).decode().strip()
    assert int(checked) == len(hashes)


def verify_candidate_files(manifest):
    for role, image in manifest["images"].items():
        if role != "frontend":
            verify_image_files(image, manifest["files"])
    verify_frontend_image(manifest["images"]["frontend"], manifest["frontend_files"])
    print(json.dumps({"candidate_files_verified": True,
                      "files_per_backend": len(manifest["files"])}), flush=True)



def frontend_hashes():
    hashes = {}
    for directory in ("app", "components", "features", "lib", "public", "build"):
        for path in sorted((REPO / directory).rglob("*")):
            if path.is_file():
                relative = path.relative_to(REPO).as_posix()
                hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
                if directory == "public":
                    hashes["dist/client/" + relative[len("public/"):]] = hashes[relative]
    for relative in ("package.json", "package-lock.json", "backend/app/processing_notice.json"):
        hashes[relative] = hashlib.sha256((REPO / relative).read_bytes()).hexdigest()
    return hashes


def verify_frontend_image(image, hashes):
    script = "const fs=require('fs'),c=require('crypto'); const h=JSON.parse(fs.readFileSync(0,'utf8')); const bad=Object.entries(h).filter(([p,s])=>!fs.existsSync('/app/'+p)||c.createHash('sha256').update(fs.readFileSync('/app/'+p)).digest('hex')!==s).map(([p])=>p); if(bad.length)throw Error(JSON.stringify(bad)); console.log(Object.keys(h).length);"
    checked = out(["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
                   "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                   "--entrypoint", "node", image, "-e", script], input=json.dumps(hashes).encode()).decode().strip()
    assert int(checked) == len(hashes)


def build(root, revision, reuse_candidate=None):
    assert REPO == Path("/opt/polaris/releases") / revision, "Use the exact release directory"
    required_free = (2 if reuse_candidate else 7) * 1024 ** 3
    assert shutil.disk_usage('/').free >= required_free, "Reclaim unused candidate cache before building"
    root.mkdir(mode=0o700, exist_ok=False)
    live = {role: healthy(role) for role in ROLES}
    baseline = {role: row["Image"] for role, row in live.items()}
    helpers.private(root / "build-baseline.private.json", live)
    hashes = source_hashes()
    front_hashes = frontend_hashes()
    previous = None
    if reuse_candidate:
        previous_root = Path('/etc/polaris/audit-20261030-' + reuse_candidate[:12])
        previous = json.loads((previous_root / 'manifest.json').read_text())
        assert previous['revision'] == reuse_candidate
        assert previous['bases'] == baseline, "Candidate baseline differs from production"
        assert previous['files'] == hashes, "Backend changed; perform a full build"
        stable = lambda name: name.startswith(('build/', 'public/', 'dist/client/')) or name in {
            'package.json', 'package-lock.json', 'backend/app/processing_notice.json'}
        assert {p: h for p, h in front_hashes.items() if stable(p)} == {
            p: h for p, h in previous['frontend_files'].items() if stable(p)
        }, "Frontend dependencies, build runtime or public assets changed; perform a full build"
        verify_candidate_files(previous)
    images = {}
    for role in ROLES:
        if previous and role != 'frontend':
            images[role] = previous['images'][role]
            verify_image_files(images[role], hashes)
            print(json.dumps({'reused_verified_backend': role, 'image': images[role]}), flush=True)
            continue
        dockerfile = "frontend" if role == "frontend" else "backend"
        tag = "polaris/audit-" + role + ":" + revision[:12]
        base_tag = build_base(role, live[role], root) if not previous else (
            'polaris/audit-reuse-frontend:' + reuse_candidate[:12])
        if previous:
            subprocess.run(['docker', 'tag', previous['images']['frontend'], base_tag], check=True)
            dockerfile = 'frontend-overlay'
        subprocess.run(["docker", "build", "-f",
            str(REPO / "deploy/sister-audit-20261030" / (dockerfile + ".Dockerfile")),
            "--pull=false", "--build-arg", "POLARIS_BASE_IMAGE=" + base_tag,
            "--build-arg", "POLARIS_REVISION=" + revision, "-t", tag, str(REPO)],
            check=True)
        images[role] = out(["docker", "image", "inspect", "--format", "{{.Id}}", tag]).decode().strip()
        if role != "frontend":
            verify_image_files(images[role], hashes)
        else:
            verify_frontend_image(images[role], front_hashes)
        print(json.dumps({"built": role, "image": images[role]}), flush=True)
    helpers.private(root / "manifest.json", {
        "revision": revision, "bases": baseline, "images": images, "files": hashes, "frontend_files": front_hashes,
    })
    assert frontend_hashes() == front_hashes
    assert source_hashes() == hashes, "Release source changed during build"
    print(json.dumps({"build_complete": True, "revision": revision,
                      "source_files": len(hashes)}), flush=True)


def prepare(root):
    manifest = json.loads((root / "manifest.json").read_text())
    live = {role: healthy(role) for role in ROLES}
    assert all(row["Image"] == manifest["bases"][role] for role, row in live.items()), "Runtime drifted"
    schema = sql("SELECT version_num FROM alembic_version")
    width = sql("SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name='job_plans' AND column_name='schema_version'")
    assert schema in {OLD_SCHEMA, NEW_SCHEMA} and width == "64"
    verify_candidate_files(manifest)
    idle()
    config = None
    for role, row in live.items():
        source = row["Config"]["Labels"]["com.docker.compose.project.config_files"]
        assert source.startswith("/etc/polaris/") and "," not in source
        canonical = json.loads(out(["docker", "compose", "-f", source, "config", "--format", "json"]))
        if config is None:
            config = {key: deepcopy(value) for key, value in canonical.items()
                      if key in {"name", "services", "networks", "volumes", "secrets", "configs"}}
            config["services"] = {}
        service = deepcopy(canonical["services"][role])
        service.pop("depends_on", None)
        service.pop("build", None)
        helpers.preserve_runtime_fields(service, row)
        service["image"] = row["Image"]
        service["pull_policy"] = "never"
        assert not service.get("ports") and service.get("read_only")
        assert "ALL" in service.get("cap_drop", [])
        config["services"][role] = service
    assert config and config["name"] == "polaris-production"
    for section in ("networks", "volumes"):
        config[section] = {key: {"name": value["name"], "external": True}
                           for key, value in config.get(section, {}).items()}
    rollback = deepcopy(config)
    for role, service in config["services"].items():
        service["image"] = manifest["images"][role]
        service.setdefault("labels", {})["com.polaris.audit.revision"] = manifest["revision"]
    helpers.private(root / "rollback.compose.private.json", rollback)
    helpers.private(root / "active.compose.private.json", config)
    helpers.private(root / "baseline.private.json", {
        "roles": live, "protected": protected(), "schema": schema,
        "plan_count": sql("SELECT count(*) FROM job_plans"),
    })
    compose(root, "active.compose.private.json", "config", "--quiet")
    compose(root, "rollback.compose.private.json", "config", "--quiet")
    fd = os.open(root / "postgres.dump", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        subprocess.run(["docker", "exec", "polaris-production-postgres-1", "pg_dump",
                        "-U", "polaris", "-d", "polaris", "-Fc"], stdout=stream, check=True)
    subprocess.run(["docker", "exec", "-i", "polaris-production-postgres-1", "pg_restore", "--list"],
                   input=(root / "postgres.dump").read_bytes(), check=True, stdout=subprocess.DEVNULL)
    print(json.dumps({"prepared": True, "backup_bytes": (root / "postgres.dump").stat().st_size}), flush=True)


def verify_runtime(root):
    manifest = json.loads((root / "manifest.json").read_text())
    baseline = json.loads((root / "baseline.private.json").read_text())
    hashes = manifest["files"]
    result = {}
    for role in ROLES:
        row = healthy(role)
        assert row["Image"] == manifest["images"][role]
        previous = baseline["roles"][role]
        env = lambda value: dict(entry.split("=", 1) for entry in value["Config"]["Env"])
        assert env(row) == env(previous), role + " environment"
        for key in ("Cmd", "Entrypoint", "Healthcheck", "User", "WorkingDir"):
            assert row["Config"].get(key) == previous["Config"].get(key), role + " runtime " + key
        for key in ("Memory", "NanoCpus", "ReadonlyRootfs", "CapDrop", "SecurityOpt"):
            assert row["HostConfig"].get(key) == previous["HostConfig"].get(key), role + " resource " + key
        assert set(row["NetworkSettings"]["Networks"]) == set(previous["NetworkSettings"]["Networks"]), role + " networks"
        mounts = lambda value: sorted((entry["Type"], entry.get("Name", ""), entry["Source"], entry["Destination"], entry["RW"])
                                      for entry in value["Mounts"])
        assert mounts(row) == mounts(previous), role + " mounts"
        assert row["RestartCount"] == 0 and not row["State"].get("OOMKilled")
        if role != "frontend":
            script = "import hashlib,json,pathlib; h=json.load(__import__('sys').stdin); " \
                     "bad=[p for p,s in h.items() if hashlib.sha256((pathlib.Path('/app')/p).read_bytes()).hexdigest()!=s]; " \
                     "assert not bad,bad; print(len(h))"
            checked = out(["docker", "exec", "-i", "polaris-production-" + role + "-1", "python", "-c", script],
                          input=json.dumps(hashes).encode()).decode().strip()
        else:
            verify_frontend_image(row["Image"], manifest["frontend_files"])
            checked = len(manifest["frontend_files"])
        result[role] = {"image": row["Image"], "healthy": True, "source_files_verified": int(checked)}
    assert protected() == baseline["protected"], "An unrelated container changed"
    assert sql("SELECT version_num FROM alembic_version") == NEW_SCHEMA
    assert sql("SELECT character_maximum_length FROM information_schema.columns "
               "WHERE table_name='job_plans' AND column_name='schema_version'") == "64"
    helpers.private(root / "runtime-proof.json", {
        "revision": manifest["revision"], "roles": result, "schema": NEW_SCHEMA,
        "runtime_preserved": True, "unrelated_services_preserved": True,
    })
    print(json.dumps({"verified": True, "revision": manifest["revision"], "roles": result,
                      "runtime_preserved": True, "unrelated_services_preserved": True}), flush=True)


def activate(root):
    manifest = json.loads((root / "manifest.json").read_text())
    baseline = json.loads((root / "baseline.private.json").read_text())
    assert protected() == baseline["protected"]
    assert (root / "postgres.dump").stat().st_size > 0
    rehearsal = json.loads((root / "restore-rehearsal.json").read_text())
    assert rehearsal["source_revision"] == manifest["revision"] and rehearsal["candidate_migration_passed"]
    assert all(inspect(role)["Image"] == manifest["bases"][role] for role in ROLES)
    verify_candidate_files(manifest)
    idle()
    # Stop dispatchers first, wait for in-flight work, then observe idle again.
    compose(root, "active.compose.private.json", "stop", "--timeout", "1200", *WORKERS)
    try:
        idle()
        # The candidate runs no server and uses the existing private API network.
        compose(root, "active.compose.private.json", "run", "--rm", "--no-deps", "-T",
                "api", "python", "-m", "alembic", "-c", "/app/alembic.ini", "upgrade", NEW_SCHEMA)
        assert sql("SELECT version_num FROM alembic_version") == NEW_SCHEMA
        assert sql("SELECT count(*) FROM job_plans") == baseline["plan_count"]
        compose(root, "active.compose.private.json", "up", "-d", "--no-deps", "--no-build",
                "--pull", "never", *APIS)
        for role in APIS:
            healthy(role)
        compose(root, "active.compose.private.json", "up", "-d", "--no-deps", "--no-build",
                "--pull", "never", *WORKERS)
        for role in WORKERS:
            healthy(role)
        compose(root, "active.compose.private.json", "up", "-d", "--no-deps", "--no-build",
                "--pull", "never", "frontend")
        verify_runtime(root)
    except BaseException:
        # Keep consent receipts during application rollback; do not reverse their migration.
        compose(root, "rollback.compose.private.json", "up", "-d", "--no-deps", "--no-build",
                "--pull", "never", *APIS, *WORKERS, "frontend")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("build", "prepare", "activate", "verify"))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--reuse-candidate")
    args = parser.parse_args()
    assert re.fullmatch(r"[0-9a-f]{40}", args.revision)
    assert args.reuse_candidate is None or re.fullmatch(r"[0-9a-f]{40}", args.reuse_candidate)
    root = Path("/etc/polaris/audit-20261030-" + args.revision[:12])
    if args.phase == "build":
        build(root, args.revision, args.reuse_candidate)
    elif args.phase == "prepare":
        prepare(root)
    elif args.phase == "activate":
        activate(root)
    else:
        verify_runtime(root)
