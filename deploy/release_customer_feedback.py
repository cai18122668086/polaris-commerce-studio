"""Server-only, idle cutover of reviewed images; private Compose never leaves the VM.

The manifest records each role's observed base image and built replacement.
Preparation does not change running services. No schema or object changes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from copy import deepcopy
from pathlib import Path

from release_replica_native import preserve_runtime_fields, private

ROLES = ("api", "replica-api", "detail-api", "worker", "replica-worker",
         "detail-worker", "dispatcher", "frontend")
WORKERS = ("dispatcher", "worker", "replica-worker", "detail-worker")
APIS = ("api", "replica-api", "detail-api")
ENV = {**os.environ, "COMPOSE_IGNORE_ORPHANS": "true"}
ID = re.compile(r"sha256:[0-9a-f]{64}")


def inspect(role):
    return json.loads(subprocess.check_output([
        "docker", "inspect", "polaris-production-" + role + "-1"
    ]))[0]


def sql(query):
    return subprocess.check_output([
        "docker", "exec", "polaris-production-postgres-1", "psql", "-U",
        "polaris", "-d", "polaris", "-At", "-v", "ON_ERROR_STOP=1", "-c", query
    ]).decode().strip()


def idle():
    busy = sql("""SELECT
        (SELECT count(*) FROM job_attempts WHERE status IN ('claimed','running')) +
        (SELECT count(*) FROM jobs WHERE status IN ('planning','processing','cancelling')) +
        (SELECT count(*) FROM replica_documents WHERE status IN ('fetching','analysing'))
    """)
    if busy != "0":
        raise RuntimeError("Active work exists; defer cutover without retrying user jobs")


def healthy(role):
    for _ in range(90):
        state = inspect(role)["State"]
        if state.get("Health", {}).get("Status") == "healthy":
            return
        if state["Status"] in {"exited", "dead"}:
            raise RuntimeError(role + " stopped")
        time.sleep(2)
    raise RuntimeError(role + " health timeout")


def compose(root, rollback, *args):
    path = root / ("rollback.compose.private.json" if rollback else "active.compose.private.json")
    subprocess.run(["docker", "compose", "-f", str(path), *args], check=True, env=ENV)


def runtime_config(canonical, live, images, revision):
    config = {key: deepcopy(canonical[key]) for key in
              ("name", "services", "networks", "volumes", "secrets", "configs")
              if key in canonical}
    if config["name"] != "polaris-production":
        raise ValueError("Unexpected Compose project")
    config["services"] = {role: deepcopy(canonical["services"][role]) for role in ROLES}
    for section in ("networks", "volumes"):
        config[section] = {key: {"name": row["name"], "external": True}
                           for key, row in config.get(section, {}).items()}
    rollback = deepcopy(config)
    for role, service in config["services"].items():
        if service.get("ports") or not service.get("read_only"):
            raise ValueError(role + " must remain private and read-only")
        if "ALL" not in service.get("cap_drop", []):
            raise ValueError(role + " must retain dropped capabilities")
        for candidate in (service, rollback["services"][role]):
            candidate.pop("depends_on", None)
            candidate.pop("build", None)
            preserve_runtime_fields(candidate, live[role])
            candidate["pull_policy"] = "never"
        rollback["services"][role]["image"] = live[role]["Image"]
        service["image"] = images[role]
        service.setdefault("labels", {})["com.polaris.feedback.revision"] = revision
        if role != "frontend":
            service["environment"]["POLARIS_IMAGE_GLOBAL_CONCURRENCY"] = "3000"
    return config, rollback


def protected():
    names = subprocess.check_output([
        "docker", "ps", "-a", "--filter", "label=com.docker.compose.project=polaris-production",
        "--format", "{{.Names}}"
    ]).decode().splitlines()
    result = {}
    for name in names:
        if name not in {"polaris-production-" + role + "-1" for role in ROLES}:
            # Historical acceptance containers can carry the project label
            # while using a custom name. Preserve their exact identity too.
            value = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
            result[name] = {"id": value["Id"], "image": value["Image"]}
    return result


def prepare(root, manifest_path):
    manifest = json.loads(manifest_path.read_text())
    revision = manifest["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("A complete Git revision is required")
    if set(manifest["images"]) != set(ROLES) or set(manifest["bases"]) != set(ROLES):
        raise ValueError("Every application role must be recorded")
    live = {role: inspect(role) for role in ROLES}
    for role in ROLES:
        healthy(role)
        if live[role]["Image"] != manifest["bases"][role]:
            raise ValueError(role + " changed since source audit")
        image = manifest["images"][role]
        if not ID.fullmatch(image):
            raise ValueError("Use immutable image IDs")
        new = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0]
        labels = new["Config"].get("Labels", {})
        if labels.get("org.opencontainers.image.revision") != revision:
            raise ValueError(role + " image revision differs")
        if labels.get("com.polaris.feedback.base") != live[role]["Image"]:
            raise ValueError(role + " image base differs")
    sources = {row["Config"]["Labels"]["com.docker.compose.project.config_files"]
               for row in live.values()}
    if len(sources) != 1:
        raise ValueError("Audit differing role Compose files before preparation")
    source = sources.pop()
    if not source.startswith("/etc/polaris/") or "," in source:
        raise ValueError("Unexpected canonical Compose source")
    canonical = json.loads(subprocess.check_output([
        "docker", "compose", "-f", source, "config", "--format", "json"
    ]))
    active, rollback = runtime_config(canonical, live, manifest["images"], revision)
    idle()
    baseline = {
        **manifest, "protected": protected(),
        "containers": {role: live[role]["Id"] for role in ROLES},
        "schema": sql("SELECT version_num FROM alembic_version"),
    }
    root.mkdir(mode=0o700, exist_ok=False)
    private(root / "active.compose.private.json", active)
    private(root / "rollback.compose.private.json", rollback)
    private(root / "baseline.json", baseline)
    compose(root, False, "config", "--quiet")
    compose(root, True, "config", "--quiet")
    fd = os.open(root / "postgres.dump", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        subprocess.run(["docker", "exec", "polaris-production-postgres-1", "pg_dump",
                        "-U", "polaris", "-d", "polaris", "-Fc"], stdout=stream, check=True)
    print(json.dumps({"prepared": True, "revision": revision, "roles": list(ROLES)}), flush=True)


def deploy(root, phase):
    baseline = json.loads((root / "baseline.json").read_text())
    if protected() != baseline["protected"]:
        raise RuntimeError("An unrelated container changed; audit before continuing")
    rollback = phase == "rollback"
    if phase in {"backend", "rollback"}:
        idle()
        if rollback and sql("SELECT count(*) FROM replica_documents WHERE payload::text LIKE '%exact-compact-v9%'") != "0":
            raise RuntimeError("New v9 documents exist; retain v9 support in a forward repair")
        expected = baseline["images"] if rollback else baseline["bases"]
        for role in ROLES:
            if inspect(role)["Image"] != expected[role]:
                raise RuntimeError(role + " image changed since preparation")
        # Warm shutdown allows any call started after the idle observation to finish.
        compose(root, False, "stop", "--timeout", "1200", *WORKERS)
        try:
            idle()
            compose(root, rollback, "up", "-d", "--no-deps", "--no-build", "--pull",
                    "never", "--timeout", "1200", *APIS)
            for role in APIS:
                healthy(role)
            compose(root, rollback, "up", "-d", "--no-deps", "--no-build", "--pull",
                    "never", "--timeout", "1200", *WORKERS)
        except BaseException:
            # Do not leave job dispatch paused after an aborted cutover.
            subprocess.run(["docker", "start", *["polaris-production-" + role + "-1"
                                                 for role in WORKERS]], check=False)
            raise
    if phase in {"frontend", "rollback"}:
        if phase == "frontend" and inspect("frontend")["Image"] != baseline["bases"]["frontend"]:
            raise RuntimeError("Frontend changed since preparation")
        for role in APIS + WORKERS:
            healthy(role)
        compose(root, rollback, "up", "-d", "--no-deps", "--no-build", "--pull",
                "never", "--timeout", "120", "frontend")
    for role in ROLES:
        healthy(role)
    if protected() != baseline["protected"]:
        raise RuntimeError("An unrelated service changed")
    if sql("SELECT version_num FROM alembic_version") != baseline["schema"]:
        raise RuntimeError("Unexpected schema change")
    evidence = {"phase": phase, "revision": baseline["revision"],
                "roles": {role: {"id": inspect(role)["Id"], "image": inspect(role)["Image"]}
                          for role in ROLES}, "unrelated_services_unchanged": True}
    private(root / (phase + "-evidence.json"), evidence)
    print(json.dumps({"phase": phase, "healthy": True, "schema_unchanged": True,
                      "unrelated_services_unchanged": True}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "backend", "frontend", "rollback"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if not str(args.root).startswith("/etc/polaris/customer-feedback-"):
        parser.error("Use a new private customer-feedback release directory")
    if args.phase == "prepare":
        if args.manifest is None:
            parser.error("prepare requires --manifest")
        prepare(args.root, args.manifest)
    else:
        deploy(args.root, args.phase)
