"""Durable preparation steps before the single billable lipsync submission."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .config import Settings
from .errors import ApiError
from .video_generation_models import VideoAudioRecord, VideoGenerationRecord
from .video_generation_runtime import guard_run
from .video_providers import VideoProviders
from .video_stage_timing import transition
from .video_template_media import audio_duration, prepare_forward, video_info

MODEL_REGISTRATION_STAGES = {"model_submitting", "forward_model_submitting"}
MODEL_REGISTRATION_TIMEOUT = 180
MODEL_LOOKUP_WINDOW = 90


def register_model(
    session: Session,
    job: VideoGenerationRecord,
    provider: VideoProviders,
    *,
    stage: str,
    name: str,
    video_url: str,
) -> dict[str, Any]:
    """Submit once, then reconcile lost replies by this job's unique name.

    The provider copies uploaded videos to a different URL during registration,
    so URL equality is not an identity check. Only one active private video with
    the exact job UUID name in the authenticated account can be adopted.
    """
    receipt = dict(job.details.get("model_registration") or {})
    if receipt and receipt.get("name") != name:
        raise ApiError(409, "VIDEO_MODEL_REGISTRATION_CONFLICT", "形象登记记录不匹配。")
    if receipt.get("model_id"):
        return {"model": {"id": receipt["model_id"]}, "billing": receipt.get("billing")}
    attempted = receipt.get("submission_started") or any(
        item.get("stage") == stage for item in job.details.get("stage_history", [])
    )
    receipt.update(name=name, submission_started=True)
    if not attempted:
        # Commit the intent before the POST, including before a process crash.
        set_stage(session, job, stage, model_registration=receipt)
        try:
            data = provider.request(
                "quanyu",
                "POST",
                "/api/digital_human/models",
                json={
                    "model_name": name,
                    "model_type": "video",
                    "video_url": video_url,
                },
                timeout=httpx.Timeout(MODEL_REGISTRATION_TIMEOUT, connect=15),
            )
            model_id = (data.get("model") or {}).get("id")
            if (
                isinstance(model_id, int)
                and not isinstance(model_id, bool)
                and model_id > 0
            ):
                receipt.update(
                    model_id=model_id, reconciled=False, billing=data.get("billing")
                )
                set_stage(session, job, stage, model_registration=receipt)
                return data
        except ApiError as error:
            if error.code != "VIDEO_PROVIDER_OUTCOME_UNKNOWN":
                raise

    # Existing/legacy submissions also enter here. No recovery path repeats POST.
    deadline = time.monotonic() + MODEL_LOOKUP_WINDOW
    while True:
        set_stage(session, job, stage, model_registration=receipt)
        try:
            data = provider.request(
                "quanyu",
                "GET",
                "/api/digital_human/models",
                timeout=min(15, max(1, deadline - time.monotonic())),
            )
            matches = [
                model
                for model in data.get("models", [])
                if model.get("model_name") == name
                and model.get("model_type") == "video"
                and model.get("is_active") is True
                and model.get("is_public") is False
                and isinstance(model.get("id"), int)
                and not isinstance(model.get("id"), bool)
                and model["id"] > 0
                and model.get("video_url")
            ]
            if len(matches) == 1:
                receipt.update(model_id=matches[0]["id"], reconciled=True)
                set_stage(session, job, stage, model_registration=receipt)
                return {"model": {"id": matches[0]["id"]}}
            if len(matches) > 1:
                break  # Never guess between ambiguous registrations.
        except ApiError:
            pass  # A failed GET does not justify another registration.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(5, remaining))
    raise ApiError(
        502,
        "VIDEO_MODEL_REGISTRATION_PENDING",
        "形象登记结果仍待确认，可继续查询原任务，无需重新登记。",
    )


def set_stage(
    session: Session, job: VideoGenerationRecord, stage: str, **details: Any
) -> None:
    guard_run(session)
    history = transition(job.details.get("stage_history"), stage)
    if stage in {"completed", "awaiting_review"}:
        history = transition(history, stage, finish=True, outcome=stage)
    job.stage = stage
    job.details = {**job.details, **details, "stage_history": history}
    session.commit()  # Release the DB connection before provider/media I/O.


def prepare_lipsync_media(
    session: Session,
    job: VideoGenerationRecord,
    settings: Settings,
    provider: VideoProviders,
) -> None:
    root = settings.video_media_dir / "jobs" / job.id
    if not job.details.get("audio_duration_seconds"):
        if job.details.get("audio_id"):
            audio = session.get(VideoAudioRecord, job.details["audio_id"])
            if (
                not audio
                or audio.owner_user_id != job.owner_user_id
                or audio.workspace_id != job.workspace_id
            ):
                raise ApiError(404, "VIDEO_AUDIO_NOT_FOUND", "未找到任务音频。")
            path, mime = Path(audio.path), audio.mime
            session.commit()
        elif job.details.get("tts_local_path"):
            path, mime = Path(job.details["tts_local_path"]), "audio/mpeg"
        else:
            path, mime = root / "narration.mp3", "audio/mpeg"
            if not path.exists():
                set_stage(session, job, "downloading_audio")
                provider.download(
                    job.details["audio_url"], path, limit=50 * 1024 * 1024
                )
        set_stage(session, job, "measuring_audio")
        seconds = audio_duration(path)
        set_stage(
            session,
            job,
            "audio_measured",
            audio_duration_seconds=seconds,
            audio_local_path=str(path),
            audio_mime=mime,
        )

    if job.details.get("template_duration_ready"):
        return
    seconds = job.details["audio_duration_seconds"]
    source = job.details.get("source_video")
    if not source:
        # Recover old queued records by their exact, server-selected model ID;
        # never silently substitute the avatar's current (possibly newer) model.
        set_stage(session, job, "resolving_source")
        model = next(
            (
                m
                for m in provider.models()
                if str(m["id"]) == str(job.details["model_id"])
            ),
            None,
        )
        if not model or not model.get("video_url"):
            raise ApiError(
                409, "VIDEO_TEMPLATE_SNAPSHOT_MISSING", "原动作模板无法恢复。"
            )
        source = {"video_url": model["video_url"]}
        set_stage(session, job, "source_resolved", source_video=source)
    if source.get("local_path"):
        path = Path(source["local_path"])
    else:
        path = root / "source.mp4"
        if not path.exists():
            set_stage(session, job, "downloading_source")
            provider.download(source["video_url"], path)
    set_stage(session, job, "measuring_source")
    info = video_info(path)
    set_stage(session, job, "source_measured", source_duration_seconds=info["duration"])
    if info["duration"] + 0.001 >= seconds:
        set_stage(
            session,
            job,
            "template_duration_ready",
            template_duration_ready=True,
            template_preparation={
                "recipe": "original-long-enough",
                "audio_seconds": seconds,
                "source_seconds": info["duration"],
                "reversed_frames": False,
            },
        )
        return

    target = root / "forward-template.mp4"
    if not job.details.get("forward_preparation"):
        set_stage(session, job, "preparing_forward_template")
        result = prepare_forward(path, target, seconds)
        set_stage(session, job, "forward_template_prepared", forward_preparation=result)
    if not job.details.get("forward_template_url"):
        set_stage(session, job, "uploading_forward_template")
        url = provider.upload(target, "video/mp4", "digital_human_model")
        set_stage(session, job, "forward_template_uploaded", forward_template_url=url)
    if not job.details.get("forward_model_id"):
        data = register_model(
            session,
            job,
            provider,
            stage="forward_model_submitting",
            name="极光正向动作-" + job.id,
            video_url=job.details["forward_template_url"],
        )
        model_id = (data.get("model") or {}).get("id")
        if not model_id:
            raise ApiError(
                502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "完整动作登记结果未能确认。"
            )
        billing = job.details.get("billing", [])
        if data.get("billing"):
            billing = [*billing, data["billing"]]
        set_stage(
            session,
            job,
            "forward_model_ready",
            forward_model_id=model_id,
            billing=billing,
        )
    set_stage(
        session,
        job,
        "template_duration_ready",
        template_duration_ready=True,
        source_model_id=job.details["model_id"],
        model_id=job.details["forward_model_id"],
        template_preparation=job.details["forward_preparation"],
    )
