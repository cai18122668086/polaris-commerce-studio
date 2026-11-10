"""All 132 static audits or concrete native evidence import; never edits source."""

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.motion_library import atomic_json
from app.motion_library_validation import (
    audit,
    motion_evidence_directory,
    record_failure,
    record_native,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--native-report", type=Path)
    parser.add_argument("--native-failure", type=Path)
    parser.add_argument(
        "--state-dir", type=Path, help="Release-specific evidence directory"
    )
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    if args.native_report and args.native_failure:
        parser.error("Choose one concrete success or failure receipt")
    if args.native_report or args.native_failure:
        if not args.instance:
            parser.error("Native evidence needs --instance")
        settings = Settings(
            video_editing_ffmpeg=args.ffmpeg, video_editing_ffprobe=args.ffprobe
        )
        state = args.state_dir
        if state is None:
            if settings.video_editing_library_evidence_dir is None:
                parser.error(
                    "Native evidence needs --state-dir or "
                    "POLARIS_VIDEO_EDITING_LIBRARY_EVIDENCE_DIR"
                )
            state = motion_evidence_directory(settings)
        if args.native_report:
            result = record_native(
                args.package, state, args.instance, args.native_report, settings
            )
        else:
            result = record_failure(
                args.package, state, args.instance, args.native_failure
            )
    else:
        if not args.output:
            parser.error("An all-group static audit needs --output")
        result = audit(args.package)
    if args.output:
        atomic_json(args.output, result)
    print(
        json.dumps(
            {
                "groups": len(result.get("groups", [])),
                "group_id": result.get("group_id"),
                "scope": result["scope"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
