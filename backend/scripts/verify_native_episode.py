"""Compile an explicit candidate episode, optionally render through the original CLI.

No model request is made. Operator candidates are never gateway/user approvals.
"""

import argparse
import shutil
import sys
from pathlib import Path

from app.config import Settings
from app.motion_library import read_json, sha256, verify_package
from app.video_editing_contracts import SemanticPlan, Transcript
from app.video_editing_episode_compiler import EpisodeRecipeBundle, compile_episode
from app.video_editing_pipeline import native_export, prepare, validate_result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-instance", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--recipes", required=True, type=Path)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument(
        "--source-subtitles", required=True, choices=["none", "present"]
    )
    parser.add_argument("--choice-snapshot", type=Path)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    parent = args.source_instance
    root = args.out.resolve()
    if root.exists():
        raise FileExistsError("Preserve previous episode output; choose a new instance")
    settings = Settings(
        _env_file=None,
        video_editing_enabled=True,
        video_editing_library_dir=args.library,
        video_editing_ffmpeg=args.ffmpeg,
        video_editing_ffprobe=args.ffprobe,
        video_editing_python=sys.executable,
    )
    transcript = Transcript.model_validate(read_json(parent / "transcript.json"))
    verify_package(args.library)
    bundle = EpisodeRecipeBundle.model_validate(read_json(args.recipes))
    if bundle.planning_origin != "operator_candidate":
        raise ValueError("This operator CLI cannot assert a verified gateway origin")
    prepared = prepare(
        parent / "input/source.mp4",
        transcript.source_sha256,
        root,
        settings,
        lambda: None,
    )
    shutil.copyfile(parent / "transcript.json", root / "transcript.json")
    compile_episode(
        root,
        prepared,
        transcript,
        SemanticPlan.model_validate(read_json(args.plan)),
        bundle,
        {},
        {
            "caption_font_id": "font-d1961be1161ea1be",
            "source_subtitles": args.source_subtitles,
        },
        settings,
        read_json(args.choice_snapshot) if args.choice_snapshot else None,
    )
    print(
        "Compiled original episode/selection/bindings; "
        "semantics and quality unreviewed.",
        flush=True,
    )
    if args.render:
        final = native_export(root, settings, lambda: None)
        validate_result(final, prepared, root, settings, lambda: None)
        print("Rendered and fully decoded:", final, sha256(final), flush=True)


if __name__ == "__main__":
    main()
