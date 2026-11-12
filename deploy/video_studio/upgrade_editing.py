"""Upgrade existing video/editing services from immutable images; preserve all other roles."""

import argparse
import copy
import json
import os
import re
import subprocess
from pathlib import Path

from integrated_release import (
    PROJECT, backup, composition, compose, digest, environment, inspect,
    observed, output, query, run, save, wait_healthy,
)

os.umask(0o077)
ROLES = ("video-api", "editing-worker", "editing-maintenance", "frontend")


def name(role):
    return PROJECT + "-" + role + "-1"


def baseline():
    names = output(["docker", "ps", "-a", "--format", "{{.Names}}"]).decode().split()
    return {key: inspect(key) for key in names}


def require_idle():
    for table in ("video_generations", "video_editing_tasks", "video_editing_planning_tasks"):
        if query("select count(*) from " + table + " where status in ('queued','running');") != "0":
            raise ValueError("Active work must finish before cutover: " + table)


def services_for(live, images, revision, examples):
    """Keep observed runtime, identities, queues and mounts; change images and examples only."""
    services = {role: observed(live[name(role)]) for role in ROLES}
    rollback = composition(copy.deepcopy(services))
    for role, service in services.items():
        if service.get("ports"):
            raise ValueError("Video services must retain private networking")
        service["image"] = images[role]
        service.setdefault("labels", {})["com.polaris.video.revision"] = revision
        if role != "frontend":
            runtime = environment(live[name(role)])
            if runtime.get("POLARIS_AUTH_MODE") != "external":
                raise ValueError("Production authentication must be preserved")
            if runtime.get("POLARIS_VIDEO_EDITING_ALIGNMENT_ENABLED") != "true":
                raise ValueError("Confirmed-script alignment must already be enabled")
            matches = [mount for mount in service["volumes"] if mount["target"] == "/template-examples"]
            if len(matches) != 1 or not matches[0]["read_only"]:
                raise ValueError("One read-only examples mount is required")
            matches[0]["source"] = str(examples)
    return composition(services), rollback


def prepare(root, revision, backend, frontend, examples):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Full merged revision required")
    if not all(re.fullmatch(r"sha256:[0-9a-f]{64}", image) for image in (backend, frontend)):
        raise ValueError("Immutable image IDs required")
    if not (examples / "manifest.json").is_file():
        raise ValueError("Versioned examples manifest required")
    live = baseline()
    for role in ROLES:
        item = live[name(role)]
        if not item["State"]["Running"] or (role != "editing-maintenance" and item["State"].get("Health", {}).get("Status") != "healthy"):
            raise ValueError("Existing release is not healthy: " + role)
    images = {role: frontend if role == "frontend" else backend for role in ROLES}
    active, rollback = services_for(live, images, revision, examples)
    root.mkdir(parents=True, exist_ok=False)
    save(root / "active.compose.private.json", active)
    save(root / "rollback.compose.private.json", rollback)
    save(root / "manifest.json", {
        "revision": revision, "images": images,
        "baseline": {key: {"id": value["Id"], "image": value["Image"]} for key, value in live.items()},
        "schema_before": query("select version_num from alembic_version;"),
        "examples": str(examples), "examples_manifest_sha256": digest(examples / "manifest.json"),
        "schema_changes": False, "paid_generation_submissions": 0,
    })
    run(["docker", "compose", "-f", str(root / "active.compose.private.json"), "config", "--quiet"])
    print("Prepared four-service upgrade and exact rollback", flush=True)


def verify(root, *, rollback=False):
    manifest = json.loads((root / "manifest.json").read_text())
    for container, old in manifest["baseline"].items():
        current = inspect(container)
        if container not in {name(role) for role in ROLES}:
            if (current["Id"], current["Image"]) != (old["id"], old["image"]):
                raise ValueError("Unrelated service changed: " + container)
    for role in ROLES:
        current = inspect(name(role))
        expected = manifest["baseline"][name(role)]["image"] if rollback else manifest["images"][role]
        if current["Image"] != expected or not current["State"]["Running"]:
            raise ValueError("Wrong or stopped image: " + role)
        if role != "editing-maintenance":
            wait_healthy(role)
        if role != "frontend" and environment(current)["POLARIS_AUTH_MODE"] != "external":
            raise ValueError("Authentication changed")
    if query("select version_num from alembic_version;") != manifest["schema_before"]:
        raise ValueError("Unexpected schema change")
    result = {
        "revision": manifest["revision"], "status": "rolled_back" if rollback else "healthy",
        "schema_unchanged": True, "unrelated_services_unchanged": True,
        "authentication_preserved": True, "paid_generation_submissions": 0,
        "images": {role: inspect(name(role))["Image"] for role in ROLES},
    }
    save(root / ("rollback-result.json" if rollback else "deployment-result.json"), result)
    print(json.dumps(result), flush=True)


def apply(root):
    manifest = json.loads((root / "manifest.json").read_text())
    for role in ROLES:
        if inspect(name(role))["Id"] != manifest["baseline"][name(role)]["id"]:
            raise ValueError("Service changed since preparation: " + role)
    if digest(Path(manifest["examples"]) / "manifest.json") != manifest["examples_manifest_sha256"]:
        raise ValueError("Examples changed since preparation")
    require_idle()
    backup(root)
    media = environment(inspect(name("video-api")))["POLARIS_VIDEO_MEDIA_DIR"]
    with (root / "video-media-before.tar.gz").open("xb") as stream:
        run(["docker", "exec", name("video-api"), "tar", "-czf", "-", "-C", media, "."], stdout=stream)
    save(root / "video-backup.json", {"sha256": digest(root / "video-media-before.tar.gz")})
    require_idle()
    try:
        compose(root, "stop", "editing-maintenance", "editing-worker")
        compose(root, "up", "-d", "--no-deps", "video-api", "frontend")
        wait_healthy("video-api")
        wait_healthy("frontend")
        compose(root, "up", "-d", "--no-deps", "editing-worker", "editing-maintenance")
        verify(root)
    except Exception:
        subprocess.run(["docker", "compose", "-p", PROJECT, "-f", str(root / "rollback.compose.private.json"), "up", "-d", "--no-deps", *ROLES], check=True)
        verify(root, rollback=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "apply", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--backend")
    parser.add_argument("--frontend")
    parser.add_argument("--examples", type=Path)
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare(args.root, args.revision, args.backend, args.frontend, args.examples)
    elif args.phase == "apply":
        apply(args.root)
    else:
        verify(args.root)


if __name__ == "__main__":
    main()
