"""Server-local release of the video API, UI and dedicated editing queue.

Inspected credentials stay in private files on the server. Existing non-video
services, authentication identities, object keys and media volumes are preserved.
No phase submits a generation request. Run the phases explicitly in order.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

os.umask(0o077)
PROJECT = "polaris-production"
ROLES = ("video-api", "frontend", "caddy")
NEW_ROLES = ("editing-worker", "editing-maintenance")


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(args):
    return subprocess.check_output(args)


def inspect(name):
    return json.loads(output(["docker", "inspect", name]))[0]


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def save(path, value):
    path.write_text(
        json.dumps(value, indent=2) if not isinstance(value, str) else value
    )
    path.chmod(0o600)


def escaped(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [escaped(item) for item in value]
    if isinstance(value, dict):
        return {key: escaped(item) for key, item in value.items()}
    return value


def environment(live):
    return dict(item.split("=", 1) for item in live["Config"]["Env"])


def observed(live):
    role = live["Config"]["Labels"]["com.docker.compose.service"]
    files = live["Config"]["Labels"]["com.docker.compose.project.config_files"].split(
        ","
    )
    command = ["docker", "compose"]
    for file in files:
        command += ["-f", file]
    config = json.loads(output([*command, "config", "--format", "json"]))
    service = copy.deepcopy(config["services"][role])
    service.pop("depends_on", None)
    service.pop("build", None)
    service.update(image=live["Image"], pull_policy="never")
    service["environment"] = escaped(environment(live))
    service["command"] = escaped(live["Config"].get("Cmd"))
    service["entrypoint"] = escaped(live["Config"].get("Entrypoint"))
    service["networks"] = {
        name: {"aliases": item.get("Aliases") or []}
        for name, item in live["NetworkSettings"]["Networks"].items()
    }
    service["volumes"] = [
        {
            "type": row["Type"],
            "source": row.get("Name") if row["Type"] == "volume" else row["Source"],
            "target": row["Destination"],
            "read_only": not row["RW"],
        }
        for row in live["Mounts"]
        if row["Type"] in {"volume", "bind"}
    ]
    return service


def composition(services):
    networks = {
        name: {"name": name, "external": True}
        for service in services.values()
        for name in service["networks"]
    }
    volumes = {
        row["source"]: {"name": row["source"], "external": True}
        for service in services.values()
        for row in service.get("volumes", [])
        if row["type"] == "volume"
    }
    return {
        "name": PROJECT,
        "services": services,
        "networks": networks,
        "volumes": volumes,
    }


def compose(root, *arguments):
    run(
        [
            "docker",
            "compose",
            "-p",
            PROJECT,
            "-f",
            str(root / "active.compose.private.json"),
            *arguments,
        ]
    )


def prepare(root, revision, assets, backend, frontend):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Full reviewed Git revision required")
    if not all(
        re.fullmatch(r"sha256:[0-9a-f]{64}", image) for image in (backend, frontend)
    ):
        raise ValueError("Immutable built image IDs required")
    root.mkdir(parents=True, exist_ok=False)
    all_names = output(["docker", "ps", "--format", "{{.Names}}"]).decode().split()
    all_live = {name: inspect(name) for name in all_names}
    live = {role: all_live[PROJECT + "-" + role + "-1"] for role in ROLES}
    if any(
        item["State"].get("Health", {}).get("Status") != "healthy"
        for item in live.values()
    ):
        raise ValueError("Existing video/UI/proxy baseline is not healthy")
    services = {role: observed(item) for role, item in live.items()}
    save(root / "rollback.compose.private.json", composition(copy.deepcopy(services)))
    runtime = environment(live["video-api"])
    shared = environment(inspect(PROJECT + "-api-1"))
    for key in ("POLARIS_CELERY_BROKER_URL", "POLARIS_CELERY_RESULT_BACKEND"):
        if not runtime.get(key):
            runtime[key] = shared[key]
    supplied = json.load(sys.stdin)
    allowed = {
        "POLARIS_WUYE_API_KEY",
        "POLARIS_QUANYU_API_KEY",
        "POLARIS_TAO_API_KEY",
        "POLARIS_VIDEO_SCRIPT_API_KEY",
    }
    if set(supplied) - allowed:
        raise ValueError("Unsupported credential override")
    for key, value in supplied.items():
        if not runtime.get(key) and value:
            runtime[key] = value
    for key in allowed:
        if not runtime.get(key):
            raise ValueError("Required video credential missing: " + key)
    runtime.update(
        {
            "POLARIS_VIDEO_EDITING_ENABLED": "true",
            "POLARIS_VIDEO_EDITING_NATIVE_PLAN_ENABLED": "true",
            "POLARIS_VIDEO_EDITING_PLANNING_ENABLED": "true",
            "POLARIS_VIDEO_SCRIPT_PLANNING_ENABLED": "true",
            "POLARIS_VIDEO_SCRIPT_MODEL": "gpt-6.1-sol",
            "POLARIS_VIDEO_EDITING_PLAN_MODEL": "gpt-6.1-sol",
            "POLARIS_VIDEO_WRITING_WORKFLOW_ENABLED": "true",
            "POLARIS_VIDEO_EDITING_LIBRARY_DIR": "/motion",
            "POLARIS_VIDEO_EDITING_LIBRARY_EVIDENCE_DIR": "/motion-evidence",
            "POLARIS_VIDEO_EDITING_NATIVE_BINDINGS_FILE": (
                "/motion-dependencies/bindings.json"
            ),
            "POLARIS_VIDEO_EDITING_TEMPLATE_EXAMPLES_DIR": "/template-examples",
            "POLARIS_VIDEO_EDITING_TASKS_DIR": "/app/.data/editing-tasks",
            "POLARIS_VIDEO_WRITING_LIBRARY_DIR": "/writing",
            "POLARIS_VIDEO_EDITING_ASR_PROVIDER": "funasr",
            "POLARIS_VIDEO_EDITING_ASR_MODEL": "/asr",
            "POLARIS_VIDEO_EDITING_ALIGNMENT_ENABLED": "true",
            "POLARIS_VIDEO_EDITING_ALIGNMENT_MODEL_DIR": "/asr-alignment",
            "POLARIS_VIDEO_EDITING_ASR_DEVICE": "cpu",
            "POLARIS_VIDEO_EDITING_PYTHON": "/usr/local/bin/python",
            "POLARIS_VIDEO_EDITING_FFMPEG": "/usr/bin/ffmpeg",
            "POLARIS_VIDEO_EDITING_FFPROBE": "/usr/bin/ffprobe",
            "POLARIS_VIDEO_EDITING_LEASE_SECONDS": "480",
            "POLARIS_AUTO_PROCESS_JOBS": "false",
            "POLARIS_ECOMMERCE_STARTUP_RECOVERY_ENABLED": "false",
            "POLARIS_VIDEO_BACKGROUND_RECOVERY_ENABLED": "false",
            "POLARIS_VIDEO_LIPSYNC_FAILOVER_ENABLED": "false",
            "POLARIS_VIDEO_SKYHUMAN_AUTO_REGISTER": "false",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "OMP_NUM_THREADS": "2",
            "OPENBLAS_NUM_THREADS": "2",
            "XDG_CACHE_HOME": "/app/.data/editing-tasks/.cache",
        }
    )
    if runtime.get("POLARIS_AUTH_MODE") != "external":
        raise ValueError("Production authentication must be preserved")
    if any("\n" in str(value) or "\r" in str(value) for value in runtime.values()):
        raise ValueError("Multiline runtime values require explicit env-file encoding")
    save(
        root / "runtime.env",
        "\n".join(key + "=" + str(value) for key, value in runtime.items()) + "\n",
    )
    mounts = [
        ("motion", "/motion"),
        ("evidence", "/motion-evidence"),
        ("dependencies", "/motion-dependencies"),
        ("examples", "/template-examples"),
        ("writing", "/writing"),
        ("asr", "/asr"),
        ("alignment", "/asr-alignment"),
    ]
    api = services["video-api"]
    api.update(image=backend, environment=escaped(runtime))
    api["volumes"] += [
        {
            "type": "bind",
            "source": str(assets / name),
            "target": target,
            "read_only": True,
        }
        for name, target in mounts
    ]
    api["volumes"].append(
        {
            "type": "volume",
            "source": "polaris-production_editing_data",
            "target": "/app/.data/editing-tasks",
        }
    )
    api["labels"] = {**api.get("labels", {}), "com.polaris.video.revision": revision}
    services["frontend"]["image"] = frontend
    services["frontend"]["labels"] = {
        **services["frontend"].get("labels", {}),
        "com.polaris.video.revision": revision,
    }
    worker = copy.deepcopy(api)
    worker["command"] = [
        "python",
        "-m",
        "celery",
        "-A",
        "app.celery_app:celery_app",
        "worker",
        "--queues=editing,editing-planning",
        "--concurrency=1",
        "--hostname=editing@%h",
        "--loglevel=INFO",
    ]
    worker.update(mem_limit="3221225472", memswap_limit="4294967296", cpus=1.5)
    worker["healthcheck"] = {
        "test": [
            "CMD-SHELL",
            (
                "celery -A app.celery_app:celery_app inspect ping "
                "-d editing@$$(hostname) --timeout 5 >/dev/null"
            ),
        ],
        "interval": "30s",
        "timeout": "15s",
        "retries": 5,
        "start_period": "60s",
    }
    for role, service in [
        ("editing-worker", worker),
        ("editing-maintenance", copy.deepcopy(worker)),
    ]:
        service.pop("container_name", None)
        service["networks"] = {
            name: {"aliases": [role]} for name in service["networks"]
        }
        for row in service["volumes"]:
            if row["target"] == runtime.get("POLARIS_VIDEO_MEDIA_DIR"):
                row["read_only"] = True
        services[role] = service
    services["editing-maintenance"]["command"] = [
        "python",
        "-m",
        "app.video_editing_maintenance",
        "--interval",
        "30",
    ]
    services["editing-maintenance"].update(
        mem_limit="402653184", cpus=0.25, healthcheck={"disable": True}
    )
    caddy = services["caddy"]
    target = next(
        row for row in caddy["volumes"] if row["target"] == "/etc/caddy/Caddyfile"
    )
    old_caddy = Path(target["source"]).read_text()
    save(root / "Caddyfile.before", old_caddy)
    new_caddy = old_caddy.replace("max_size 55MB", "max_size 210MB")
    if new_caddy != old_caddy:
        if old_caddy.count("max_size 55MB") != 1 or "@video_request" not in old_caddy:
            raise ValueError(
                "Video upload limit needs an explicitly scoped proxy block"
            )
        save(root / "Caddyfile", new_caddy)
        target["source"] = str(root / "Caddyfile")
    save(root / "active.compose.private.json", composition(services))
    baseline = {
        name: {"id": item["Id"], "image": item["Image"]}
        for name, item in all_live.items()
    }
    manifest = {
        "revision": revision,
        "backend_image": backend,
        "frontend_image": frontend,
        "assets": str(assets),
        "baseline": baseline,
        "caddy_changed": old_caddy != new_caddy,
        "schema_before": "20261107_0041",
    }
    save(root / "manifest.json", manifest)
    compose(root, "config", "--quiet")
    print(
        json.dumps(
            {
                "prepared": True,
                "revision": revision,
                "new_services": NEW_ROLES,
                "authentication_preserved": True,
            }
        ),
        flush=True,
    )


def backup(root):
    if (root / "database-before.dump").exists():
        raise ValueError("Backup already exists")
    with (root / "database-before.dump").open("xb") as stream:
        run(
            [
                "docker",
                "exec",
                PROJECT + "-postgres-1",
                "pg_dump",
                "-U",
                "polaris",
                "-d",
                "polaris",
                "-Fc",
            ],
            stdout=stream,
        )
    # The repository's established object backup streams bytes and their SHA256
    # from the live API, retaining opaque keys without printing credentials.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from backup_restore import BACKUP_CODE

    with (root / "objects-before.tar").open("xb") as stream:
        run(
            ["docker", "exec", "-i", PROJECT + "-api-1", "python", "-"],
            input=BACKUP_CODE.encode(),
            stdout=stream,
        )
    save(
        root / "backup-manifest.json",
        {
            name: {"bytes": (root / name).stat().st_size, "sha256": digest(root / name)}
            for name in ("database-before.dump", "objects-before.tar")
        },
    )
    print("Created checksummed database and object backups", flush=True)


def query(sql):
    return (
        output(
            [
                "docker",
                "exec",
                PROJECT + "-postgres-1",
                "psql",
                "-U",
                "polaris",
                "-d",
                "polaris",
                "-Atc",
                sql,
            ]
        )
        .decode()
        .strip()
    )


def wait_healthy(role):
    for _ in range(90):
        live = inspect(PROJECT + "-" + role + "-1")
        if live["State"].get("Health", {}).get("Status") == "healthy":
            return
        if not live["State"]["Running"]:
            raise ValueError("Container exited before readiness: " + role)
        time.sleep(2)
    raise TimeoutError("Container did not become healthy: " + role)


def rehearse(root):
    manifest = json.loads((root / "manifest.json").read_text())
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from backup_restore import main as restore_drill

    restore_drill(
        manifest["revision"],
        manifest["backend_image"],
        expected_before=manifest["schema_before"],
        expected_after="20261110_0051",
        preserve_existing_voices=True,
    )
    result = (
        Path("/opt/polaris/backups/video-studio-" + manifest["revision"][:12])
        / "manifest.json"
    )
    proof = json.loads(result.read_text())
    assert proof["restore_passed"] and proof["production_unchanged"]
    save(
        root / "rehearsal-proof.json",
        {
            "manifest": str(result),
            "sha256": digest(result),
            "schema_after": proof["schema_after_rehearsal"],
        },
    )


def verify(root):
    manifest = json.loads((root / "manifest.json").read_text())
    current = {
        role: inspect(PROJECT + "-" + role + "-1") for role in (*ROLES, *NEW_ROLES)
    }
    for role in ("video-api", "frontend", "caddy", "editing-worker"):
        if current[role]["State"].get("Health", {}).get("Status") != "healthy":
            raise ValueError("Release service is not healthy: " + role)
    if not current["editing-maintenance"]["State"]["Running"]:
        raise ValueError("Editing maintenance is not running")
    for name, old in manifest["baseline"].items():
        if name not in {PROJECT + "-" + role + "-1" for role in ROLES}:
            now = inspect(name)
            if (now["Id"], now["Image"]) != (old["id"], old["image"]):
                raise ValueError(
                    "Unrelated service changed during video release: " + name
                )
    assert (
        current["video-api"]["Image"]
        == current["editing-worker"]["Image"]
        == manifest["backend_image"]
    )
    assert current["frontend"]["Image"] == manifest["frontend_image"]
    assert environment(current["video-api"])["POLARIS_AUTH_MODE"] == "external"
    assert query("select version_num from alembic_version;") == "20261110_0051"
    save(
        root / "deployment-result.json",
        {
            "revision": manifest["revision"],
            "schema": "20261110_0051",
            "status": "healthy",
            "services": {
                role: {"id": value["Id"], "image": value["Image"]}
                for role, value in current.items()
            },
            "unrelated_services_unchanged": True,
            "authentication_preserved": True,
            "paid_generation_submissions": 0,
        },
    )
    print(
        json.dumps(
            {
                "revision": manifest["revision"],
                "status": "healthy",
                "schema": "20261110_0051",
                "unrelated_services_unchanged": True,
            }
        ),
        flush=True,
    )


def apply(root):
    manifest = json.loads((root / "manifest.json").read_text())
    proof = json.loads((root / "rehearsal-proof.json").read_text())
    assert digest(proof["manifest"]) == proof["sha256"]
    assert proof["schema_after"] == "20261110_0051"
    for role in ROLES:
        live = inspect(PROJECT + "-" + role + "-1")
        assert live["Id"] == manifest["baseline"][PROJECT + "-" + role + "-1"]["id"]
    if (
        query(
            "select count(*) from video_generations "
            "where status in ('queued','running');"
        )
        != "0"
    ):
        raise ValueError("Wait for existing video generations before cutover")
    assert (
        query("select version_num from alembic_version;") == manifest["schema_before"]
    )
    # Fresh paired backup immediately before the additive production migration.
    backup(root)
    media = environment(inspect(PROJECT + "-video-api-1"))["POLARIS_VIDEO_MEDIA_DIR"]
    with (root / "video-media-before.tar.gz").open("xb") as stream:
        run(
            [
                "docker",
                "exec",
                PROJECT + "-video-api-1",
                "tar",
                "-czf",
                "-",
                "-C",
                media,
                ".",
            ],
            stdout=stream,
        )
    run(
        ["docker", "volume", "create", "polaris-production_editing_data"],
        stdout=subprocess.DEVNULL,
    )
    run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--user",
            "0",
            "-v",
            "polaris-production_editing_data:/work",
            manifest["backend_image"],
            "chown",
            "10001:10001",
            "/work",
        ]
    )
    if manifest["caddy_changed"]:
        compose(
            root,
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "caddy",
            "caddy",
            "validate",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        )
    with (root / "migration.log").open("xb") as log:
        compose_command = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--env-file",
            str(root / "runtime.env"),
        ]
        network = next(
            iter(inspect(PROJECT + "-video-api-1")["NetworkSettings"]["Networks"])
        )
        run(
            [
                *compose_command,
                "--network",
                network,
                manifest["backend_image"],
                "python",
                "-m",
                "alembic",
                "upgrade",
                "head",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        compose(
            root, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "video-api"
        )
        wait_healthy("video-api")
        compose(
            root, "up", "-d", "--no-deps", "--no-build", "--pull", "never", *NEW_ROLES
        )
        wait_healthy("editing-worker")
        compose(
            root,
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            "frontend",
            *(["caddy"] if manifest["caddy_changed"] else []),
        )
        wait_healthy("frontend")
        wait_healthy("caddy")
        verify(root)
    except Exception:
        # Append-only migrations remain. Rollback uses the exact observed old
        # images/configuration and retains both the editing and video volumes.
        subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                PROJECT,
                "-f",
                str(root / "active.compose.private.json"),
                "stop",
                *NEW_ROLES,
            ],
            check=False,
        )
        run(
            [
                "docker",
                "compose",
                "-p",
                PROJECT,
                "-f",
                str(root / "rollback.compose.private.json"),
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--pull",
                "never",
                *ROLES,
            ]
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=["prepare", "backup", "rehearse", "apply", "verify"],
        required=True,
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--backend-image")
    parser.add_argument("--frontend-image")
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare(
            args.root,
            args.revision,
            args.assets,
            args.backend_image,
            args.frontend_image,
        )
    elif args.phase == "backup":
        backup(args.root)
    elif args.phase == "rehearse":
        rehearse(args.root)
    elif args.phase == "apply":
        apply(args.root)
    elif args.phase == "verify":
        verify(args.root)


if __name__ == "__main__":
    main()
