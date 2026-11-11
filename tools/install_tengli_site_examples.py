"""Download and install the explicit five local operator demos, without providers.

Confirmation opens an existing staged master; it does not mark human review passed.
Public API downloads, hashes and full decode are recorded separately from AV review.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_template_styles import STYLES

TEMPLATES = (
    "presenter-openings-v1",
    "rotation-cards-v1",
    "azl-panels-v1",
    "unified-chapter-v1",
    "unified-paper-typewriter-v1",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8018)
    parser.add_argument("--confirm-existing-masters", action="store_true")
    parser.add_argument("--ffmpeg", default="C:/tl/tools/bin/ffmpeg.exe")
    parser.add_argument("--ffprobe", default="C:/tl/tools/bin/ffprobe.exe")
    args = parser.parse_args()
    root, examples = args.root, args.examples
    examples.mkdir(parents=True, exist_ok=True)
    manifest_path = examples / "manifest.json"
    manifest = read_json(manifest_path)
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{args.port}",
        headers={"X-User-Id": "usr_development"},
        trust_env=False,
        timeout=120,
    )
    api = "/api/v1/video-studio/workspaces/ws_development"
    reports = []
    for tid in TEMPLATES:
        adjustment = root / "adjustments" / tid
        task_id = read_json(adjustment / "preview-task.json")["id"]
        response = client.get(api + "/editing-tasks/" + task_id)
        response.raise_for_status()
        task = response.json()
        if task["status"] == "awaiting_review" and args.confirm_existing_masters:
            preview = next(a for a in task["artifacts"] if a["role"] == "preview")
            response = client.post(
                api + "/editing-tasks/" + task_id + "/confirm-export",
                json={
                    "preview_artifact_id": preview["id"],
                    "preview_sha256": preview["sha256"],
                },
            )
            response.raise_for_status()
            task = response.json()
        assert task["status"] == "completed", (tid, task["status"])
        final = next(a for a in task["artifacts"] if a["role"] == "final")
        output = root / "downloads" / (tid + ".mp4")
        output.parent.mkdir(exist_ok=True)
        if not output.exists() or sha256(output) != final["sha256"]:
            response = client.get(final["url"])
            response.raise_for_status()
            output.write_bytes(response.content)
        assert sha256(output) == final["sha256"]
        subprocess.run(
            [
                args.ffmpeg,
                "-v",
                "error",
                "-xerror",
                "-i",
                str(output),
                "-f",
                "null",
                "-",
            ],
            check=True,
        )
        probe = json.loads(
            subprocess.check_output(
                [
                    args.ffprobe,
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(output),
                ]
            )
        )
        video = next(s for s in probe["streams"] if s["codec_type"] == "video")
        audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
        assert (video["width"], video["height"]) == (1080, 1920)
        assert abs(float(probe["format"]["duration"]) - 36.271) < 0.2
        semantic = read_json(adjustment / "semantic.json")
        groups = {b["group_id"] for b in semantic["beats"] if b["group_id"] != "Z-M00"}
        assert len(groups) >= 5 and groups & set(STYLES[tid]["signature_group_ids"])
        installed = examples / ("tengli-" + tid + ".mp4")
        shutil.copyfile(output, installed)
        poster = installed.with_suffix(".jpg")
        poster_time = {
            "presenter-openings-v1": "1.5",
            "rotation-cards-v1": "11.5",
            "azl-panels-v1": "8",
            "unified-chapter-v1": "6.6",
            "unified-paper-typewriter-v1": "8.5",
        }[tid]
        subprocess.run(
            [
                args.ffmpeg,
                "-v",
                "error",
                "-y",
                "-ss",
                poster_time,
                "-i",
                str(installed),
                "-frames:v",
                "1",
                "-vf",
                "scale=360:640",
                str(poster),
            ],
            check=True,
        )
        paper = tid == "unified-paper-typewriter-v1"
        manifest["examples"][tid] = {
            "video": {"file": installed.name, "sha256": sha256(installed)},
            "poster": {"file": poster.name, "sha256": sha256(poster)},
            "metadata": {
                "title": "极光商绘·四个入口·"
                + ("人工编排样片" if paper else "人工调整版"),
                "round": "operator_authored" if paper else "replan",
                "origin": "operator_candidate",
                "distinct_groups": len(groups),
                "occurrences": len(semantic["beats"]),
                "width": video["width"],
                "height": video["height"],
            },
        }
        atomic_json(adjustment / "completed-task.json", task)
        reports.append(
            {
                "template_id": tid,
                "task_id": task_id,
                "file": str(output),
                "sha256": final["sha256"],
                "downloaded_through_public_api": True,
                "full_decode": "passed",
                "width": video["width"],
                "height": video["height"],
                "duration": float(probe["format"]["duration"]),
                "audio_codec": audio["codec_name"],
                "distinct_groups": sorted(groups),
                "occurrences": len(semantic["beats"]),
                "unmodified_model_first_pass": False,
                "model_response_for_this_template": not paper,
                "planning_origin": "operator_candidate",
                "human_review": task["review"],
            }
        )
        print(
            json.dumps(
                {"template": tid, "download_decode": "passed", "groups": len(groups)}
            ),
            flush=True,
        )
    atomic_json(manifest_path, manifest)
    atomic_json(
        root / "five-film-delivery.json",
        {"films": reports, "installation_paid_calls": 0},
    )


if __name__ == "__main__":
    main()
