"""Release only product-source API and frontend overlays on inspected live images.

Private environment and rollback files stay on the server. No schema, proxy,
worker, user, object or unrelated application service changes are performed.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import time
from pathlib import Path

SELECTED = ("replica-api", "frontend")
ROLES = (*SELECTED, "replica-worker", "api", "worker", "detail-api", "detail-worker", "video-api", "dispatcher", "caddy")


def inspect(role):
    return json.loads(subprocess.check_output(["docker", "inspect", "polaris-production-" + role + "-1"]))[0]


def private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2)


def escaped(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, dict):
        return {k: escaped(v) for k, v in value.items()}
    if isinstance(value, list):
        return [escaped(v) for v in value]
    return value


def summary(live):
    return {r: {"id": x["Id"], "image": x["Image"]} for r, x in live.items()}


def compose(path, *args):
    subprocess.run(["docker", "compose", "-p", "polaris-production", "-f", str(path), *args], check=True, env={**os.environ, "COMPOSE_IGNORE_ORPHANS": "true"})


def prepare(root, backend, frontend, key_file):
    assert not root.exists(), "Release directory already exists"
    for value in (backend, frontend):
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", value), "Immutable image required"
    live = {r: inspect(r) for r in ROLES}
    config = {"name": "polaris-production", "services": {}, "networks": {}, "volumes": {}}
    for role in SELECTED:
        current = live[role]
        source = current["Config"]["Labels"]["com.docker.compose.project.config_files"]
        assert source.startswith(("/etc/polaris/", "/opt/polaris/releases/")) and "," not in source
        original = json.loads(subprocess.check_output(["docker", "compose", "-f", source, "config", "--format", "json"]))
        service = copy.deepcopy(original["services"][role])
        for key in ("build", "depends_on", "container_name"):
            service.pop(key, None)
        service["image"] = current["Image"]
        service["pull_policy"] = "never"
        service["environment"] = escaped(dict(row.split("=", 1) for row in current["Config"]["Env"]))
        service["command"] = escaped(current["Config"]["Cmd"])
        service["entrypoint"] = escaped(current["Config"].get("Entrypoint"))
        service["networks"] = {name: {"aliases": data.get("Aliases") or []} for name, data in current["NetworkSettings"]["Networks"].items()}
        for name in service["networks"]:
            config["networks"][name] = {"external": True, "name": name}
        service["volumes"] = []
        for mount in current["Mounts"]:
            assert mount["Type"] in {"volume", "bind"}
            source = mount.get("Name") if mount["Type"] == "volume" else mount["Source"]
            service["volumes"].append({"type": mount["Type"], "source": source, "target": mount["Destination"], "read_only": not mount["RW"]})
            if mount["Type"] == "volume":
                config["volumes"][source] = {"external": True, "name": source}
        config["services"][role] = service
    rollback = copy.deepcopy(config)
    config["services"]["replica-api"]["image"] = backend
    config["services"]["frontend"]["image"] = frontend
    if key_file is not None:
        key = key_file.read_text().strip()
        assert key.startswith("ei_") and not any(c.isspace() for c in key)
        config["services"]["replica-api"]["environment"].update({
            "POLARIS_EVERYINFRA_API_KEY": escaped(key),
            "POLARIS_EVERYINFRA_PRODUCT_SOURCES_ENABLED": "true",
        })
    root.mkdir(mode=0o700)
    private(root / "baseline.json", summary(live))
    private(root / "rollback.compose.private.json", rollback)
    private(root / "active.compose.private.json", config)
    compose(root / "active.compose.private.json", "config", "--quiet")
    print(json.dumps({"prepared": True, "selected": SELECTED, "root": str(root)}), flush=True)


def unchanged(root, roles):
    baseline = json.loads((root / "baseline.json").read_text())
    now = summary({r: inspect(r) for r in roles})
    assert all(now[r] == baseline[r] for r in roles), "Live services changed since preparation"


def idle():
    # Both fetching and analysis run as API-owned background work.
    sql = "SELECT count(*) FROM replica_documents WHERE status IN ('fetching','analysing') AND updated_at > now() - interval '25 minutes'"
    result = subprocess.check_output(["docker", "exec", "-i", "polaris-production-postgres-1", "psql", "-U", "polaris", "-d", "polaris", "-At"], input=sql.encode()).decode().strip()
    assert result == "0", "Replica API has active work; defer cutover"


def health():
    for _ in range(45):
        states = [inspect(role)["State"] for role in SELECTED]
        if all(state.get("Health", {}).get("Status") == "healthy" for state in states):
            return
        if any(state.get("Status") == "exited" for state in states):
            break
        time.sleep(2)
    raise RuntimeError("Selected services did not become healthy")


def apply(root, rollback=False):
    preserved = [r for r in ROLES if r not in SELECTED]
    unchanged(root, preserved)
    idle()
    if not rollback:
        unchanged(root, SELECTED)
    path = root / ("rollback.compose.private.json" if rollback else "active.compose.private.json")
    try:
        compose(path, "up", "-d", "--no-deps", "--no-build", "--pull", "never", *SELECTED)
        health()
    except Exception:
        if not rollback:
            compose(root / "rollback.compose.private.json", "up", "-d", "--no-deps", "--no-build", "--pull", "never", *SELECTED)
            health()
        raise
    unchanged(root, preserved)
    evidence = {"healthy": True, "rollback": rollback, "services": summary({r: inspect(r) for r in ROLES}), "unrelated_services_unchanged": True}
    private(root / ("rollback-evidence.json" if rollback else "release-evidence.json"), evidence)
    print(json.dumps(evidence), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "apply", "rollback"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--backend-image")
    parser.add_argument("--frontend-image")
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    assert args.root.is_absolute() and str(args.root).startswith("/etc/polaris/commerce-sources-"), "Scoped release path required"
    if args.phase == "prepare":
        prepare(args.root, args.backend_image, args.frontend_image, args.key_file)
    else:
        apply(args.root, args.phase == "rollback")
