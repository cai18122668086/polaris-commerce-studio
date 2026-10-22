"""Scoped native-Skill release; credentials and Compose stay on the user's server.

Prepare captures a fresh baseline and database backup. Backend/frontend phases
replace only the three named roles; no proxy, dispatcher, detail or schema edits.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from copy import deepcopy
from pathlib import Path

ROOT = Path("/etc/polaris/replica-native-20261022")
PREVIOUS = Path("/etc/polaris/one-click-replica-20261022/active.compose.private.json")
ROLES = ("api", "worker", "detail-api", "detail-worker", "dispatcher", "caddy",
         "replica-api", "replica-worker", "frontend")
PRESERVE = ROLES[:6]
CADDY = Path("/opt/polaris/releases/888409d869a8459f0c4fe5086ff45eceae6efcc9/deploy/Caddyfile.domestic-detail-native")
ENV = {**os.environ, "COMPOSE_IGNORE_ORPHANS": "true"}


def inspect(role):
    return json.loads(subprocess.check_output([
        "docker", "inspect", "polaris-production-" + role + "-1"
    ]))[0]


def private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)


def escaped(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [escaped(row) for row in value]
    if isinstance(value, dict):
        return {key: escaped(row) for key, row in value.items()}
    return value


def idle():
    sql = """SELECT
      (SELECT count(*) FROM jobs WHERE configuration ? 'replica_session_id'
       AND status NOT IN ('partial','completed','failed','cancelled')) +
      (SELECT count(*) FROM replica_documents WHERE status IN ('fetching','analysing'))
    """
    count = subprocess.check_output([
        "docker", "exec", "-i", "polaris-production-postgres-1", "psql",
        "-U", "polaris", "-d", "polaris", "-At"
    ], input=sql.encode()).decode().strip()
    assert count == "0", "Replica work is active; defer cutover"


def unchanged(*roles):
    baseline = json.loads((ROOT / "baseline.json").read_text())
    for role in roles:
        current = inspect(role)
        assert {"id": current["Id"], "image": current["Image"]} == baseline["roles"][role], role + " changed since prepare"
    assert hashlib.sha256(CADDY.read_bytes()).hexdigest() == baseline["caddy_sha256"], "Proxy changed since prepare"


def health(role):
    for _ in range(40):
        current = inspect(role)
        if current["State"].get("Health", {}).get("Status") == "healthy":
            return
        assert current["State"]["Status"] not in {"exited", "dead"}, role + " stopped"
        time.sleep(2)
    raise RuntimeError(role + " health timeout")


def compose(path, *arguments):
    subprocess.run(["docker", "compose", "-f", str(path), *arguments],
                   check=True, env=ENV)


def prepare(revision, backend, frontend):
    assert re.fullmatch(r"[0-9a-f]{40}", revision)
    for image in (backend, frontend):
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", image)
        subprocess.run(["docker", "image", "inspect", image], check=True,
                       stdout=subprocess.DEVNULL)
    assert not ROOT.exists(), "Prepared release already exists; inspect it"
    ROOT.mkdir(mode=0o700)
    live = {role: inspect(role) for role in ROLES}
    for role in ROLES:
        health(role)
    idle()
    config = json.loads(subprocess.check_output([
        "docker", "compose", "-f", str(PREVIOUS), "config", "--format", "json"
    ]))
    config["services"] = {
        role: deepcopy(config["services"][role])
        for role in ("replica-api", "replica-worker", "frontend")
    }
    previous = deepcopy(config)
    for role, service in config["services"].items():
        assert not service.get("ports") and service.get("read_only")
        assert "ALL" in service.get("cap_drop", [])
        service["environment"] = dict(row.split("=", 1) for row in live[role]["Config"]["Env"])
        previous["services"][role]["environment"] = deepcopy(service["environment"])
        previous["services"][role]["image"] = live[role]["Image"]
        service["image"] = frontend if role == "frontend" else backend
        service["pull_policy"] = "never"
        service.setdefault("labels", {})["com.polaris.replica.native_revision"] = revision
    private(ROOT / "rollback.compose.private.json", escaped(previous))
    private(ROOT / "active.compose.private.json", escaped(config))
    private(ROOT / "baseline.json", {
        "revision": revision,
        "roles": {role: {"id": value["Id"], "image": value["Image"]} for role, value in live.items()},
        "caddy_sha256": hashlib.sha256(CADDY.read_bytes()).hexdigest(),
    })
    compose(ROOT / "active.compose.private.json", "config", "--quiet")
    backup = Path("/opt/polaris/backups/20261022-replica-native")
    backup.mkdir(mode=0o700, exist_ok=False)
    with (backup / "postgres.dump").open("xb") as stream:
        subprocess.run(["docker", "exec", "polaris-production-postgres-1",
                        "pg_dump", "-U", "polaris", "-d", "polaris", "-Fc"],
                       stdout=stream, check=True)
    os.chmod(backup / "postgres.dump", 0o600)
    (backup / "README.txt").write_text("No schema migration or object deletion in this release. Existing immutable objects remain in place. Restore is not part of application rollback.\n")
    print(json.dumps({"prepared": True, "revision": revision, "roles": list(config["services"]), "credentials_exported": False}), flush=True)


def phase(name):
    unchanged(*PRESERVE)
    if name in {"backend", "rollback"}:
        idle()
    if name == "backend":
        unchanged("replica-api", "replica-worker", "frontend")
        selected = ("replica-api", "replica-worker")
    elif name == "frontend":
        unchanged("frontend")
        health("replica-api")
        health("replica-worker")
        selected = ("frontend",)
    elif name == "rollback":
        selected = ("replica-api", "replica-worker", "frontend")
    else:
        selected = ()
    if selected:
        compose(ROOT / ("rollback.compose.private.json" if name == "rollback" else "active.compose.private.json"),
                "up", "-d", "--no-deps", "--no-build", "--pull", "never", *selected)
    for role in ("replica-api", "replica-worker", "frontend"):
        health(role)
    unchanged(*PRESERVE)
    evidence = {"phase": name, "preserved_roles": list(PRESERVE),
                "roles": {role: {"id": inspect(role)["Id"], "image": inspect(role)["Image"]} for role in ROLES}}
    (ROOT / (name + "-evidence.json")).write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"phase": name, "healthy": True, "unrelated_services_unchanged": True}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "backend", "frontend", "verify", "rollback"])
    parser.add_argument("--revision")
    parser.add_argument("--backend-image")
    parser.add_argument("--frontend-image")
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare(args.revision, args.backend_image, args.frontend_image)
    else:
        phase(args.phase)
