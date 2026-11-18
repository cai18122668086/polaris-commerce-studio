"""Update the video API from its observed image and retain an exact rollback."""

import argparse
import copy
import json
import re
import sys
from pathlib import Path

from integrated_release import (
    PROJECT,
    compose,
    composition,
    digest,
    environment,
    escaped,
    inspect,
    observed,
    output,
    query,
    run,
    save,
    wait_healthy,
)

NAME = PROJECT + "-video-api-1"


def prepare(root, revision, image, base_image):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Full source revision required")
    if not all(
        re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in (image, base_image)
    ):
        raise ValueError("Immutable image IDs required")
    credentials = json.load(sys.stdin)
    if set(credentials) != {"POLARIS_YIYUAN_API_KEY"}:
        raise ValueError("Only the Yiyuan server credential may be supplied")
    key = credentials["POLARIS_YIYUAN_API_KEY"]
    if not isinstance(key, str) or not key or "\n" in key or "\r" in key:
        raise ValueError("Single-line Yiyuan credential required")
    names = output(["docker", "ps", "-a", "--format", "{{.Names}}"]).decode().split()
    live = {name: inspect(name) for name in names}
    current = live[NAME]
    if current["Image"] != base_image:
        raise ValueError("Live video API changed; rebuild from the current image")
    if current["State"].get("Health", {}).get("Status") != "healthy":
        raise ValueError("Existing video API is not healthy")
    runtime = environment(current)
    if (
        runtime.get("POLARIS_AUTH_MODE") != "external"
        or runtime.get("POLARIS_VIDEO_PROVIDERS_ENABLED") != "true"
        or not runtime.get("POLARIS_WUYE_API_KEY")
    ):
        raise ValueError(
            "Existing authentication, video service and H3 backup required"
        )
    service = observed(current)
    if service.get("ports"):
        raise ValueError("Video API must retain private networking")
    rollback = composition({"video-api": copy.deepcopy(service)})
    runtime["POLARIS_YIYUAN_API_KEY"] = key
    service.update(image=image, environment=escaped(runtime))
    service.setdefault("labels", {})["com.polaris.avatar_template.revision"] = revision
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    save(root / "active.compose.private.json", composition({"video-api": service}))
    save(root / "rollback.compose.private.json", rollback)
    save(
        root / "manifest.json",
        {
            "revision": revision,
            "image": image,
            "base_image": base_image,
            "baseline": {
                name: {"id": value["Id"], "image": value["Image"]}
                for name, value in live.items()
            },
            "schema_before": query("select version_num from alembic_version;"),
            "changed_services": ["video-api"],
        },
    )
    compose(root, "config", "--quiet")
    print("Prepared video API upgrade and rollback", flush=True)


def verify(root, *, rollback=False):
    manifest = json.loads((root / "manifest.json").read_text())
    for name, baseline in manifest["baseline"].items():
        if name == NAME:
            continue
        current = inspect(name)
        if (current["Id"], current["Image"]) != (baseline["id"], baseline["image"]):
            raise ValueError("Another service changed during the release: " + name)
    wait_healthy("video-api")
    current = inspect(NAME)
    expected = manifest["base_image"] if rollback else manifest["image"]
    if current["Image"] != expected:
        raise ValueError("Unexpected video API image")
    if environment(current).get("POLARIS_AUTH_MODE") != "external":
        raise ValueError("Authentication changed")
    if not rollback and not environment(current).get("POLARIS_YIYUAN_API_KEY"):
        raise ValueError("Yiyuan credential missing")
    if query("select version_num from alembic_version;") != manifest["schema_before"]:
        raise ValueError("Unexpected schema change")
    result = {
        "revision": manifest["revision"],
        "status": "rolled_back" if rollback else "healthy",
        "changed_services": ["video-api"],
        "unrelated_services_unchanged": True,
        "schema_unchanged": True,
    }
    save(
        root / ("rollback-result.json" if rollback else "deployment-result.json"),
        result,
    )
    print(json.dumps(result), flush=True)


def apply(root):
    manifest = json.loads((root / "manifest.json").read_text())
    if inspect(NAME)["Id"] != manifest["baseline"][NAME]["id"]:
        raise ValueError("Video API changed since preparation")
    if (
        query(
            "select count(*) from video_generations where status in ('queued','running');"
        )
        != "0"
    ):
        raise ValueError("Wait for active video generation before cutover")
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
    media = environment(inspect(NAME))["POLARIS_VIDEO_MEDIA_DIR"]
    with (root / "video-media-before.tar.gz").open("xb") as stream:
        run(
            ["docker", "exec", NAME, "tar", "-czf", "-", "-C", media, "."],
            stdout=stream,
        )
    save(
        root / "backup-manifest.json",
        {
            name: {"sha256": digest(root / name), "bytes": (root / name).stat().st_size}
            for name in ("database-before.dump", "video-media-before.tar.gz")
        },
    )
    if (
        query(
            "select count(*) from video_generations where status in ('queued','running');"
        )
        != "0"
    ):
        raise ValueError("A video task started during preparation; wait before cutover")
    try:
        compose(
            root, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "video-api"
        )
        verify(root)
    except Exception:
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
                "video-api",
            ]
        )
        verify(root, rollback=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "apply", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--image")
    parser.add_argument("--base-image")
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare(args.root, args.revision, args.image, args.base_image)
    elif args.phase == "apply":
        apply(args.root)
    else:
        verify(args.root)


if __name__ == "__main__":
    main()
