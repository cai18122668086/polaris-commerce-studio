"""Local acceptance run: real user media, real ASR/native render, real API return.

Creates an isolated local project and database. Never generates a new avatar,
calls a paid provider, accesses production data or claims human acceptance.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.motion_library import atomic_json, read_json, sha256
from app.video_studio_schemas import VideoProjectContent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--provider", choices=["faster-whisper", "funasr"], default="faster-whisper"
    )
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    root = args.runtime.resolve()
    root.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        environment="test",
        auth_mode="development",
        development_user_email="1474953130@qq.com",
        database_url=f"sqlite:///{root / 'acceptance.db'}",
        auto_create_schema=True,
        storage_backend="local",
        storage_dir=root / "storage",
        auto_process_jobs=False,
        task_dispatcher="inline",
        task_runner="mock",
        video_media_dir=root / "video",
        ecommerce_startup_recovery_enabled=False,
        video_editing_enabled=True,
        video_editing_library_dir=args.library.resolve(),
        video_editing_tasks_dir=root / "tasks",
        video_editing_python=sys.executable,
        video_editing_ffmpeg=str((args.tools / "ffmpeg.exe").resolve()),
        video_editing_ffprobe=str((args.tools / "ffprobe.exe").resolve()),
        video_editing_asr_model=args.model,
        video_editing_asr_provider=args.provider,
    )
    app = create_app(settings)
    app.state.editing_dispatcher = lambda task_id: None  # Explicit CLI launch below.
    receipt_path = root / "acceptance.json"
    with TestClient(app) as client:
        ws = client.get("/api/v1/workspaces").json()[0]["id"]
        base = f"/api/v1/video-studio/workspaces/{ws}"
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            if receipt["source_sha256"] != sha256(args.source):
                raise ValueError(
                    "Acceptance source changed; use a new runtime directory"
                )
        else:
            pid = str(uuid4())
            content = VideoProjectContent()
            content.draft.name = "真实原片剪辑验证"
            body = {
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "content": content.model_dump(mode="json"),
                "action": "save",
            }
            result = client.put(base + "/projects/" + pid, json=body)
            result.raise_for_status()
            with args.source.open("rb") as media:
                uploaded = client.post(
                    base + "/editing-sources",
                    data={"project_id": pid},
                    files={"file": (args.source.name, media, "video/mp4")},
                )
            uploaded.raise_for_status()
            task = client.post(
                base + "/editing-tasks",
                json={
                    "request_id": str(uuid4()),
                    "source_id": uploaded.json()["id"],
                    "options": {"source_subtitles": "none"},
                },
            )
            task.raise_for_status()
            receipt = {
                "source_name": args.source.name,
                "source_sha256": sha256(args.source),
                "workspace_id": ws,
                "project_id": pid,
                "task_id": task.json()["id"],
                "new_paid_calls": 0,
                "deployment": "local_only",
                "user_acceptance": "pending",
            }
            atomic_json(receipt_path, receipt)
        if args.render:
            state = client.get(base + "/editing-tasks/" + receipt["task_id"]).json()
            if state["status"] in {"failed", "cancelled"}:
                client.post(
                    base + "/editing-tasks/" + receipt["task_id"] + "/retry"
                ).raise_for_status()
            env = os.environ.copy()
            overrides = {
                "database_url": settings.database_url,
                "video_editing_enabled": "true",
                "video_editing_library_dir": str(settings.video_editing_library_dir),
                "video_editing_tasks_dir": str(settings.video_editing_tasks_dir),
                "video_editing_python": sys.executable,
                "video_editing_ffmpeg": settings.video_editing_ffmpeg,
                "video_editing_ffprobe": settings.video_editing_ffprobe,
                "video_editing_asr_model": args.model,
                "video_editing_asr_provider": args.provider,
            }
            env.update({"POLARIS_" + k.upper(): str(v) for k, v in overrides.items()})
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("run_editing_worker.py")),
                    "--once",
                    receipt["task_id"],
                ],
                check=True,
                env=env,
            )
        result = client.get(base + "/editing-tasks/" + receipt["task_id"])
        result.raise_for_status()
        task = result.json()
        receipt.update(
            status=task["status"], stage=task["stage"], error_code=task["error_code"]
        )
        if task["status"] == "completed":
            artifacts = []
            for item in task["artifacts"]:
                response = client.get(item["url"])
                response.raise_for_status()
                import hashlib

                if hashlib.sha256(response.content).hexdigest() != item["sha256"]:
                    raise ValueError(
                        "Website download hash differs from validated artifact"
                    )
                artifacts.append({**item, "http_status": response.status_code})
                if item["role"] == "final":
                    (root / "website-download.mp4").write_bytes(response.content)
            final = next(x for x in artifacts if x["role"] == "final")
            partial = client.get(final["url"], headers={"Range": "bytes=0-1023"})
            if partial.status_code != 206 or len(partial.content) != 1024:
                raise ValueError("Website video range playback failed")
            receipt.update(
                artifacts=artifacts, range_playback_status=partial.status_code
            )
        atomic_json(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        if args.render and task["status"] != "completed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
