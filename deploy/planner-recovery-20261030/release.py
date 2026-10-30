"""Release the unified planner policy without altering image routes or the DB."""

from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "suite_release_helpers", REPO / "deploy/sister-fast-20261030/release.py")
assert spec and spec.loader
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
ROLES = tuple(role for role in shared.ROLES if role != "frontend")
POLICY_KEYS = frozenset({
    "POLARIS_ANALYSIS_API_KEY", "POLARIS_ANALYSIS_BASE_URL", "POLARIS_ANALYSIS_MODEL",
    "POLARIS_ANALYSIS_TIMEOUT_SECONDS", "POLARIS_PROVIDER_FAILOVER_ENABLED",
    "POLARIS_PROVIDER_FAILOVER_API_KEY", "POLARIS_PROVIDER_FAILOVER_BASE_URL",
    "POLARIS_PROVIDER_FAILOVER_MODEL", "POLARIS_PROVIDER_ROTATION_ORDER",
    "POLARIS_PLANNER_STREAMING_ENABLED", "POLARIS_PLANNER_RECOVERY_ENABLED",
    "POLARIS_PLANNER_TRANSIENT_RETRIES", "POLARIS_PLANNER_RETRY_BACKOFF_SECONDS",
    "POLARIS_PLANNER_PRIMARY_TIMEOUT_SECONDS",
})


def environment(row):
    return dict(value.split("=", 1) for value in row["Config"]["Env"])


def policy(live):
    current = environment(live["worker"])
    keys = [value for value in re.split(r"[\s,]+", current["POLARIS_PROVIDER_FAILOVER_API_KEY"]) if value]
    assert len(keys) == 3 and len(set(keys)) == 3
    assert current["POLARIS_ANALYSIS_BASE_URL"].rstrip("/") == "https://api.tengliapi.xyz"
    assert current["POLARIS_PROVIDER_FAILOVER_BASE_URL"].rstrip("/") == "https://api.ooapi.cc"
    assert current["POLARIS_ANALYSIS_API_KEY"] and current["POLARIS_ANALYSIS_API_KEY"] not in keys
    assert len(re.split(r"[\s,]+", current["POLARIS_ANALYSIS_API_KEY"].strip())) == 1
    return {
        **{key: current[key] for key in (
            "POLARIS_ANALYSIS_API_KEY", "POLARIS_ANALYSIS_BASE_URL", "POLARIS_ANALYSIS_MODEL",
            "POLARIS_PROVIDER_FAILOVER_API_KEY", "POLARIS_PROVIDER_FAILOVER_BASE_URL",
            "POLARIS_PROVIDER_FAILOVER_MODEL")},
        "POLARIS_ANALYSIS_TIMEOUT_SECONDS": "1200",
        "POLARIS_PROVIDER_FAILOVER_ENABLED": "true",
        "POLARIS_PROVIDER_ROTATION_ORDER": "primary,failover-1,failover-2,failover-3",
        "POLARIS_PLANNER_STREAMING_ENABLED": "true",
        "POLARIS_PLANNER_RECOVERY_ENABLED": "true",
        "POLARIS_PLANNER_TRANSIENT_RETRIES": "1",
        "POLARIS_PLANNER_RETRY_BACKOFF_SECONDS": "2",
        "POLARIS_PLANNER_PRIMARY_TIMEOUT_SECONDS": "300",
    }


def protected():
    result = shared.protected()
    frontend = shared.inspect("frontend")
    result["polaris-production-frontend-1"] = {"id": frontend["Id"], "image": frontend["Image"]}
    return result


def build(root, revision):
    assert REPO == Path("/opt/polaris/releases") / revision
    root.mkdir(mode=0o700, exist_ok=False)
    live = {role: shared.healthy(role) for role in ROLES}
    shared.helpers.private(root / "build-baseline.private.json", live)
    hashes = shared.source_hashes()
    images = {}
    for role, row in live.items():
        base = shared.build_base(role, row, root)
        tag = "polaris/planner-recovery-" + role + ":" + revision[:12]
        subprocess.run(["docker", "build", "--pull=false", "-f",
            str(REPO / "deploy/sister-fast-20261030/backend.Dockerfile"),
            "--build-arg", "POLARIS_BASE_IMAGE=" + base,
            "--build-arg", "POLARIS_REVISION=" + revision, "-t", tag, str(REPO)], check=True)
        image = shared.out(["docker", "image", "inspect", "--format", "{{.Id}}", tag]).decode().strip()
        shared.verify_image_files(image, hashes)
        images[role] = image
        print(json.dumps({"built_and_verified": role}), flush=True)
    shared.helpers.private(root / "manifest.json", {
        "revision": revision, "images": images, "files": hashes,
        "bases": {role: row["Image"] for role, row in live.items()},
    })
    assert shared.source_hashes() == hashes
    print(json.dumps({"build_complete": True, "revision": revision}), flush=True)


def prepare(root):
    manifest = json.loads((root / "manifest.json").read_text())
    live = {role: shared.healthy(role) for role in ROLES}
    assert all(row["Image"] == manifest["bases"][role] for role, row in live.items())
    shared.verify_candidate_files(manifest)
    shared.idle()
    desired = policy(live)
    config = None
    for role, row in live.items():
        source = row["Config"]["Labels"]["com.docker.compose.project.config_files"]
        assert source.startswith("/etc/polaris/") and "," not in source
        canonical = json.loads(shared.out(["docker", "compose", "-f", source, "config", "--format", "json"]))
        if config is None:
            config = {key: deepcopy(value) for key, value in canonical.items()
                      if key in {"name", "services", "networks", "volumes", "secrets", "configs"}}
            config["services"] = {}
        service = deepcopy(canonical["services"][role])
        service.pop("depends_on", None)
        service.pop("build", None)
        shared.helpers.preserve_runtime_fields(service, row)
        service.update(image=row["Image"], pull_policy="never")
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
        service["environment"].update(shared.helpers.escaped(desired))
        service.setdefault("labels", {})["com.polaris.planner.revision"] = manifest["revision"]
    shared.helpers.private(root / "rollback.compose.private.json", rollback)
    shared.helpers.private(root / "active.compose.private.json", config)
    shared.helpers.private(root / "baseline.private.json", {
        "roles": live, "protected": protected(), "planner_policy": desired,
        "schema": shared.sql("SELECT version_num FROM alembic_version"),
    })
    for filename in ("active.compose.private.json", "rollback.compose.private.json"):
        shared.compose(root, filename, "config", "--quiet")
    fd = os.open(root / "postgres.dump", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        subprocess.run(["docker", "exec", "polaris-production-postgres-1", "pg_dump",
                        "-U", "polaris", "-d", "polaris", "-Fc"], stdout=stream, check=True)
    subprocess.run(["docker", "exec", "-i", "polaris-production-postgres-1", "pg_restore", "--list"],
        input=(root / "postgres.dump").read_bytes(), check=True, stdout=subprocess.DEVNULL)
    print(json.dumps({"prepared": True, "backup_bytes": (root / "postgres.dump").stat().st_size}), flush=True)


def verify(root):
    manifest = json.loads((root / "manifest.json").read_text())
    baseline = json.loads((root / "baseline.private.json").read_text())
    roles = {}
    for role in ROLES:
        row = shared.healthy(role)
        old = baseline["roles"][role]
        assert row["Image"] == manifest["images"][role]
        before, after = environment(old), environment(row)
        assert {k: v for k, v in after.items() if k not in POLICY_KEYS} == {
            k: v for k, v in before.items() if k not in POLICY_KEYS}, role + " non-planner environment"
        assert all(after.get(key) == value for key, value in baseline["planner_policy"].items())
        for key in ("Cmd", "Entrypoint", "Healthcheck", "User", "WorkingDir"):
            assert row["Config"].get(key) == old["Config"].get(key), role + " " + key
        for key in ("Memory", "NanoCpus", "ReadonlyRootfs", "CapDrop", "SecurityOpt"):
            assert row["HostConfig"].get(key) == old["HostConfig"].get(key), role + " " + key
        assert set(row["NetworkSettings"]["Networks"]) == set(old["NetworkSettings"]["Networks"])
        mounts = lambda value: sorted((e["Type"], e.get("Name", ""), e["Source"], e["Destination"], e["RW"])
                                     for e in value["Mounts"])
        assert mounts(row) == mounts(old) and row["RestartCount"] == 0
        script = "import hashlib,json,pathlib,sys; h=json.load(sys.stdin); bad=[p for p,s in h.items() if hashlib.sha256((pathlib.Path('/app')/p).read_bytes()).hexdigest()!=s]; assert not bad,bad; print(len(h))"
        checked = shared.out(["docker", "exec", "-i", "polaris-production-" + role + "-1", "python", "-c", script],
            input=json.dumps(manifest["files"]).encode()).decode().strip()
        roles[role] = {"healthy": True, "image": row["Image"], "source_files": int(checked),
                       "planner_streaming": True, "planner_recovery": True, "planner_routes": 4}
    assert protected() == baseline["protected"]
    assert shared.sql("SELECT version_num FROM alembic_version") == baseline["schema"]
    proof = {"revision": manifest["revision"], "roles": roles,
             "image_routes_and_other_environment_preserved": True,
             "runtime_resources_preserved": True, "unrelated_services_preserved": True,
             "schema_unchanged": True}
    shared.helpers.private(root / "runtime-proof.json", proof)
    print(json.dumps(proof), flush=True)


def activate(root):
    manifest = json.loads((root / "manifest.json").read_text())
    baseline = json.loads((root / "baseline.private.json").read_text())
    shared.verify_candidate_files(manifest)
    assert protected() == baseline["protected"]
    assert (root / "postgres.dump").stat().st_size > 0
    assert all(shared.inspect(role)["Image"] == manifest["bases"][role] for role in ROLES)
    shared.idle()
    shared.compose(root, "active.compose.private.json", "stop", "--timeout", "1200", *shared.WORKERS)
    try:
        shared.idle()
        shared.compose(root, "active.compose.private.json", "up", "-d", "--no-deps", "--no-build", "--pull", "never", *shared.APIS)
        for role in shared.APIS:
            shared.healthy(role)
        shared.compose(root, "active.compose.private.json", "up", "-d", "--no-deps", "--no-build", "--pull", "never", *shared.WORKERS)
        verify(root)
    except BaseException:
        shared.compose(root, "rollback.compose.private.json", "up", "-d", "--no-deps", "--no-build", "--pull", "never", *ROLES)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("build", "prepare", "activate", "verify"))
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    assert re.fullmatch("[0-9a-f]{40}", args.revision)
    root = Path("/etc/polaris/planner-recovery-20261030-" + args.revision[:12])
    if args.phase == "build":
        build(root, args.revision)
    else:
        globals()[args.phase](root)
