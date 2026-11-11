"""Atomically install seven explicitly validated local caption revisions.

Old videos remain in place and the old manifest is backed up. The native B-roll
reference remains unchanged. This changes local examples, never a production Site.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.motion_library import atomic_json, read_json, sha256

FILMS = {
    "product-explainer-v1": ("product", 3.5),
    "knowledge-talk-v1": ("knowledge", 6),
    "presenter-openings-v1": ("presenter-final", 1.5),
    "rotation-cards-v1": ("rotation", 11.5),
    "azl-panels-v1": ("magazine", 8),
    "unified-chapter-v1": ("chapter", 6.6),
    "unified-paper-typewriter-v1": ("paper", 8.5),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="C:/tl/tools/bin/ffmpeg.exe")
    args = parser.parse_args()
    root, examples = args.review.resolve(), args.examples.resolve()
    manifest_file = examples / "manifest.json"
    manifest_hash = sha256(manifest_file)
    manifest = read_json(manifest_file)
    before = json.loads(json.dumps(manifest))
    backup = root / "example-manifest-before.json"
    if backup.exists():
        raise ValueError("Use a new review directory for a new example installation")
    staged = []
    for tid, (folder, at) in FILMS.items():
        receipt = read_json(root / folder / "replay-evidence.json")
        master = root / folder / "outputs/episode.mp4"
        entry = manifest["examples"][tid]
        if (
            receipt["new_provider_calls"] != 0
            or receipt["validation"]["decoded"] is not True
            or receipt["validation"]["caption_presentation"]["status"] != "passed"
            or sha256(master) != receipt["sha256"]
            or entry["video"]["sha256"] != receipt["original_master_sha256"]
            or sha256(examples / entry["video"]["file"]) != entry["video"]["sha256"]
        ):
            raise ValueError(f"Current example or verified revision changed: {tid}")
        video = examples / ("caption-fixed-" + tid + ".mp4")
        poster = video.with_suffix(".jpg")
        if video.exists() or poster.exists():
            raise ValueError(f"Revision filename already exists: {tid}")
        staged.append((tid, master, video, poster, at))
    shutil.copyfile(manifest_file, backup)
    for tid, master, video, poster, at in staged:
        shutil.copyfile(master, video)
        subprocess.run(
            [
                args.ffmpeg,
                "-v",
                "error",
                "-n",
                "-ss",
                str(at),
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-vf",
                "scale=360:640",
                str(poster),
            ],
            check=True,
        )
        entry = manifest["examples"][tid]
        entry["video"] = {"file": video.name, "sha256": sha256(video)}
        entry["poster"] = {"file": poster.name, "sha256": sha256(poster)}
        entry["metadata"]["title"] += "·字幕与衔接修正版"
    # Fail closed if another window installed new examples during preparation.
    if sha256(manifest_file) != manifest_hash:
        raise ValueError(
            "Example manifest changed concurrently; no pointer was updated"
        )
    if manifest["style_previews"] != before["style_previews"]:
        raise ValueError("Native style references must remain unchanged")
    atomic_json(manifest_file, manifest)
    atomic_json(
        root / "example-installation.json",
        {
            "previous_manifest_sha256": manifest_hash,
            "installed_manifest_sha256": sha256(manifest_file),
            "backup": str(backup),
            "examples": str(examples),
            "updated_template_ids": list(FILMS),
            "native_references_preserved": True,
            "new_provider_calls": 0,
            "production_deployment": False,
        },
    )
    print("Installed seven local caption revisions; native references preserved.")


if __name__ == "__main__":
    main()
