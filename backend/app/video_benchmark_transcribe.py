"""小红书 benchmark transcription on the editing worker (it has the ASR memory).

The API marks an extraction ``stage="asr_queued"`` and publishes
``polaris.transcribe_benchmark``. The worker claims the row by moving it to
``asr_running`` (duplicate deliveries do nothing), finds the video file, runs
``app.video_benchmark_asr`` in a subprocess with heartbeats, and stores the
transcript. A lost message or a dead worker turns the row into
``awaiting_resume``; 继续 re-dispatches it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from . import video_benchmark_platforms as platforms
from .celery_app import celery_app
from .config import Settings
from .database import build_database_for
from .errors import ApiError
from .models import utc_now
from .video_assistance_models import VideoAssistanceRecord
from .video_stage_timing import transition

TASK_NAME = "polaris.transcribe_benchmark"
QUEUED, RUNNING = "asr_queued", "asr_running"
ASR_TIMEOUT_SECONDS = 900


def dispatch(task_id: str) -> bool:
    """Publish one transcription; False when the broker is unreachable."""
    try:
        with celery_app.connection_for_write(
            connect_timeout=3,
            transport_options={
                "socket_connect_timeout": 3,
                "socket_timeout": 3,
                "retry_on_timeout": False,
                "max_retries": 0,
            },
        ) as connection:
            celery_app.send_task(
                TASK_NAME,
                args=[task_id],
                queue="editing",
                retry=False,
                ignore_result=True,
                connection=connection,
            )
    except Exception:  # noqa: BLE001 - no broker URL in logs; the row stays resumable
        return False
    return True


def _finish(
    factory: sessionmaker[Session],
    task_id: str,
    *,
    result: dict[str, Any] | None = None,
    error: ApiError | None = None,
) -> None:
    with factory() as session:
        row = session.get(VideoAssistanceRecord, task_id)
        if row is None or row.stage != RUNNING:
            return
        status = "completed" if result is not None else "failed"
        history = transition(row.receipt.get("stage_history"), "received")
        history = transition(history, status, finish=True, outcome=status)
        row.status, row.stage = status, ("completed" if result is not None else RUNNING)
        if result is not None:
            row.result = result
        row.error_code = error.code if error else None
        row.receipt = {
            **row.receipt,
            "stage_history": history,
            "billing": {"local_asr": True},
        }
        session.commit()


def _heartbeat(factory: sessionmaker[Session], task_id: str) -> None:
    with factory() as session:
        session.execute(
            update(VideoAssistanceRecord)
            .where(
                VideoAssistanceRecord.id == task_id,
                VideoAssistanceRecord.stage == RUNNING,
            )
            .values(updated_at=utc_now())
        )
        session.commit()


def media_for(settings: Settings, inputs: dict[str, Any]) -> str:
    media = inputs.get("media_url")
    if media:
        return str(media)
    # Search pages do not always carry the file; the detail call does (paid once).
    from .video_assistance_provider import VideoAssistanceProvider

    data = VideoAssistanceProvider(settings).request(
        "extract",
        "POST",
        "/api/v1/social",
        json={
            "platform": "xiaohongshu",
            "action": "video",
            "params": {"url": inputs["source_url"]},
        },
    )
    found = data.get("results")
    row = found[0] if isinstance(found, list) and found else found
    media = platforms.https_url(row.get("video_url")) if isinstance(row, dict) else None
    if not media or not (media.split("/")[2].lower()).endswith(
        platforms.MEDIA_HOST_SUFFIXES
    ):
        raise ApiError(
            422,
            "VIDEO_TRANSCRIPT_EMPTY",
            "这条笔记读取不到视频，可能是图文笔记；可以手动粘贴口播原文。",
        )
    return media


NO_SPEECH = ApiError(
    422,
    "VIDEO_TRANSCRIPT_EMPTY",
    "这条视频没有口播（多是背景音乐配画面字幕），换一条有人说话的对标。",
)


def spoken(payload: dict[str, Any]) -> bool:
    """Real talk, not song lyrics or a stray word: enough Chinese for the length."""
    text = str(payload.get("text") or "")
    chinese = sum("\u4e00" <= ch <= "\u9fff" for ch in text)
    seconds = payload.get("duration_seconds")
    seconds = float(seconds) if isinstance(seconds, (int, float)) else 0.0
    return chinese >= max(15, seconds * 0.8)


def note_text(settings: Settings, inputs: dict[str, Any]) -> str:
    """The note's full text, for videos with music and on-screen captions only."""
    from .video_assistance_provider import VideoAssistanceProvider

    data = VideoAssistanceProvider(settings).request(
        "extract",
        "POST",
        "/api/v1/social",
        json={
            "platform": "xiaohongshu",
            "action": "note",
            "params": {"url": inputs["source_url"]},
        },
    )
    found = data.get("results")
    row = found[0] if isinstance(found, list) and found else found
    text = str(row.get("text") or "") if isinstance(row, dict) else ""
    # Topic tags carry no script: 「#早餐[话题]#」.
    return re.sub(r"#[^#\s]{1,30}(?:\[话题\])?#?", " ", text).strip()


def transcribe(
    task_id: str, settings: Settings, factory: sessionmaker[Session]
) -> None:
    from .video_assistance_provider import transcript_result

    with factory() as session:
        claimed = session.execute(
            update(VideoAssistanceRecord)
            .where(
                VideoAssistanceRecord.id == task_id,
                VideoAssistanceRecord.kind == "extract",
                VideoAssistanceRecord.status == "running",
                VideoAssistanceRecord.stage == QUEUED,
            )
            .values(stage=RUNNING, updated_at=utc_now())
        )
        session.commit()
        if cast(CursorResult[Any], claimed).rowcount != 1:
            return
        row = session.get(VideoAssistanceRecord, task_id)
        assert row is not None
        inputs = dict(row.inputs)
    try:
        media = media_for(settings, inputs)
        with tempfile.TemporaryDirectory(prefix="benchmark-asr-") as work:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "app.video_benchmark_asr",
                    media,
                    str(Path(work) / "asr"),
                ],
                cwd=str(Path(__file__).resolve().parent.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            started = time.monotonic()
            while process.poll() is None:
                if time.monotonic() - started > ASR_TIMEOUT_SECONDS:
                    process.kill()
                    raise ApiError(
                        502,
                        "VIDEO_LOCAL_ASR_FAILED",
                        "语音识别超时，请稍后重试或手动粘贴原文。",
                    )
                _heartbeat(factory, task_id)
                time.sleep(5)
            lines = (
                (process.stdout.read() if process.stdout else "").strip().splitlines()
            )
        try:
            payload = json.loads(lines[-1]) if lines else {}
        except ValueError:
            payload = {}
        if not isinstance(payload, dict) or payload.get("error"):
            raise ApiError(
                502,
                "VIDEO_LOCAL_ASR_FAILED",
                "视频语音识别失败，请稍后重试或手动粘贴原文。",
            )
        source = "speech"
        if not spoken(payload):
            text = note_text(settings, inputs)
            if len(re.sub(r"\s", "", text)) < 80:
                raise NO_SPEECH
            payload, source = {"text": text, "segments": []}, "note_text"
        result = transcript_result(
            {"results": {**payload, "title": inputs.get("title", "")}},
            inputs["source_url"],
        )
        result["source"] = source
    except ApiError as error:
        _finish(factory, task_id, error=error)
        return
    except Exception:  # noqa: BLE001 - the row must not stay running
        _finish(
            factory,
            task_id,
            error=ApiError(502, "VIDEO_LOCAL_ASR_FAILED", "视频语音识别失败。"),
        )
        return
    _finish(factory, task_id, result=result)


@celery_app.task(name=TASK_NAME, acks_late=True, reject_on_worker_lost=True)
def transcribe_benchmark(task_id: str) -> None:
    settings = Settings()
    engine, factory = build_database_for(settings)
    try:
        transcribe(task_id, settings, factory)
    finally:
        engine.dispose()
