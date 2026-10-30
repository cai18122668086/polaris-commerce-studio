"""Immutable Polaris suite release; runtime secrets never leave the server.

Build and prepare do not replace running applications. Activate requires an idle
queue, retained rollback images, a private database backup and exact baselines.
The only database change is the reviewed, forward-compatible 32-to-64 expansion.
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
import subprocess
import time

REPO = Path(__file__).resolve().parents[2]
ROLES = ("api", "worker", "replica-api", "replica-worker", "detail-api",
         "detail-worker", "dispatcher", "frontend")
WORKERS = ("dispatcher", "worker", "replica-worker", "detail-worker")
APIS = ("api", "replica-api", "detail-api")
ENV = {**os.environ, "COMPOSE_IGNORE_ORPHANS": "true"}
OLD_SCHEMA = "20261028_0031"
NEW_SCHEMA = "20261030_0032"

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
    tag = "polaris/suite-fast-base-" + role + ":" + live["Image"][7:19]
    if layers <= 80:
        subprocess.run(["docker", "tag", live["Image"], tag], check=True)
        return tag
    # The running root is read-only and Docker export omits all mounted volumes.
    # Reading its already-mounted filesystem avoids the old image's overlay
    # lowerdir limit. Runtime configuration is restored from inspect, below.
    assert live["HostConfig"]["ReadonlyRootfs"]
    current = inspect(role)
    assert (current["Id"], current["Image"]) == (live["Id"], live["Image"])
    tag = "polaris/suite-fast-flat-" + role + ":" + live["Image"][7:19]
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


def build(root, revision):
    assert REPO == Path("/opt/polaris/releases") / revision, "Use the exact release directory"
    root.mkdir(mode=0o700, exist_ok=False)
    live = {role: healthy(role) for role in ROLES}
    baseline = {role: row["Image"] for role, row in live.items()}
    helpers.private(root / "build-baseline.private.json", live)
    hashes = source_hashes()
    images = {}
    for role in ROLES:
        dockerfile = "frontend" if role == "frontend" else "backend"
        tag = "polaris/suite-fast-" + role + ":" + revision[:12]
        base_tag = build_base(role, live[role], root)
        subprocess.run(["docker", "build", "-f",
            str(REPO / "deploy/sister-fast-20261030" / (dockerfile + ".Dockerfile")),
            "--pull=false", "--build-arg", "POLARIS_BASE_IMAGE=" + base_tag,
            "--build-arg", "POLARIS_REVISION=" + revision, "-t", tag, str(REPO)],
            check=True)
        images[role] = out(["docker", "image", "inspect", "--format", "{{.Id}}", tag]).decode().strip()
        print(json.dumps({"built": role, "image": images[role]}), flush=True)
    helpers.private(root / "manifest.json", {
        "revision": revision, "bases": baseline, "images": images, "files": hashes,
    })
    assert source_hashes() == hashes, "Release source changed during build"
    print(json.dumps({"build_complete": True, "revision": revision,
                      "source_files": len(hashes)}), flush=True)


def prepare(root):
    manifest = json.loads((root / "manifest.json").read_text())
    live = {role: healthy(role) for role in ROLES}
    assert all(row["Image"] == manifest["bases"][role] for role, row in live.items()), "Runtime drifted"
    assert sql("SELECT version_num FROM alembic_version") == OLD_SCHEMA
    assert sql("SELECT character_maximum_length FROM information_schema.columns "
               "WHERE table_name='job_plans' AND column_name='schema_version'") == "32"
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
        service.setdefault("labels", {})["com.polaris.suite_fast.revision"] = manifest["revision"]
    helpers.private(root / "rollback.compose.private.json", rollback)
    helpers.private(root / "active.compose.private.json", config)
    helpers.private(root / "baseline.private.json", {
        "roles": live, "protected": protected(), "schema": OLD_SCHEMA,
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
            checked = 0
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
    assert all(inspect(role)["Image"] == manifest["bases"][role] for role in ROLES)
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
        # Additive width remains 64 on application rollback; never shrink data.
        compose(root, "rollback.compose.private.json", "up", "-d", "--no-deps", "--no-build",
                "--pull", "never", *APIS, *WORKERS, "frontend")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("build", "prepare", "activate", "verify"))
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"[0-9a-f]{40}", args.revision)
    root = Path("/etc/polaris/suite-fast-20261030-" + args.revision[:12])
    if args.phase == "build":
        build(root, args.revision)
    elif args.phase == "prepare":
        prepare(root)
    elif args.phase == "activate":
        activate(root)
    else:
        verify_runtime(root)
