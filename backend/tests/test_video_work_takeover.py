"""B7: tasks outside batches (avatar motions, single talking videos) are taken
over after a restart like batch tasks: query only, never re-submit."""

from sqlalchemy import update

from app import video_work_talking as talking
from app.video_generation_models import VideoGenerationRecord
from app.video_work_models import VideoWorkItemRecord
from tests.test_video_work_talking import _stuck, jobs, studio, submits  # noqa: F401


def _detached(client, root, ws, user, provider, **job_fields):
    """A task left 'running' by a dead process that no work item points at."""
    batch, job_id = _stuck(client, root, ws, user, provider, **job_fields)
    with client.app.state.session_factory() as session:
        session.execute(
            update(VideoWorkItemRecord)
            .where(VideoWorkItemRecord.batch_id == batch["id"])
            .values(generation_task_id=None, stage="finishing", status="pending")
        )
        session.commit()
    return job_id


def test_stale_avatar_motion_with_provider_id_resumes_querying_only(
    studio, monkeypatch  # noqa: F811
):
    client, _, provider, root, ws, user = studio
    job_id = _detached(
        client,
        root,
        ws,
        user,
        provider,
        kind="h3_template",
        stage="h3_generating",
        provider_task_id="h3-known",
        details={"stage_history": [{"stage": "h3_submitting"}]},
    )
    runs = []
    monkeypatch.setattr(
        talking, "process_generation", lambda *a, **k: runs.append((a[2], k))
    )
    factory, settings = client.app.state.session_factory, client.app.state.settings
    assert talking.sweep_once(factory, settings, provider) == [job_id]
    assert [r[0] for r in runs] == [job_id] and "lease" in runs[0][1]
    with factory() as session:
        assert session.get(VideoGenerationRecord, job_id).status == "queued"
    assert submits(provider) == [] and jobs(client) == 1


def test_stale_task_without_provider_id_becomes_unknown_and_check_never_resubmits(
    studio, monkeypatch  # noqa: F811
):
    client, _, provider, root, ws, user = studio
    job_id = _detached(
        client,
        root,
        ws,
        user,
        provider,
        kind="h3_template",
        stage="h3_submitting",
        provider_task_id=None,
        details={"stage_history": [{"stage": "h3_submitting"}]},
    )
    runs = []
    monkeypatch.setattr(talking, "process_generation", lambda *a, **k: runs.append(a))
    factory, settings = client.app.state.session_factory, client.app.state.settings
    assert talking.sweep_once(factory, settings, provider) == []
    with factory() as session:
        job = session.get(VideoGenerationRecord, job_id)
        assert (job.status, job.error_code) == (
            "unknown",
            "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
        )
    checked = client.post(root + f"/generation-tasks/{job_id}/check")
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["id"] == job_id and body["status"] == "unknown"
    assert "不会重新生成" in body["notice"]
    assert runs == [] and submits(provider) == [] and jobs(client) == 1


def test_check_continues_a_lost_task_with_a_provider_id(studio, monkeypatch):  # noqa: F811
    client, _, provider, root, ws, user = studio
    job_id = _detached(
        client,
        root,
        ws,
        user,
        provider,
        stage="lipsync_generating",
        provider_task_id="lip-known",
        details={
            "stage_history": [{"stage": "lipsync_submitting"}],
            "audio_url": "https://sowa.oss-cn-beijing.aliyuncs.com/audio.mp3",
        },
    )
    runs = []
    monkeypatch.setattr(
        talking, "process_generation", lambda *a, **k: runs.append((a[2], k))
    )
    checked = client.post(root + f"/generation-tasks/{job_id}/check")
    assert checked.status_code == 200, checked.text
    assert checked.json()["status"] == "queued" and checked.json()["notice"] is None
    assert [r[0] for r in runs] == [job_id] and "lease" in runs[0][1]
    assert submits(provider) == []


def test_recent_task_outside_batches_is_left_alone_and_others_cannot_check(
    studio, monkeypatch  # noqa: F811
):
    client, auth, provider, root, ws, user = studio
    job_id = _detached(
        client,
        root,
        ws,
        user,
        provider,
        stage="lipsync_generating",
        provider_task_id="lip-known",
    )
    with client.app.state.session_factory() as session:
        # Heartbeat just now: its run is alive.
        session.execute(
            update(VideoGenerationRecord)
            .where(VideoGenerationRecord.id == job_id)
            .values(updated_at=talking.utc_now())
        )
        session.commit()
    runs = []
    monkeypatch.setattr(talking, "process_generation", lambda *a, **k: runs.append(a))
    factory, settings = client.app.state.session_factory, client.app.state.settings
    assert talking.sweep_once(factory, settings, provider) == []
    assert runs == []
    other = root.replace(ws, "ws_someone_else")
    assert client.post(other + f"/generation-tasks/{job_id}/check").status_code in {
        403,
        404,
    }
