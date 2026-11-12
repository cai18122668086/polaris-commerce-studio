"""Replay an explicit existing website example in a fresh directory, offline.

Uses the same presentation functions as the compiler. Sealed original shots are
relocated only after the existing recovery adapter verifies their full inputs.
Changed scene tails are rendered again. Original files and the example manifest
are read-only; there are no HTTP clients, providers, database writes or deploys.
"""

import argparse
import copy
import importlib
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import Settings
from app.motion_library import atomic_json, read_json, sha256, verify_package
from app.video_editing_azl_panels import azl_backing
from app.video_editing_caption_presentation import (
    bridge_scene_gaps,
    readable_caption_rows,
    register_caption_backings,
    remove_duplicate_captions,
    reserve_caption_lane,
)
from app.video_editing_captioning import write_caption_receipt
from app.video_editing_contracts import Transcript
from app.video_editing_native_shot_recovery import _restore_shot
from app.video_editing_pipeline import (
    layout_captions,
    native_export,
    validate_result,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument("--validate-existing", action="store_true")
    args = parser.parse_args()
    previous, root = args.previous.resolve(), args.output.resolve()
    if not args.validate_existing:
        root.mkdir(parents=True, exist_ok=False)
    package = Path("C:/tl/clean-motion-install-20261110/c10429057a86/motion")
    verify_package(package)
    settings = Settings(
        _env_file=None,
        environment="test",
        video_editing_library_dir=package,
        video_editing_tasks_dir=root.parent,
        video_editing_python=sys.executable,
        video_editing_ffmpeg="C:/tl/tools/bin/ffmpeg.exe",
        video_editing_ffprobe="C:/tl/tools/bin/ffprobe.exe",
        video_editing_native_bindings_file=Path(
            "C:/tl/dependency-binding/original-bindings.json"
        ),
    )
    original_hashes = {p.name: sha256(p) for p in previous.glob("*.json")}
    if args.validate_existing:
        master = root / "outputs/episode.mp4"
        validation = validate_result(
            master, read_json(root / "prepared.json"), root, settings, lambda: None
        )
        atomic_json(
            root / "replay-evidence.json",
            {
                "previous": str(previous),
                "master": str(master),
                "sha256": sha256(master),
                "original_master_sha256": sha256(previous / "outputs/episode.mp4"),
                "new_provider_calls": 0,
                "presentation": read_json(root / "episode.json")["editorial"][
                    "caption_presentation"
                ],
                "validation": validation,
                "original_json_preserved": all(
                    sha256(previous / name) == digest
                    for name, digest in original_hashes.items()
                ),
            },
        )
        print(f"Validated existing {master}", flush=True)
        return

    def relocate(value):
        if isinstance(value, dict):
            return {key: relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        if isinstance(value, str):
            normalized = value.replace("\\", "/")
            prefix = previous.as_posix() + "/"
            if normalized.casefold().startswith(prefix.casefold()):
                return str(root / normalized[len(prefix) :])
        return value

    for name in ("input", "cache", "compiled-native"):
        if (previous / name).is_dir():
            # Inputs are immutable throughout export; generated caches are copied.
            def clone(source, target, folder=name):
                if folder == "input":
                    try:
                        os.link(source, target)
                        return target
                    except OSError:
                        pass
                return shutil.copyfile(source, target)

            shutil.copytree(previous / name, root / name, copy_function=clone)
    for path in previous.glob("*.json"):
        if "validation" in path.name or path.name.startswith(
            ("native-", "validation", "preview-validation", "runtime-")
        ):
            continue
        atomic_json(root / path.name, relocate(read_json(path)))
    # Preserve the exact transcript bytes to keep its source-version digest.
    shutil.copyfile(previous / "transcript.json", root / "transcript.json")
    episode = relocate(read_json(previous / "episode.json"))
    transcript = Transcript.model_validate(read_json(root / "transcript.json"))
    anchors = readable_caption_rows(transcript)
    episode["captions"] = [
        {key: row[key] for key in ("text", "start_seconds", "end_seconds")}
        for row in anchors
    ]
    bridges = bridge_scene_gaps(episode, read_json(root / "bindings.json"))
    removed = remove_duplicate_captions(episode, anchors)
    layout_captions(episode, copy.deepcopy(episode["captions"]), settings)
    presentation = reserve_caption_lane(episode, removed, bridges)
    selection = read_json(root / "selection.json")
    register_caption_backings(episode, selection)
    atomic_json(root / "selection.json", selection)
    for index, shot in enumerate(episode["shots"]):
        if shot["group_id"].startswith("AZL"):
            backing = azl_backing(shot, episode, index)
            episode["visual_scenes"] = [
                backing if row["id"] == backing["id"] else row
                for row in episode["visual_scenes"]
            ]
    atomic_json(root / "episode.json", episode)
    atomic_json(root / "caption-anchors.json", anchors)
    atomic_json(
        root / "caption-adapter-layout.json",
        episode["editorial"]["caption_line_layout"],
    )
    write_caption_receipt(root, transcript, anchors, True)
    report = {
        "previous": str(previous),
        "original_master_sha256": sha256(previous / "outputs/episode.mp4"),
        "new_provider_calls": 0,
        "presentation": presentation,
    }
    if args.compile_only:
        atomic_json(root / "replay-evidence.json", report)
        print("Prepared explicit offline caption revision", flush=True)
        return
    sys.path.insert(0, str(package))
    adapter = importlib.import_module("adapter")
    restored = []
    subtitles = {
        row["id"]
        for row in read_json(package / "catalog/groups.json")["groups"]
        if row["kind"] == "subtitle"
    }
    for index, shot in enumerate(episode["shots"]):
        output = root / "renders" / f"{index:03}-{shot['group_id']}.mp4"
        job = adapter.prepared_job(
            {
                "schema": "commercial-talk-job/1",
                "group_id": shot["group_id"],
                "config": shot["config"],
                "output": str(output),
            },
            root,
        )
        if _restore_shot(
            previous,
            root,
            output,
            job,
            sha256(package / "integrity.json"),
            shot["group_id"] in subtitles,
        ):
            restored.append(index)
    print(f"Reused {len(restored)} sealed unchanged native shots", flush=True)
    master = native_export(root, settings, lambda: None)
    validation = validate_result(
        master, read_json(root / "prepared.json"), root, settings, lambda: None
    )
    assert all(
        sha256(previous / name) == digest for name, digest in original_hashes.items()
    )
    report.update(
        master=str(master),
        sha256=sha256(master),
        validation=validation,
        restored_shots=restored,
        original_json_preserved=True,
    )
    atomic_json(root / "replay-evidence.json", report)
    print(f"Validated {master}", flush=True)


if __name__ == "__main__":
    main()
