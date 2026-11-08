"""Align an operator candidate against real audio; never label it user-approved."""

import argparse
from pathlib import Path

from app.motion_library import read_json, sha256
from app.video_editing_alignment import align_transcript
from app.video_editing_contracts import Transcript


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-instance", required=True, type=Path)
    parser.add_argument("--text", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--revision-id", required=True)
    args = parser.parse_args()
    parent_path = args.source_instance / "transcript.json"
    result = align_transcript(
        args.source_instance / "input/speech.wav",
        read_json(args.source_instance / "prepared.json"),
        Transcript.model_validate(read_json(parent_path)),
        sha256(parent_path),
        args.text.read_text(encoding="utf-8"),
        args.revision_id,
        "operator_candidate",
        args.bundle,
        args.out,
    )
    print(
        f"Aligned {len(result.tokens)} measured units; "
        "text and timing remain unreviewed."
    )


if __name__ == "__main__":
    main()
