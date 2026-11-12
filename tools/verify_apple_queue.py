"""Exercise real suite delivery with a local protocol fixture and zero API calls.

Creates a NEW isolated SQLite/app directory. Reuses measured words from a supplied
transcript, shifted onto an actual source crop; it does not claim fresh ASR or
model matching quality. The fixture provider is injected directly into the queue.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import Settings
from app.main import create_app
from app.motion_library import MOTION_SHA256, atomic_json, sha256
from app.video_editing_contracts import Transcript, TranscriptUtterance
from app.video_editing_planning_worker import process as plan_process
from app.video_editing_task_models import EditingArtifactRecord, EditingTaskRecord
from app.video_editing_worker import process as render_process
from app.video_studio_schemas import VideoProjectContent
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--transcript", type=Path, required=True)
    p.add_argument("--material", type=Path, required=True)
    p.add_argument("--library", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--start", type=float, default=12.8)
    p.add_argument("--duration", type=float, default=7.6)
    p.add_argument("--ffmpeg", default="C:/tl/tools/bin/ffmpeg.exe")
    p.add_argument("--ffprobe", default="C:/tl/tools/bin/ffprobe.exe")
    a = p.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    clip = out / "source.mp4"
    subprocess.run(
        [
            a.ffmpeg,
            "-v",
            "error",
            "-ss",
            str(a.start),
            "-i",
            str(a.source),
            "-t",
            str(a.duration),
            "-vf",
            "scale=1080:1920,fps=25",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(clip),
        ],
        check=True,
    )
    audio = out / "speech.wav"
    subprocess.run(
        [
            a.ffmpeg,
            "-v",
            "error",
            "-i",
            str(clip),
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ],
        check=True,
    )
    original = Transcript.model_validate_json(a.transcript.read_text(encoding="utf8"))
    start_ms, duration_ms = round(a.start * 1000), round(a.duration * 1000)
    words = [
        t.model_copy(
            update={"start_ms": t.start_ms - start_ms, "end_ms": t.end_ms - start_ms}
        )
        for t in original.tokens
        if t.start_ms >= start_ms and t.end_ms <= start_ms + duration_ms
    ]
    ids = {t.id: t for t in words}
    utterances = []
    for row in original.utterances:
        tokens = [ids[i] for i in row.token_ids if i in ids]
        if tokens:
            utterances.append(
                TranscriptUtterance(
                    id=row.id,
                    text="".join(t.text for t in tokens),
                    token_ids=[t.id for t in tokens],
                    start_ms=tokens[0].start_ms,
                    end_ms=tokens[-1].end_ms,
                )
            )
    transcript = original.model_copy(
        update={
            "source_sha256": sha256(clip),
            "audio_sha256": sha256(audio),
            "duration_ms": duration_ms,
            "tokens": words,
            "utterances": utterances,
            "warnings": [
                "queue integration fixture: measured parent word clocks shifted onto a source crop; not new ASR or model quality approval"
            ],
            "timing_adjustments": [],
            "reference_text": None,
            "reference_matches": None,
            "differences": [],
        }
    )
    transcript = Transcript.model_validate(transcript.model_dump())
    assert len(utterances) >= 2
    settings = Settings(
        _env_file=None,
        environment="test",
        auth_mode="development",
        development_user_email="1474953130@qq.com",
        database_url="sqlite:///" + (out / "site.db").as_posix(),
        auto_create_schema=True,
        auto_process_jobs=False,
        storage_backend="local",
        storage_dir=out / "storage",
        ecommerce_startup_recovery_enabled=False,
        video_editing_enabled=True,
        video_editing_native_plan_enabled=True,
        video_editing_planning_enabled=True,
        video_script_planning_enabled=True,
        video_script_api_key=SecretStr("local-protocol-fixture-never-transmitted"),
        video_editing_library_dir=a.library.resolve(),
        video_editing_tasks_dir=out / "tasks",
        video_editing_python=sys.executable,
        video_editing_ffmpeg=a.ffmpeg,
        video_editing_ffprobe=a.ffprobe,
        video_editing_lease_seconds=360,
    )
    with TestClient(create_app(settings)) as client:
        client.app.state.editing_dispatcher = lambda _: None
        client.app.state.editing_planning_dispatcher = lambda _: None
        user = client.get("/api/v1/me").raise_for_status().json()["id"]
        ws = client.get("/api/v1/workspaces").raise_for_status().json()[0]["id"]
        base = f"/api/v1/video-studio/workspaces/{ws}"
        pid = str(uuid4())
        content = VideoProjectContent().model_dump(mode="json")
        content["draft"].update(
            name="苹果极简真实队列回归（协议fixture）",
            text="".join(t.text for t in words),
        )
        client.put(
            base + f"/projects/{pid}",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "content": content,
                "action": "save",
            },
        ).raise_for_status()
        with clip.open("rb") as f:
            source = (
                client.post(
                    base + "/editing-sources",
                    data={"project_id": pid, "request_id": str(uuid4())},
                    files={"file": ("source.mp4", f, "video/mp4")},
                )
                .raise_for_status()
                .json()
            )
        tid = str(uuid4())
        path = out / "tasks" / tid / "fixture" / "transcript.json"
        atomic_json(path, transcript.model_dump(mode="json"))
        with client.app.state.session_factory() as session:
            session.add(
                EditingTaskRecord(
                    id=tid,
                    workspace_id=ws,
                    owner_user_id=user,
                    project_id=pid,
                    source_id=source["id"],
                    request_id=str(uuid4()),
                    request_hash="a" * 64,
                    library_release=MOTION_SHA256,
                    status="completed",
                    stage="transcript_ready",
                    options={
                        "mode": "transcript",
                        "source_subtitles": "none",
                        "language": "zh",
                        "caption_font_id": "font-d1961be1161ea1be",
                    },
                )
            )
            session.add(
                EditingArtifactRecord(
                    id=str(uuid4()),
                    task_id=tid,
                    role="transcript",
                    path=str(path),
                    sha256=sha256(path),
                    bytes=path.stat().st_size,
                    mime="application/json",
                    duration_ms=duration_ms,
                    validation={
                        "source_frame": {
                            "width": 1080,
                            "height": 1920,
                            "supports_native_portrait": True,
                        },
                        "source_display_transform_verified": True,
                    },
                )
            )
            session.commit()
        with a.material.open("rb") as f:
            material = (
                client.post(
                    base + f"/projects/{pid}/editing-materials",
                    data={
                        "request_id": str(uuid4()),
                        "label": "拉取对标商品",
                        "description": "点击拉取参考商品后展示图片列表的录屏",
                    },
                    files={"file": ("pull.mp4", f, "video/mp4")},
                )
                .raise_for_status()
                .json()
            )
        # A crop can retain a tiny tail of the preceding utterance. Keep those
        # measured words in the transcript, but choose complete demo phrases.
        intro = next(row for row in utterances if row.end_ms - row.start_ms >= 1500 and "上传自己的产品图" in row.text)
        body = next(
            row
            for row in utterances
            if row.start_ms >= intro.end_ms and row.end_ms - row.start_ms >= 1500 and "拉取参考商品" in row.text
        )
        assert "上传" in intro.text and "拉取" in body.text, (intro.text, body.text)
        body_words = [ids[i] for i in body.token_ids]
        anchor = next(t for t in body_words if t.start_ms >= intro.end_ms + 500)
        plan = {
            "schema_version": "tengli.apple-suite-plan/1",
            "opening": {
                "title": {
                    "first_token_id": intro.token_ids[0],
                    "last_token_id": intro.token_ids[-1],
                },
                "subtitle": {
                    "first_token_id": intro.token_ids[0],
                    "last_token_id": intro.token_ids[min(2, len(intro.token_ids) - 1)],
                },
                "intro_last_token_id": intro.token_ids[-1],
            },
            "body_variant": "materials",
            "materials": [
                {
                    "asset_id": "material-" + material["id"],
                    "first_token_id": body.token_ids[0],
                    "last_token_id": body.token_ids[-1],
                    "show_at_token_id": anchor.id,
                    "edge": "start",
                }
            ],
            "warnings": ["Explicit local protocol fixture; no external planner called"],
        }

        class Provider:
            calls = 0

            def request(self, *_args, **_kwargs):
                self.calls += 1
                return {
                    "id": "local-fixture",
                    "model": "local-fixture",
                    "choices": [
                        {"message": {"content": json.dumps(plan, ensure_ascii=False)}}
                    ],
                }

        provider = Provider()
        prepared = (
            client.post(
                base + f"/editing-tasks/{tid}/planning-tasks",
                json={
                    "request_id": str(uuid4()),
                    "template_id": "apple-minimal-v1",
                    "material_ids": [material["id"]],
                    "music": "off",
                    "creative_options": {
                        "title": "素材对应口播",
                        "subtitle": "选好素材再开始",
                        "name_card": {
                            "enabled": True,
                            "name": "示范讲师",
                            "description": "队列功能验证",
                        },
                        "cover": "auto",
                    },
                },
            )
            .raise_for_status()
            .json()
        )
        plan_process(prepared["id"], settings, client.app.state.session_factory)
        ready = (
            client.get(base + f"/editing-planning-tasks/{prepared['id']}")
            .raise_for_status()
            .json()
        )
        assert ready["status"] == "prepared", ready
        generated = (
            client.post(
                base + f"/editing-tasks/{tid}/planning-tasks",
                json={
                    "request_id": str(uuid4()),
                    "mode": "generate",
                    "prepared_task_id": prepared["id"],
                },
            )
            .raise_for_status()
            .json()
        )
        plan_process(
            generated["id"], settings, client.app.state.session_factory, provider
        )
        planned = (
            client.get(base + f"/editing-planning-tasks/{generated['id']}")
            .raise_for_status()
            .json()
        )
        assert planned["status"] == "completed", planned
        preview = (
            client.post(base + f"/editing-planning-tasks/{generated['id']}/preview")
            .raise_for_status()
            .json()
        )
        assert (
            client.post(
                base + f"/editing-planning-tasks/{generated['id']}/preview"
            ).json()["id"]
            == preview["id"]
        )
        render_process(preview["id"], settings, client.app.state.session_factory)
        rendered = (
            client.get(base + f"/editing-tasks/{preview['id']}")
            .raise_for_status()
            .json()
        )
        assert rendered["status"] == "awaiting_review", rendered
        visible = {a["role"]: a for a in rendered["artifacts"]}
        assert "preview" in visible and "poster" in visible and "final" not in visible
        confirmed = (
            client.post(
                base + f"/editing-tasks/{preview['id']}/confirm-export",
                json={
                    "preview_artifact_id": visible["preview"]["id"],
                    "preview_sha256": visible["preview"]["sha256"],
                },
            )
            .raise_for_status()
            .json()
        )
        assert confirmed["status"] == "completed" and provider.calls == 1
        final = next(a for a in confirmed["artifacts"] if a["role"] == "final")
        assert (
            client.get(final["url"], headers={"Range": "bytes=0-255"}).status_code
            == 206
        )
        with client.app.state.session_factory() as session:
            record = session.scalar(
                select(EditingArtifactRecord).where(
                    EditingArtifactRecord.id == final["id"]
                )
            )
            final_path = record.path
        summary = {
            "status": "passed",
            "scope": "real queue/renderer/preview/export; fixture planner and shifted measured transcript; not ASR or semantic quality approval",
            "opening_spoken_text": intro.text,
            "matched_spoken_text": body.text,
            "provider_calls": provider.calls,
            "external_calls": 0,
            "source_sha256": sha256(clip),
            "parent_source_sha256": sha256(a.source),
            "parent_range": [a.start, a.start + a.duration],
            "final_path": final_path,
            "final_sha256": final["sha256"],
            "workspace_id": ws,
            "project_id": pid,
            "planning_task_id": generated["id"],
            "render_task_id": preview["id"],
            "confirmed_artifacts": [a["role"] for a in confirmed["artifacts"]],
        }
        atomic_json(out / "queue-verification.json", summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
