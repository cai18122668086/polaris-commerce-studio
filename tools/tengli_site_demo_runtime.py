"""Local, explicitly authorized seven-call demo batch. Never deploys.

Credentials are read in memory from --provider-env; never exported or printed.
Paid POST reservations are durable and unique before any network transmission.
Re-running cannot repeat a paid submission, even after an uncertain outcome.
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx
import uvicorn
from app.config import Settings
from app.main import create_app
from app.motion_library import atomic_json, read_json, sha256
from app.video_assistance_provider import VideoAssistanceProvider
from app.video_editing_planning_worker import process as plan_worker
from app.video_editing_worker import process as edit_worker
from app.video_providers import VideoProviders
from app.video_template_media import audio_duration
from app.video_tts import synthesize
from app.video_voice_catalog import select_tao_voice

BATCH_TEMPLATES = {
    "presenter-openings-v1",
    "rotation-cards-v1",
    "azl-panels-v1",
    "unified-chapter-v1",
    "unified-paper-typewriter-v1",
}


class BatchTransport(httpx.BaseTransport):
    def __init__(self, root: Path):
        self.root = root
        self.http = httpx.HTTPTransport(retries=0)
        with sqlite3.connect(root / "paid-reservations.db") as db:
            db.execute(
                "create table if not exists paid_calls "
                "(slot text primary key, request_sha256 text not null, "
                "reserved_at text not null)"
            )

    def handle_request(self, request):
        slot = None
        if request.method == "POST":
            host, path = request.url.host, request.url.path
            if host == "newapi.qwqtao.one" and path == "/v1/audio/speech":
                slot = "tts"
            elif host == "quanyu.sowa.chat" and path == "/api/digital_human/submit":
                slot = "digital_human"
                if json.loads(request.content)["model_id"] != 966:
                    raise ValueError(
                        "Only the already registered, same-presenter motion "
                        "model is authorized"
                    )
            elif host == "api.tengliapi.xyz" and path == "/v1/chat/completions":
                data = json.loads(request.content)
                payload = json.loads(data["messages"][1]["content"])
                tid = payload["overlay_template"]["id"]
                if tid not in BATCH_TEMPLATES:
                    raise ValueError(
                        "Template is outside the authorized five-call batch"
                    )
                slot = "planning:" + tid
            elif host == "quanyu.sowa.chat" and path == "/api/oss/upload_policy":
                pass  # Audio upload preparation, not a generation call.
            elif host.endswith("aliyuncs.com"):
                pass  # Upload to the service's signed audio object destination.
            else:
                raise ValueError("Unapproved POST blocked by the local batch cap")
        if slot:
            with sqlite3.connect(self.root / "paid-reservations.db") as db:
                try:
                    db.execute(
                        "insert into paid_calls values (?,?,?)",
                        (
                            slot,
                            hashlib.sha256(request.content).hexdigest(),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                except sqlite3.IntegrityError:
                    raise ValueError(
                        "Paid slot already submitted; reconcile the original "
                        "result, never resubmit"
                    ) from None
            print("Reserved authorized paid slot: " + slot, flush=True)
        return self.http.handle_request(request)

    def close(self):
        # Clients share this transport across polling and worker calls. Each
        # temporary HTTP client must not tear down the shared connection pool.
        pass


def settings_for(root: Path, provider_env: Path) -> Settings:
    return Settings(
        _env_file=provider_env,
        environment="test",
        auth_mode="development",
        development_user_email="1474953130@qq.com",
        auto_create_schema=False,
        auto_process_jobs=False,
        ecommerce_startup_recovery_enabled=False,
        video_background_recovery_enabled=False,
        storage_backend="local",
        storage_dir=root / "storage",
        database_url="sqlite:///" + (root / "site.db").as_posix(),
        video_providers_enabled=True,
        video_tao_tts_enabled=True,
        video_hashsight_tts_enabled=False,
        video_cosyvoice_enabled=False,
        video_lipsync_failover_enabled=False,
        video_skyhuman_auto_register=False,
        video_editing_enabled=True,
        video_editing_native_plan_enabled=True,
        video_script_planning_enabled=True,
        video_editing_planning_enabled=True,
        video_editing_plan_model="gpt-6.1-sol",
        video_editing_library_dir=Path(
            "C:/tl/clean-motion-install-20261110/c10429057a86/motion"
        ),
        video_editing_library_evidence_dir=Path(
            "C:/tl/acceptance/first/tasks/_library-validation"
        ),
        video_editing_native_bindings_file=Path(
            "C:/tl/dependency-binding/original-bindings.json"
        ),
        video_editing_tasks_dir=root / "tasks",
        video_media_dir=root / "video",
        video_editing_lease_seconds=480,
        video_editing_python=sys.executable,
        video_editing_ffmpeg="C:/tl/tools/bin/ffmpeg.exe",
        video_editing_ffprobe="C:/tl/tools/bin/ffprobe.exe",
        video_editing_asr_provider="funasr",
        video_editing_asr_model="C:/tl/asr/funasr",
        video_editing_alignment_enabled=True,
        video_editing_alignment_model_dir=Path("C:/tl/asr/alignment"),
        video_editing_template_examples_dir=root.parent / "product-examples",
    )


def submit_source(root, settings, transport):
    source = root / "source"
    source.mkdir(exist_ok=True)
    provider = VideoProviders(settings, transport)
    # The original confirmed Huipin job used avatar 230 and registered this exact
    # forward-only motion model. Reuse it; do not pay to save another avatar.
    original = Path("C:/tl/tengli-template-flow-20261111/business/site.db")
    with sqlite3.connect(original.as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute(
            "select avatar_id,details from video_generations "
            "where id=? and status='completed'",
            ("07731012-b626-4454-9b94-baa92436ad20",),
        ).fetchone()
    prior = json.loads(row[1])
    assert (
        row[0] == "qy-model-230"
        and prior["model_id"] == prior["forward_model_id"] == 966
    )
    model = next(m for m in provider.models() if m["id"] == 966)
    assert (
        model.get("is_active")
        and model["model_name"] == prior["model_registration"]["name"]
    )
    script_path = (
        Path(__file__).resolve().parents[1] / "docs/tengli-site-demo-scripts.json"
    )
    text = read_json(script_path)["scripts"]["four-goals"]["text"]
    draft = {
        "voiceId": "mm-voice-8c91dd8e0c5d9f440fb7",
        "speed": 1.2,
        "emotion": "自然",
        "language": "auto",
    }
    audio = source / "narration.mp3"
    if not audio.exists():
        receipt = synthesize(
            settings, select_tao_voice(settings, draft), text, audio, transport
        )
        atomic_json(source / "tts-receipt.json", receipt)
    seconds = audio_duration(audio)
    if seconds > prior["template_preparation"]["target_seconds"]:
        raise ValueError(
            "New narration exceeds the existing registered motion; "
            "no extra paid avatar registration is authorized"
        )
    atomic_json(
        source / "source-input.json",
        {
            "script": text,
            "script_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "avatar_id": "qy-model-230",
            "existing_registered_motion_model": 966,
            "motion_origin_job": "07731012-b626-4454-9b94-baa92436ad20",
            "voice_id": draft["voiceId"],
            "speed": draft["speed"],
            "audio_duration_seconds": seconds,
            "audio_sha256": sha256(audio),
            "motion_seconds": prior["template_preparation"]["target_seconds"],
        },
    )
    task_path = source / "digital-human-task.json"
    if not task_path.exists():
        audio_url = provider.upload(audio, "audio/mpeg", "digital_human_audio")
        task = provider.request(
            "quanyu",
            "POST",
            "/api/digital_human/submit",
            json={"model_id": 966, "audio_url": audio_url},
        )
        if not task.get("task_id"):
            raise ValueError("Digital human submission uncertain; do not submit again")
        atomic_json(
            task_path,
            {
                "task_id": task["task_id"],
                "billing": task.get("billing"),
                "status": "submitted",
            },
        )
    print(
        json.dumps(
            {
                "source_stage": "submitted",
                "audio_seconds": seconds,
                "registered_motion_reused": 966,
                "extra_avatar_registration_calls": 0,
            }
        ),
        flush=True,
    )


def poll_source(root, settings, transport):
    source = root / "source"
    task = read_json(source / "digital-human-task.json")
    provider = VideoProviders(settings, transport)
    data = provider.request("quanyu", "GET", "/api/status/" + task["task_id"])
    status = str(data.get("status", "")).lower()
    atomic_json(
        source / "digital-human-status.json",
        {"status": status, "progress": data.get("progress")},
    )
    if status in {"completed", "success", "succeeded"}:
        output = source / "tengli-four-goals-original.mp4"
        if not output.exists():
            direct = (data.get("result") or {}).get("output_video_url") or data.get(
                "video_url"
            )
            if direct:
                provider.download(direct, output)
            else:
                provider.download(
                    "https://quanyu.sowa.chat/api/download/" + task["task_id"],
                    output,
                    vendor="quanyu",
                )
        atomic_json(
            source / "source-download.json",
            {
                "file": str(output),
                "sha256": sha256(output),
                "task_id": task["task_id"],
                "source_scope": "new_real_dynamic_narration_about_tengli_site",
            },
        )
    print(
        json.dumps({"source_stage": status, "progress": data.get("progress")}),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "submit-source",
            "poll-source",
            "revalidate-saved",
            "render-ready",
            "serve",
        ],
    )
    parser.add_argument("--planning-task", action="append", default=[])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--provider-env", type=Path, required=True)
    parser.add_argument("--authorized-seven-calls", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=8018)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    transport = BatchTransport(args.root)
    settings = settings_for(args.root, args.provider_env)
    if args.action == "submit-source":
        submit_source(args.root, settings, transport)
    elif args.action == "poll-source":
        poll_source(args.root, settings, transport)
    elif args.action == "revalidate-saved":
        from app.database import build_database
        from app.video_editing_task_models import EditingPlanningTaskRecord

        flow = read_json(args.root / "flow.json")
        engine, factory = build_database(settings.database_url)
        for planning_id in args.planning_task:
            with factory() as session:
                row = session.get(EditingPlanningTaskRecord, planning_id)
                assert (
                    row and row.project_id == flow["project"] and row.mode == "generate"
                )
                assert (
                    args.root
                    / "tasks/_planning"
                    / planning_id
                    / "provider/semantic-response.json"
                ).is_file()
            plan_worker(
                planning_id,
                settings,
                factory,
                VideoAssistanceProvider(settings, transport),
            )
        engine.dispose()
    elif args.action == "render-ready":
        from app.database import build_database
        from app.video_editing_task_models import (
            EditingPlanningTaskRecord,
            EditingTaskRecord,
        )

        flow = read_json(args.root / "flow.json")
        engine, factory = build_database(settings.database_url)
        for planning_id in flow["plans"].values():
            with factory() as session:
                planning_task = session.get(EditingPlanningTaskRecord, planning_id)
                assert planning_task and planning_task.project_id == flow["project"]
                preview_id = planning_task.result.get("preview_task_id")
                preview = (
                    session.get(EditingTaskRecord, preview_id) if preview_id else None
                )
                ready = (
                    preview
                    and preview.status == "queued"
                    and not preview.cancel_requested
                )
            if ready:
                print("Rendering existing queued preview: " + preview_id, flush=True)
                edit_worker(preview_id, settings, factory)
        engine.dispose()
    else:
        db = args.root / "site.db"
        if not db.exists():
            with (
                sqlite3.connect(
                    "file:C:/tl/tengli-template-flow-20261111/business/site.db?mode=ro",
                    uri=True,
                ) as old,
                sqlite3.connect(db) as new,
            ):
                old.backup(new)
        # This server can plan only the approved five films. Generation endpoints
        # stay disabled; the two source paid slots live in the explicit commands.
        settings.video_providers_enabled = False
        app = create_app(settings)
        provider = VideoAssistanceProvider(settings, transport)
        with (
            ThreadPoolExecutor(max_workers=1) as planning,
            ThreadPoolExecutor(max_workers=1) as rendering,
        ):
            app.state.editing_planning_dispatcher = lambda task: planning.submit(
                plan_worker, task, settings, app.state.session_factory, provider
            )
            app.state.editing_dispatcher = lambda task: rendering.submit(
                edit_worker, task, settings, app.state.session_factory
            )
            uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
