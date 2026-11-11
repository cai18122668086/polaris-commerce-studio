"""Serve an isolated saved-response run for local UI QA, with paid APIs disabled.

This local harness uses standalone worker processes, not the production Celery queue.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import uvicorn  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", type=Path, required=True)
parser.add_argument("--examples", type=Path, required=True)
parser.add_argument("--port", type=int, default=8017)
args = parser.parse_args()
root = args.run.resolve()
settings = Settings(
    _env_file=None,
    environment="test",
    auth_mode="development",
    development_user_email="1474953130@qq.com",
    auto_create_schema=False,
    auto_process_jobs=False,
    ecommerce_startup_recovery_enabled=False,
    storage_backend="local",
    storage_dir=root / "storage",
    database_url="sqlite:///" + (root / "site.db").as_posix(),
    video_editing_enabled=True,
    video_editing_native_plan_enabled=True,
    video_editing_planning_enabled=False,
    video_script_planning_enabled=False,
    video_editing_library_dir=Path(
        "C:/tl/clean-motion-install-20261110/c10429057a86/motion"
    ),
    video_editing_tasks_dir=root / "tasks",
    video_editing_lease_seconds=360,
    video_editing_library_evidence_dir=Path(
        "C:/tl/acceptance/first/tasks/_library-validation"
    ),
    video_editing_native_bindings_file=Path(
        "C:/tl/dependency-binding/original-bindings.json"
    ),
    video_editing_template_examples_dir=args.examples.resolve(),
    video_editing_python=sys.executable,
    video_editing_ffmpeg="C:/tl/tools/bin/ffmpeg.exe",
    video_editing_ffprobe="C:/tl/tools/bin/ffprobe.exe",
    video_editing_asr_provider="funasr",
    video_editing_asr_model="C:/tl/asr/funasr",
    video_editing_alignment_enabled=True,
    video_editing_alignment_model_dir=Path("C:/tl/asr/alignment"),
    video_media_dir=Path(
        "D:/Desktop/cyh/tengli/polaris-commerce-studio/backend/.data/video-studio"
    ),
)
app = create_app(settings)
workers = []


def dispatch(task_id: str, script: str) -> None:
    # Export only non-secret settings required by the opt-in local workers.
    keys = (
        "environment",
        "auth_mode",
        "development_user_email",
        "auto_create_schema",
        "auto_process_jobs",
        "ecommerce_startup_recovery_enabled",
        "storage_backend",
        "storage_dir",
        "database_url",
        "video_editing_enabled",
        "video_editing_native_plan_enabled",
        "video_editing_planning_enabled",
        "video_script_planning_enabled",
        "video_editing_library_dir",
        "video_editing_tasks_dir",
        "video_editing_library_evidence_dir",
        "video_editing_native_bindings_file",
        "video_editing_python",
        "video_editing_ffmpeg",
        "video_editing_ffprobe",
        "video_editing_lease_seconds",
        "video_editing_asr_provider",
        "video_editing_asr_model",
        "video_editing_alignment_enabled",
        "video_editing_alignment_model_dir",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("POLARIS_")
    }
    env.update({"POLARIS_" + key.upper(): str(getattr(settings, key)) for key in keys})
    env["PYTHONUTF8"] = "1"
    with (root / ("local-worker-" + task_id + ".log")).open("ab") as log:
        command = (
            [sys.executable, "-B", "backend/scripts/" + script, "--once", task_id]
            if script != "planning"
            else [
                sys.executable,
                "-B",
                "-c",
                "from app.config import Settings; from app.database import build_database; from app.video_editing_planning_worker import process; import sys; s=Settings(_env_file=None); e,f=build_database(s.database_url); process(sys.argv[1],s,f); e.dispose()",
                task_id,
            ]
        )
        workers.append(
            subprocess.Popen(
                command,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        )


app.state.editing_dispatcher = lambda task: dispatch(task, "run_editing_worker.py")
app.state.editing_planning_dispatcher = lambda task: dispatch(task, "planning")
uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
