"""Choose a safe native BG-S03 outline using the original role checker."""

import argparse
import copy
import importlib
import os
import sys
from pathlib import Path

from .motion_library import atomic_json, read_json, sha256

BG_OFFSET_GROUP = "BG-S03"
_OUTLINE_COLOR = "#151419"
_PROFILES = {"both": (1, 1), "body": (1, 0), "clear": (0, 0)}
_PINNED = {
    "commercial_runtime/layout.py": (
        "54dd2899595aeb68859d6c5e5e00cfd25a44e43e021df3639edf315d27ee1d88"
    ),
    "commercial_runtime/native.py": (
        "2b1c213087a59ada597fda3d9fd7c412b857d920fb04635278ae180b46bfafea"
    ),
    "src/engines/workspace/字幕动效_可编辑库_20261105/BG-S03/render.py": (
        "5e590479df8c289171836d0945f1e137a1cb895aa93f104bc5ff3018cf816f1f"
    ),
}


def apply_outline(config: dict, profile: str) -> None:
    for role, stroke in zip(("body", "focus"), _PROFILES[profile], strict=True):
        config["fonts"][role].update(outline_px=stroke, outline_color=_OUTLINE_COLOR)


def check_profiles(package: Path, job_path: Path) -> dict:
    package, job_path = package.resolve(), job_path.resolve()
    root = job_path.parent
    job = read_json(job_path)
    if (
        root.is_relative_to(package)
        or job_path.name != "job.json"
        or job["group_id"] != BG_OFFSET_GROUP
        or any(sha256(package / path) != digest for path, digest in _PINNED.items())
    ):
        raise ValueError("BG-S03 outline needs the original native role checker")
    os.environ["COMMERCIAL_INSTANCE"] = str(root)
    os.environ["COMMERCIAL_BINDINGS"] = str(root / "bindings.json")
    sys.path.insert(0, str(package))
    try:
        isolation = importlib.import_module("commercial_runtime.isolation")
        layout = importlib.import_module("commercial_runtime.layout")
        isolation.install()
        checked = []
        for profile in _PROFILES:
            candidate = copy.deepcopy(job)
            apply_outline(candidate["config"], profile)
            report = layout.role_review(candidate)
            if not report["supported"]:
                raise ValueError("BG-S03 original checker cannot separate the roles")
            collisions = report["role_collisions"]
            checked.append(
                {
                    "profile": profile,
                    "frames_checked": report["frames_checked"],
                    "collision_frames": len(collisions),
                }
            )
            if not collisions:
                return {"selected": profile, "checks": checked}
        return {"selected": None, "checks": checked}
    finally:
        sys.path.pop(0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    report = check_profiles(args.package, args.job)
    atomic_json(args.job.parent / "readability.json", report)


if __name__ == "__main__":
    main()
