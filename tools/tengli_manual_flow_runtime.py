"""Local manual photo-to-editing environment; startup never submits generation.

Uses the existing isolated database and native runtime. Unlike the historical
seven-call sample harness, this accepts new user submissions through the UI.
Background recovery remains off: opening or restarting it cannot resume paid
work. Credentials stay in server memory; the audit contains hashes only.
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx
import uvicorn
from app.main import create_app
from app.video_assistance_provider import VideoAssistanceProvider
from app.video_editing_planning_worker import process as plan_worker
from app.video_editing_task_models import EditingPlanningTaskRecord, EditingTaskRecord
from app.video_editing_worker import process as edit_worker
from app.video_providers import VideoProviders
from tengli_site_demo_runtime import settings_for


class ManualFlowTransport(httpx.BaseTransport):
    """Allow only this flow's providers; persist each paid attempt before send.

    This records attempts rather than imposing a demo batch allowance. Existing
    task idempotency and uncertain-outcome guards remain responsible for resume.
    There is no network retry on a paid POST.
    """

    STAGES: ClassVar[dict[tuple[str, str], str]] = {
        ("www.wuyeai.cn", "/v1/videos"): "photo_motion",
        ("quanyu.sowa.chat", "/api/digital_human/models"): "avatar_registration",
        ("newapi.qwqtao.one", "/v1/audio/speech"): "narration",
        ("quanyu.sowa.chat", "/api/digital_human/submit"): "digital_human",
        ("api.tengliapi.xyz", "/v1/chat/completions"): "editing_plan",
    }

    def __init__(self, root: Path, *, user_submissions: bool = False):
        self.user_submissions = user_submissions
        self.http = httpx.HTTPTransport(retries=0)
        self.ledger = root / "manual-paid-attempts.db"
        with sqlite3.connect(self.ledger) as db:
            db.execute(
                "create table if not exists paid_attempts "
                "(stage text not null, request_sha256 text not null, "
                "submitted_at text not null)"
            )

    def handle_request(self, request):
        if request.method not in {"GET", "HEAD", "POST"}:
            raise ValueError("Operation is outside the manual video flow")
        if request.method == "POST":
            host, path = request.url.host, request.url.path
            stage = self.STAGES.get((host, path))
            if stage:
                if not self.user_submissions:
                    raise ValueError("User generation submissions are disabled")
                if stage == "editing_plan":
                    payload = json.loads(request.content)
                    inputs = json.loads(payload["messages"][1]["content"])
                    suite = inputs.get("template", {})
                    apple_suite = (
                        suite.get("id") == "apple-minimal-v1"
                        and suite.get("engine") == "apple-minimal-suite"
                        and inputs.get("output_schema", {})
                        .get("properties", {})
                        .get("schema_version", {})
                        .get("const")
                        == "tengli.apple-suite-plan/2"
                    )
                    if (
                        not inputs.get("overlay_template", {}).get("id")
                        and not apple_suite
                    ):
                        raise ValueError("Only template editing planning is enabled")
                with sqlite3.connect(self.ledger) as db:
                    db.execute(
                        "insert into paid_attempts values (?,?,?)",
                        (
                            stage,
                            hashlib.sha256(request.content).hexdigest(),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
            elif not (
                host == "quanyu.sowa.chat"
                and path == "/api/oss/upload_policy"
                or host
                in {
                    "sowa.oss-cn-beijing.aliyuncs.com",
                    "openpt1.oss-cn-shanghai.aliyuncs.com",
                }
            ):
                raise ValueError("Service is outside the manual video flow")
        return self.http.handle_request(request)

    def close(self):
        # Short-lived clients share this transport with generation workers.
        pass


def dispatch_saved_preview(task_id, factory, dispatch):
    """Deliver this plan's outbox item without production maintenance."""
    with factory() as session:
        plan = session.get(EditingPlanningTaskRecord, task_id)
        if plan is None or plan.status != "completed" or plan.mode != "generate":
            return
        preview_id = plan.result.get("preview_task_id")
        preview = session.get(EditingTaskRecord, preview_id) if preview_id else None
        if (
            preview is None
            or preview.status != "queued"
            or (preview.project_id, preview.source_id)
            != (plan.project_id, plan.source_id)
        ):
            return
    dispatch(preview_id)


def process_plan_and_preview(task_id, settings, factory, provider, dispatch):
    plan_worker(task_id, settings, factory, provider)
    dispatch_saved_preview(task_id, factory, dispatch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--provider-env", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8018)
    parser.add_argument("--examples", type=Path)
    parser.add_argument("--resume-preview", action="append", default=[])
    parser.add_argument("--enable-user-submissions", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "site.db").is_file():
        parser.error("--root must contain the existing isolated site.db")
    settings = settings_for(root, args.provider_env)
    if args.examples is not None:
        settings.video_editing_template_examples_dir = args.examples.resolve()
    checks = {
        "database": True,
        "native_library": settings.video_editing_library_dir.is_dir(),
        "native_bindings": settings.video_editing_native_bindings_file.is_file(),
        "ffmpeg": Path(settings.video_editing_ffmpeg).is_file(),
        "ffprobe": Path(settings.video_editing_ffprobe).is_file(),
        "offline_asr": Path(settings.video_editing_asr_model).is_dir(),
        "alignment": settings.video_editing_alignment_model_dir.is_dir(),
        "photo_provider_configured": bool(settings.wuye_api_key.get_secret_value()),
        "avatar_provider_configured": bool(settings.quanyu_api_key.get_secret_value()),
        "tts_provider_configured": bool(settings.tao_api_key.get_secret_value()),
        "planner_configured": bool(settings.video_script_api_key.get_secret_value()),
    }
    print(json.dumps({"local_preflight": checks}), flush=True)
    if not all(checks.values()):
        parser.error("Manual flow dependencies are incomplete")
    if args.check:
        return  # No provider requests, application startup or task processing.
    settings.video_providers_enabled = args.enable_user_submissions
    settings.video_editing_planning_enabled = args.enable_user_submissions
    settings.video_script_planning_enabled = args.enable_user_submissions
    app = create_app(settings)
    transport = ManualFlowTransport(root, user_submissions=args.enable_user_submissions)
    app.state.video_providers = VideoProviders(settings, transport)
    provider = VideoAssistanceProvider(settings, transport)
    with (
        ThreadPoolExecutor(max_workers=1) as planning,
        ThreadPoolExecutor(max_workers=1) as rendering,
    ):
        app.state.editing_dispatcher = lambda task: rendering.submit(
            edit_worker, task, settings, app.state.session_factory
        )
        app.state.editing_planning_dispatcher = lambda task: planning.submit(
            process_plan_and_preview,
            task,
            settings,
            app.state.session_factory,
            provider,
            app.state.editing_dispatcher,
        )
        for task in args.resume_preview:
            dispatch_saved_preview(
                task, app.state.session_factory, app.state.editing_dispatcher
            )
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
