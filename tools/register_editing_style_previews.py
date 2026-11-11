"""Install native component previews from explicit local receipt paths.

Every source must match an admitted library evidence receipt, input and output
hash. These are diagnostic native style snippets, NEVER full business films.
Does not call providers, synthesize speech or generate acceptance evidence.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.motion_library import atomic_json, read_json, sha256
from app.motion_library_validation import group_status
from app.video_editing_template_styles import STYLES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receipt-index",
        type=Path,
        required=True,
        help="UTF-8 newline-separated receipt paths",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="Release-scoped admitted evidence directory",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.json"
    manifest = (
        read_json(manifest_path)
        if manifest_path.is_file()
        else {"version": "tengli.template-examples/1", "examples": {}}
    )
    receipts = {}
    for line in args.receipt_index.read_text(encoding="utf-8-sig").splitlines():
        path = Path(line)
        if path.is_file():
            receipts[sha256(path)] = path
    previews, missing, selected = {}, {}, {}
    for tid, style in STYLES.items():
        if tid in {"product-explainer-v1", "knowledge-talk-v1"}:
            continue  # Their full deliveries remain separately labelled examples.
        candidates = []
        for gid in style["signature_group_ids"]:
            branch = (
                "input-B"
                if tid == "question-card-b-story-v1"
                else "input-A"
                if tid == "question-card-story-v1"
                else None
            )
            for evidence in group_status(args.evidence, gid, native_branch=branch)[
                "runtime_evidence"
            ]:
                if evidence["runtime_validation"] != "sample_rendered":
                    continue
                receipt_path = receipts.get(evidence["receipt_sha256"])
                if receipt_path is None:
                    continue
                receipt = read_json(receipt_path)
                output = Path(receipt["output"])
                normalized = (
                    receipt_path.parent.parent
                    / "plans"
                    / (output.stem + "-native-input.json")
                )
                if (
                    output.is_file()
                    and normalized.is_file()
                    and sha256(output) == evidence["output_sha256"]
                    and sha256(normalized) == evidence["input_sha256"]
                ):
                    candidates.append((evidence, receipt_path, output))
        if not candidates:
            missing[tid] = (
                "No explicitly indexed native sample matches the admitted "
                "receipt, input, output and branch."
            )
            continue
        evidence, receipt_path, source = candidates[0]
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
                    "stream=width,height:format=duration",
                    "-of",
                    "json",
                    str(source),
                ]
            )
        )
        duration_ms = round(float(info["format"]["duration"]) * 1000)
        video = args.output / f"style-{tid}.mp4"
        poster = args.output / f"style-{tid}.jpg"
        if video.exists() or poster.exists():
            raise ValueError(f"Refusing to overwrite an installed style preview: {tid}")
        shutil.copyfile(source, video)
        subprocess.run(
            [
                args.ffmpeg,
                "-v",
                "error",
                "-ss",
                str(duration_ms * 0.00045),
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
        previews[tid] = {
            "video": {"file": video.name, "sha256": sha256(video)},
            "poster": {"file": poster.name, "sha256": sha256(poster)},
            "metadata": {
                "title": style["name"] + " · 原生样式片段（非本期成片）",
                "group_id": evidence["group_id"],
                "native_branch": evidence.get("native_branch"),
                "duration_ms": duration_ms,
                **info["streams"][0],
            },
        }
        selected[tid] = {
            "receipt": str(receipt_path),
            "evidence_id": evidence["id"],
            "receipt_sha256": evidence["receipt_sha256"],
            "input_sha256": evidence["input_sha256"],
            "output_sha256": evidence["output_sha256"],
            "full_decode": True,
            "scope": "native_sample_only",
            "business_review": "pending",
        }
    manifest["style_previews"] = previews
    atomic_json(manifest_path, manifest)
    atomic_json(
        args.output / "style-preview-installation.json",
        {"installed": selected, "pending": missing, "paid_calls": 0},
    )
    print(
        json.dumps(
            {"installed": len(previews), "pending": list(missing), "paid_calls": 0},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
