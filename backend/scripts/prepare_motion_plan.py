"""Build a reviewable full-library request; --execute is a billable operation."""

import argparse
from pathlib import Path

from app.config import Settings
from app.motion_library import atomic_json, read_json
from app.video_assistance_provider import VideoAssistanceProvider
from app.video_editing_contracts import Transcript
from app.video_editing_planner import build_request, generate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Makes one paid planning request; no automatic retry",
    )
    args = parser.parse_args()
    transcript = Transcript.model_validate(read_json(args.transcript))
    args.out.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=args.env_file,
        video_editing_library_dir=args.library.resolve(),
        video_editing_plan_model=args.model,
        video_editing_planning_enabled=args.execute,
    )
    if args.execute:
        generate(args.out, transcript, settings, VideoAssistanceProvider(settings))
        print(
            "One planning request submitted; review the saved response and validation."
        )
    else:
        request, evidence = build_request(transcript, args.library, args.model)
        atomic_json(args.out / "semantic-request.json", request)
        atomic_json(args.out / "semantic-request-evidence.json", evidence)
        print(
            f"Dry run: {evidence['catalog_group_count']} original groups; "
            f"{evidence['request_bytes']} bytes; model={args.model}; "
            "max_output_tokens=5000"
        )
        print("No model request submitted and no new model fees incurred.")


if __name__ == "__main__":
    main()
