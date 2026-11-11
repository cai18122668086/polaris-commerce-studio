"""Install explicitly selected genuine delivery examples, without a provider call.

Run with the backend environment: --output DIR --product EVIDENCE --knowledge EVIDENCE.
Each evidence JSON sits beside the corresponding website-*-verified-hd.mp4.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.motion_library import atomic_json, read_json, sha256  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--product", type=Path)
    parser.add_argument("--knowledge", type=Path)
    parser.add_argument(
        "--handoff",
        type=Path,
        help="Use genuine Huipin business deliveries in the handoff inventory",
    )
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    examples = {}
    for case, evidence_path in (
        ("product", args.product),
        ("knowledge", args.knowledge),
    ):
        if args.handoff:
            deliveries = read_json(args.handoff)["side_tree_real_gateway_deliveries"]
            choices = [
                row
                for row in deliveries
                if row["template_id"]
                == (
                    "product-explainer-v1" if case == "product" else "knowledge-talk-v1"
                )
            ]
            row = next(
                (row for row in choices if row["round"] == "1080 density replan"),
                choices[0],
            )
            source = Path(row["file"].replace("\\\\", "/"))
            digest = row["recorded_sha256"]
            counts = {key: row[key] for key in ("distinct_groups", "occurrences")}
            title = row["title"]
            round_name = "first" if row["round"] == "first" else "replan"
        else:
            if evidence_path is None:
                parser.error("Supply --handoff or both --product and --knowledge")
            evidence = read_json(evidence_path)
            source = evidence_path.parent / f"website-{case}-verified-hd.mp4"
            digest = evidence["download_sha256"]
            counts = evidence["motion_counts"]
            title = (
                "真实口播 · 产品讲解" if case == "product" else "真实口播 · 知识分享"
            )
            round_name = "recorded_response_replay"
            if not evidence["full_decode"]:
                raise ValueError("Delivery is not decoded")
        if sha256(source) != digest:
            raise ValueError("Delivery evidence does not match the selected film")
        if not counts["occurrences"] >= counts["distinct_groups"] >= 5:
            raise ValueError("Example has fewer than five distinct effects")
        subprocess.run(
            [
                args.ffmpeg,
                "-v",
                "error",
                "-xerror",
                "-i",
                str(source),
                "-f",
                "null",
                "-",
            ],
            check=True,
        )
        info = json.loads(
            subprocess.check_output(
                [
                    args.ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "json",
                    str(source),
                ]
            )
        )["streams"][0]
        video = args.output / f"{case}.mp4"
        shutil.copyfile(source, video)
        poster = args.output / f"{case}.jpg"
        subprocess.run(
            [
                args.ffmpeg,
                "-y",
                "-v",
                "error",
                "-ss",
                "4",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-vf",
                "scale=480:-2",
                str(poster),
            ],
            check=True,
        )
        examples[
            "product-explainer-v1" if case == "product" else "knowledge-talk-v1"
        ] = {
            "video": {"file": video.name, "sha256": sha256(video)},
            "poster": {"file": poster.name, "sha256": sha256(poster)},
            "metadata": {
                "title": title,
                "round": round_name,
                **counts,
                **info,
            },
        }
    atomic_json(
        args.output / "manifest.json",
        {"version": "tengli.template-examples/1", "examples": examples},
    )
    print("Installed two hash-verified real delivery examples; no provider calls.")


if __name__ == "__main__":
    main()
