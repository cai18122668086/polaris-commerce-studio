"""C8: sweeps pick the most recently updated batches first, and a 结果待确认
older than 24 hours is settled as failed with its hold released."""

from datetime import timedelta

from sqlalchemy import update

from app import video_work_editing as editing
from app import video_work_talking as talking
from app.models import utc_now
from app.video_generation_models import VideoGenerationRecord
from app.video_work_editing_models import VideoWorkEditingRunRecord
from app.video_work_models import VideoWorkItemRecord

pytest_plugins = ["tests.test_video_projects"]

from tests.test_video_work_talking import (  # noqa: F401, E402
    _balance,
    _holds,
    _stuck,
    item,
    jobs,
    new_batch,
    priced,
    studio,
    submits,
)


def _age(client, job_id, **delta):
    with client.app.state.session_factory() as session:
        session.execute(
            update(VideoGenerationRecord)
            .where(VideoGenerationRecord.id == job_id)
            .values(status="unknown", updated_at=utc_now() - timedelta(**delta))
        )
        session.commit()


def test_unconfirmed_for_24_hours_fails_and_releases_its_hold(priced):  # noqa: F811
    client, _, provider, root, ws, user = priced
    _balance(client, ws, 100)
    batch, job_id = _stuck(
        client, root, ws, user, provider, stage="lipsync_submitting",
        provider_task_id=None,
        details={"stage_history": [{"stage": "lipsync_submitting"}]},
    )
    assert _holds(client)[job_id][0] == "active"
    _age(client, job_id, hours=25)
    factory, settings = client.app.state.session_factory, client.app.state.settings
    talking.sweep_once(factory, settings, provider)
    with factory() as session:
        job = session.get(VideoGenerationRecord, job_id)
        assert (job.status, job.error_code) == (
            "failed",
            talking.UNCONFIRMED_EXPIRED,
        )
    assert _holds(client)[job_id][0] == "released"
    assert _balance(client, ws) == (100, 0)
    row = client.get(root + f"/work-batches/{batch['id']}").json()["items"][0]
    assert row["status"] == "failed" and "联系客服" in row["error"]
    assert submits(provider) == [] and jobs(client) == 1


def test_unconfirmed_for_less_than_a_day_is_kept(studio):  # noqa: F811
    client, _, provider, root, ws, user = studio
    _batch, job_id = _stuck(
        client, root, ws, user, provider, stage="lipsync_submitting",
        provider_task_id=None,
    )
    _age(client, job_id, hours=23)
    factory = client.app.state.session_factory
    assert talking.expire_unconfirmed(factory) == []
    with factory() as session:
        assert session.get(VideoGenerationRecord, job_id).status == "unknown"


def test_talking_sweep_visits_the_most_recently_updated_batch_first(
    studio, monkeypatch  # noqa: F811
):
    client, _, provider, root, ws, user = studio
    old = new_batch(client, root, item("旧"))
    new = new_batch(client, root, item("新"))
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory() as session:
        for batch, hours in ((old, 5), (new, 1)):
            session.execute(
                update(VideoWorkItemRecord)
                .where(VideoWorkItemRecord.batch_id == batch["id"])
                .values(
                    status="queued", updated_at=utc_now() - timedelta(hours=hours)
                )
            )
        session.commit()
    seen = []
    monkeypatch.setattr(
        talking, "advance", lambda f, s, p, batch_id: seen.append(batch_id) or []
    )
    talking.sweep_once(factory, settings, provider)
    assert seen == [new["id"], old["id"]]


def test_editing_sweep_visits_the_most_recently_updated_batch_first(
    video, tmp_path, monkeypatch
):
    from tests.test_video_work_editing import prepare_world, submit

    client, ws, settings, factory, _semantic, first = prepare_world(
        video, tmp_path, monkeypatch, count=1
    )
    assert submit(client, ws, first).status_code == 200
    from uuid import uuid4

    from tests.test_video_projects import base

    other = client.post(
        base(ws) + "/work-batches",
        json={
            "request_id": str(uuid4()),
            "source": "editing_upload",
            "items": [
                {
                    "drive_mode": "uploaded_video",
                    "source_video_ref": dict(first["items"][0]["source_video_ref"]),
                }
            ],
        },
    ).json()
    assert submit(client, ws, other).status_code == 200
    with factory() as session:
        for batch, hours in ((first, 1), (other, 5)):
            session.execute(
                update(VideoWorkEditingRunRecord)
                .where(VideoWorkEditingRunRecord.batch_id == batch["id"])
                .values(updated_at=utc_now() - timedelta(hours=hours))
            )
        session.commit()
    seen = []
    monkeypatch.setattr(
        editing, "dispatch", lambda s, st, w, batch_id: seen.append(batch_id)
    )
    editing.sweep_once(factory, settings)
    assert seen == [first["id"], other["id"]]
