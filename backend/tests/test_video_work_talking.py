"""Batch talking: N items -> N independent lipsync tasks, queued, idempotent."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import services
from app import video_work_talking as talking
from app.auth import Principal, WorkspaceContext
from app.domain import MembershipRole
from app.errors import ApiError
from app.main import create_app
from app.models import (
    CreditReservationRecord,
    WorkspaceCreditAccountRecord,
    WorkspaceMemberRecord,
)
from app.video_generation_models import VideoGenerationRecord
from app.video_studio_models import VideoProjectRecord
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_generation import FakeVideoProviders

EMAIL = "1474953130@qq.com"
SUBMIT = "/api/digital_human/submit"
TTS = "/api/tts/generate"


class TwoAvatarProviders(FakeVideoProviders):
    """Two public presenters and two public voices; model 13 can be rejected."""

    reject_model: int | None = None

    def models(self):
        return [
            *super().models(),
            {
                "id": 13,
                "model_name": "公共形象二",
                "is_public": True,
                "is_active": True,
                "model_type": "video",
                "video_url": "https://sowa.oss-cn-beijing.aliyuncs.com/public2.mp4",
            },
        ]

    def voices(self):
        return [{"id": 1, "name": "温柔女声"}, {"id": 2, "name": "沉稳男声"}]

    def request(self, vendor, method, path, **kwargs):
        body = kwargs.get("json") or {}
        if (
            method == "POST"
            and path == SUBMIT
            and self.reject_model is not None
            and str(self.reject_model) in str(body)
        ):
            self.posts.append((vendor, path, body))
            raise ApiError(422, "VIDEO_PROVIDER_REJECTED", "fixture rejected")
        return super().request(vendor, method, path, **kwargs)


@pytest.fixture
def studio(tmp_path):
    auth = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
    settings = external_settings(tmp_path).model_copy(
        update={
            "video_providers_enabled": True,
            "video_media_dir": tmp_path / "video",
            "task_dispatcher": "inline",
            "video_talking_sweep_enabled": False,
        }
    )
    app = create_app(settings, auth)
    provider = TwoAvatarProviders()
    app.state.video_providers = provider
    with TestClient(app) as client:
        ws = client.get("/api/v1/workspaces").json()[0]["id"]
        user = client.get("/api/v1/me").json()["id"]
        root = f"/api/v1/video-studio/workspaces/{ws}"
        assert client.get(root + "/avatars").status_code == 200
        yield client, auth, provider, root, ws, user


def item(text, avatar="qy-model-11", voice="qy-voice-1", **extra):
    return {
        "script_text": text,
        "publish_title": text[:10],
        "avatar_id": avatar,
        "voice_id": voice,
        **extra,
    }


def new_batch(client, root, *items):
    body = {"request_id": str(uuid4()), "source": "talking", "items": list(items)}
    response = client.post(root + "/work-batches", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def submits(provider):
    return [body for _, path, body in provider.posts if path == SUBMIT]


def jobs(client):
    with client.app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(VideoGenerationRecord))


def test_two_scripts_two_presenters_two_voices_each_get_their_own_task(studio):
    client, _, provider, root, _, _ = studio
    batch = new_batch(
        client,
        root,
        item("第一条稿：冰丝凉席睡得凉快"),
        item("第二条稿：换个人来讲同一款", avatar="qy-model-13", voice="qy-voice-2"),
    )
    response = client.post(root + f"/work-batches/{batch['id']}/talking")
    assert response.status_code == 200, response.text
    view = client.get(root + f"/work-batches/{batch['id']}/talking").json()
    items = view["batch"]["items"]
    assert [i["status"] for i in items] == ["succeeded", "succeeded"]
    assert all(v["video_url"] for v in view["talking"])
    assert items[0]["generation_task_id"] != items[1]["generation_task_id"]
    assert items[1]["source_video_ref"] == {
        "kind": "talking",
        "id": items[1]["generation_task_id"],
    }
    tts_voices = [b["cloud_voice_id"] for _, p, b in provider.posts if p == TTS]
    assert sorted(tts_voices) == ["1", "2"]
    assert len(submits(provider)) == 2
    tasks = {t["id"]: t for t in client.get(root + "/generation-tasks").json()}
    first = tasks[items[0]["generation_task_id"]]["snapshot"]["draft"]
    second = tasks[items[1]["generation_task_id"]]["snapshot"]["draft"]
    assert (first["avatarId"], first["voiceId"], first["text"]) == (
        "qy-model-11",
        "qy-voice-1",
        "第一条稿：冰丝凉席睡得凉快",
    )
    assert (second["avatarId"], second["voiceId"]) == ("qy-model-13", "qy-voice-2")


def test_same_presenter_for_three_scripts_builds_three_requests(studio):
    client, _, provider, root, _, _ = studio
    batch = new_batch(client, root, item("稿一"), item("稿二"), item("稿三"))
    client.post(root + f"/work-batches/{batch['id']}/talking")
    assert len(submits(provider)) == 3
    tasks = client.get(root + "/generation-tasks").json()
    drafts = sorted(t["snapshot"]["draft"]["text"] for t in tasks)
    assert drafts == ["稿一", "稿三", "稿二"]
    assert {t["avatar_id"] for t in tasks} == {"qy-model-11"}


def test_repeated_submit_reload_and_replayed_batch_never_charge_twice(studio):
    client, _, provider, root, _, _ = studio
    body = {
        "request_id": str(uuid4()),
        "source": "talking",
        "items": [item("稿一"), item("稿二")],
    }
    batch = client.post(root + "/work-batches", json=body).json()
    for _ in range(3):
        assert (
            client.post(root + f"/work-batches/{batch['id']}/talking").status_code
            == 200
        )
    assert client.post(root + "/work-batches", json=body).json()["id"] == batch["id"]
    client.post(root + f"/work-batches/{batch['id']}/talking")
    client.get(root + f"/work-batches/{batch['id']}/talking")
    assert len(submits(provider)) == 2
    assert jobs(client) == 2


def test_lost_link_after_task_creation_reuses_the_same_task(studio, monkeypatch):
    """A crash between creating the task and linking the item must not re-submit."""
    client, _, provider, root, ws, user = studio
    batch = new_batch(client, root, item("稿一"))
    original = talking._write
    calls = {"n": 0}

    def flaky(session, row, **values):
        if "generation_task_id" in values and values["generation_task_id"]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("connection dropped")
        return original(session, row, **values)

    monkeypatch.setattr(talking, "_write", flaky)
    with pytest.raises(RuntimeError):
        client.post(root + f"/work-batches/{batch['id']}/talking")
    monkeypatch.setattr(talking, "_write", original)
    client.post(root + f"/work-batches/{batch['id']}/talking")
    assert jobs(client) == 1
    view = client.get(root + f"/work-batches/{batch['id']}/talking").json()
    assert view["batch"]["items"][0]["generation_task_id"]


def test_parallel_limit_queues_the_rest_with_positions(studio, monkeypatch):
    client, _, provider, root, ws, user = studio
    monkeypatch.setattr(talking, "TALKING_PARALLEL", 2)
    batch = new_batch(client, root, item("稿一"), item("稿二"), item("稿三"))
    workspace = WorkspaceContext(Principal(user_id=user), ws, MembershipRole.OWNER)
    settings = client.app.state.settings
    with client.app.state.session_factory() as session:
        # Unconfirmed items are never started, not even by a dispatch.
        assert (
            talking.dispatch(
                session, settings, workspace, batch["id"], lambda: provider
            )
            == []
        )
        talking.confirm(
            session, settings, ws, talking.batch_items(session, batch["id"])
        )
        started = talking.dispatch(
            session, settings, workspace, batch["id"], lambda: provider
        )
        assert len(started) == 2
        view = talking.talking_view(
            session, session.get(talking.VideoWorkBatchRecord, batch["id"])
        )
        assert [i.queue_position for i in view.talking] == [None, None, 1]
        assert [i.status for i in view.batch.items] == ["queued", "queued", "queued"]
        assert view.batch.items[2].generation_task_id is None
        # Nothing frees a slot yet: dispatching again starts nothing.
        assert (
            talking.dispatch(
                session, settings, workspace, batch["id"], lambda: provider
            )
            == []
        )
        first = session.get(VideoGenerationRecord, started[0])
        first.status = "completed"
        session.commit()
        third = talking.dispatch(
            session, settings, workspace, batch["id"], lambda: provider
        )
        assert len(third) == 1
        view = talking.talking_view(
            session, session.get(talking.VideoWorkBatchRecord, batch["id"])
        )
        assert [i.status for i in view.batch.items] == [
            "succeeded",
            "queued",
            "queued",
        ]
        assert all(i.queue_position is None for i in view.talking)


def test_finished_task_starts_the_next_waiting_item(studio, monkeypatch):
    client, _, provider, root, _, _ = studio
    monkeypatch.setattr(talking, "TALKING_PARALLEL", 1)
    batch = new_batch(client, root, item("稿一"), item("稿二"), item("稿三"))
    client.post(root + f"/work-batches/{batch['id']}/talking")
    view = client.get(root + f"/work-batches/{batch['id']}/talking").json()
    assert [i["status"] for i in view["batch"]["items"]] == ["succeeded"] * 3
    assert len(submits(provider)) == 3


def test_one_failure_does_not_stop_others_and_retries_alone(studio):
    client, _, provider, root, _, _ = studio
    provider.reject_model = 13
    batch = new_batch(
        client,
        root,
        item("稿一"),
        item("稿二", avatar="qy-model-13", voice="qy-voice-2"),
        item("稿三"),
    )
    client.post(root + f"/work-batches/{batch['id']}/talking")
    view = client.get(root + f"/work-batches/{batch['id']}/talking").json()
    items = view["batch"]["items"]
    assert [i["status"] for i in items] == ["succeeded", "failed", "succeeded"]
    assert items[1]["error"] and "VIDEO_" not in items[1]["error"]
    assert [v["can_retry"] for v in view["talking"]] == [False, True, False]
    failed_task = items[1]["generation_task_id"]
    provider.reject_model = None
    before = len(submits(provider))
    retried = client.post(root + f"/work-items/{items[1]['id']}/talking-retry")
    assert retried.status_code == 200, retried.text
    # The response is written before the background task runs.
    assert retried.json()["batch"]["items"][1]["status"] == "queued"
    after = client.get(root + f"/work-batches/{batch['id']}").json()["items"]
    assert [i["status"] for i in after] == ["succeeded"] * 3
    assert after[1]["history"] == {"generation": [failed_task]}
    assert after[1]["generation_task_id"] != failed_task
    assert after[0]["generation_task_id"] == items[0]["generation_task_id"]
    assert len(submits(provider)) == before + 1
    # Clicking retry again on a succeeded item submits nothing new.
    again = client.post(root + f"/work-items/{items[1]['id']}/talking-retry")
    assert again.status_code == 200
    assert len(submits(provider)) == before + 1


def test_item_rejected_before_any_task_can_be_fixed_and_retried(studio):
    client, _, provider, root, _, _ = studio
    batch = new_batch(client, root, item("稿一"), item("稿二", avatar="qy-model-404"))
    client.post(root + f"/work-batches/{batch['id']}/talking")
    items = client.get(root + f"/work-batches/{batch['id']}").json()["items"]
    assert [i["status"] for i in items] == ["succeeded", "failed"]
    assert items[1]["generation_task_id"] is None
    fixed = client.patch(
        root + f"/work-items/{items[1]['id']}",
        json={"expected_version": items[1]["version"], "avatar_id": "qy-model-11"},
    )
    assert fixed.status_code == 200
    client.post(root + f"/work-items/{items[1]['id']}/talking-retry")
    retried = client.get(root + f"/work-batches/{batch['id']}").json()["items"][1]
    assert retried["status"] == "succeeded"
    assert retried["history"] == {"generation": ["none:0"]}
    with client.app.state.session_factory() as session:
        # One project per attempt keeps the failed attempt's script history.
        assert session.scalar(select(func.count()).select_from(VideoProjectRecord)) == 3


def test_other_user_cannot_submit_poll_or_retry(studio):
    client, auth, provider, root, ws, _ = studio
    batch = new_batch(client, root, item("稿一"))
    auth.identity = verified_identity(primary_user_id="someone-else", email=EMAIL)
    other = client.get("/api/v1/me").json()["id"]
    with client.app.state.session_factory() as session:
        session.add(
            WorkspaceMemberRecord(
                workspace_id=ws, user_id=other, role="owner", status="active"
            )
        )
        session.commit()
    assert client.post(root + f"/work-batches/{batch['id']}/talking").status_code == 404
    assert client.get(root + f"/work-batches/{batch['id']}/talking").status_code == 404
    item_id = batch["item_ids"][0]
    assert client.post(root + f"/work-items/{item_id}/talking-retry").status_code == 404
    assert submits(provider) == []


def test_editing_upload_batch_cannot_be_sent_to_talking(studio):
    client, _, provider, root, _, _ = studio
    body = {
        "request_id": str(uuid4()),
        "source": "editing_upload",
        "items": [
            {
                "drive_mode": "uploaded_video",
                "source_video_ref": {"kind": "upload", "id": "src"},
            }
        ],
    }
    batch = client.post(root + "/work-batches", json=body).json()
    assert client.post(root + f"/work-batches/{batch['id']}/talking").status_code == 422
    assert submits(provider) == []


def test_polling_never_starts_an_unconfirmed_batch(studio):
    client, _, provider, root, _, _ = studio
    batch = new_batch(client, root, item("稿一"), item("稿二"))
    for _ in range(2):
        view = client.get(root + f"/work-batches/{batch['id']}/talking").json()
    assert [i["status"] for i in view["batch"]["items"]] == ["pending", "pending"]
    assert submits(provider) == [] and jobs(client) == 0


def _owner(ws, user):
    return WorkspaceContext(Principal(user_id=user), ws, MembershipRole.OWNER)


def test_restart_sweep_finishes_a_queue_left_behind(studio, monkeypatch):
    """An api restart drops the in-process chain; the sweep picks it up."""
    client, _, provider, root, ws, user = studio
    monkeypatch.setattr(talking, "TALKING_PARALLEL", 1)
    batch = new_batch(client, root, item("稿一"), item("稿二"))
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory() as session:
        talking.confirm(
            session, settings, ws, talking.batch_items(session, batch["id"])
        )
        first = talking.dispatch(
            session, settings, _owner(ws, user), batch["id"], lambda: provider
        )
        # The process died: the first task finished, but nobody started the next.
        job = session.get(VideoGenerationRecord, first[0])
        job.status = "completed"
        session.commit()
    assert submits(provider) == []
    started = talking.sweep_once(factory, settings, provider)
    assert len(started) == 1
    items = client.get(root + f"/work-batches/{batch['id']}").json()["items"]
    assert [i["status"] for i in items] == ["succeeded", "succeeded"]
    assert len(submits(provider)) == 1
    assert talking.sweep_once(factory, settings, provider) == []
    assert len(submits(provider)) == 1


def test_restart_sweep_runs_a_created_task_whose_run_was_lost(studio):
    client, _, provider, root, ws, user = studio
    batch = new_batch(client, root, item("稿一"))
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory() as session:
        talking.confirm(
            session, settings, ws, talking.batch_items(session, batch["id"])
        )
        (job_id,) = talking.dispatch(
            session, settings, _owner(ws, user), batch["id"], lambda: provider
        )
    # Young queued tasks belong to their request's background run: left alone.
    assert talking.sweep_once(factory, settings, provider) == []
    with factory() as session:
        job = session.get(VideoGenerationRecord, job_id)
        job.created_at = job.created_at.replace(year=job.created_at.year - 1)
        session.commit()
    assert talking.sweep_once(factory, settings, provider) == [job_id]
    items = client.get(root + f"/work-batches/{batch['id']}").json()["items"]
    assert items[0]["status"] == "succeeded"
    assert len(submits(provider)) == 1
    assert talking.sweep_once(factory, settings, provider) == []
    assert len(submits(provider)) == 1


@pytest.fixture
def priced(studio):
    client = studio[0]
    client.app.state.settings.video_credit_prices = {"lipsync": 50}
    services.set_quota_enabled(True)
    services.set_credit_enforcement_enabled(True)
    try:
        yield studio
    finally:
        services.set_quota_enabled(True)
        services.set_credit_enforcement_enabled(
            client.app.state.settings.workspace_credit_enforcement_enabled
        )


def _balance(client, ws, credits=None):
    with client.app.state.session_factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, ws)
        if credits is not None:
            account.balance_credits = credits
            session.commit()
        return account.balance_credits, account.reserved_credits


def _holds(client):
    with client.app.state.session_factory() as session:
        rows = session.scalars(
            select(CreditReservationRecord).where(
                CreditReservationRecord.owner_type == "video_generation"
            )
        ).all()
        return {r.owner_id: (r.status, r.settled_credits) for r in rows}


def test_whole_batch_is_refused_when_credits_cannot_cover_it(priced):
    client, _, provider, root, ws, _ = priced
    _balance(client, ws, 100)
    batch = new_batch(client, root, item("稿一"), item("稿二"), item("稿三"))
    refused = client.post(root + f"/work-batches/{batch['id']}/talking")
    assert refused.status_code == 402
    error = refused.json()["error"]
    assert "150" in error["message"] and "100" in error["message"]
    items = client.get(root + f"/work-batches/{batch['id']}").json()["items"]
    assert [i["status"] for i in items] == ["pending"] * 3
    assert submits(provider) == [] and jobs(client) == 0 and _holds(client) == {}


def test_failed_item_releases_its_hold_and_others_are_charged(priced):
    client, _, provider, root, ws, _ = priced
    _balance(client, ws, 150)
    provider.reject_model = 13
    batch = new_batch(
        client,
        root,
        item("稿一"),
        item("稿二", avatar="qy-model-13", voice="qy-voice-2"),
        item("稿三"),
    )
    assert client.post(root + f"/work-batches/{batch['id']}/talking").status_code == 200
    items = client.get(root + f"/work-batches/{batch['id']}").json()["items"]
    assert [i["status"] for i in items] == ["succeeded", "failed", "succeeded"]
    holds = _holds(client)
    assert holds[items[0]["generation_task_id"]] == ("settled", 50)
    assert holds[items[2]["generation_task_id"]] == ("settled", 50)
    assert holds[items[1]["generation_task_id"]][0] == "released"
    assert _balance(client, ws) == (50, 0)
    # Retrying the failed one needs 50 more: exactly what is left.
    provider.reject_model = None
    assert (
        client.post(root + f"/work-items/{items[1]['id']}/talking-retry").status_code
        == 200
    )
    assert _balance(client, ws) == (0, 0)
    # Nothing left: the next retry-worthy batch is refused up front.
    batch2 = new_batch(client, root, item("稿四"))
    assert (
        client.post(root + f"/work-batches/{batch2['id']}/talking").status_code == 402
    )


def _stuck(client, root, ws, user, provider, **job_fields):
    """A batch task left 'running' by a process that died mid-way."""
    batch = new_batch(client, root, item("稿一"))
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory() as session:
        talking.confirm(
            session, settings, ws, talking.batch_items(session, batch["id"])
        )
        (job_id,) = talking.dispatch(
            session, settings, _owner(ws, user), batch["id"], lambda: provider
        )
        job = session.get(VideoGenerationRecord, job_id)
        old = job.created_at.replace(year=job.created_at.year - 1)
        for key, value in {"status": "running", **job_fields}.items():
            setattr(job, key, value)
        job.created_at = old
        session.flush()
        session.execute(
            VideoGenerationRecord.__table__.update()
            .where(VideoGenerationRecord.id == job_id)
            .values(updated_at=old)
        )
        session.commit()
    return batch, job_id


def test_stale_task_with_provider_id_only_resumes_querying(studio, monkeypatch):
    client, _, provider, root, ws, user = studio
    batch, job_id = _stuck(
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
    factory, settings = client.app.state.session_factory, client.app.state.settings
    assert talking.sweep_once(factory, settings, provider) == [job_id]
    assert [r[0] for r in runs] == [job_id] and "lease" in runs[0][1]
    with factory() as session:
        assert session.get(VideoGenerationRecord, job_id).status == "queued"
    assert submits(provider) == []  # continued, never re-submitted


def test_stale_task_without_provider_id_waits_for_a_check(studio, monkeypatch):
    client, _, provider, root, ws, user = studio
    batch, job_id = _stuck(
        client,
        root,
        ws,
        user,
        provider,
        stage="lipsync_submitting",
        provider_task_id=None,
        details={"stage_history": [{"stage": "lipsync_submitting"}]},
    )
    runs = []
    monkeypatch.setattr(talking, "process_generation", lambda *a, **k: runs.append(a))
    factory, settings = client.app.state.session_factory, client.app.state.settings
    assert talking.sweep_once(factory, settings, provider) == []
    view = client.get(root + f"/work-batches/{batch['id']}/talking").json()
    assert view["talking"][0]["awaiting_check"] is True
    assert view["batch"]["items"][0]["status"] == "running"
    checked = client.post(root + f"/work-items/{batch['item_ids'][0]}/talking-check")
    assert checked.status_code == 200
    assert "不会重新生成" in checked.json()["notice"]
    assert runs == [] and submits(provider) == []
    # Retry is refused while the outcome is unknown: it is not a failure.
    retry = client.post(root + f"/work-items/{batch['item_ids'][0]}/talking-retry")
    assert retry.json()["batch"]["items"][0]["generation_task_id"] == job_id
    assert submits(provider) == [] and jobs(client) == 1


def test_recently_active_running_task_is_left_alone(studio, monkeypatch):
    client, _, provider, root, ws, user = studio
    batch = new_batch(client, root, item("稿一"))
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory() as session:
        talking.confirm(
            session, settings, ws, talking.batch_items(session, batch["id"])
        )
        (job_id,) = talking.dispatch(
            session, settings, _owner(ws, user), batch["id"], lambda: provider
        )
        job = session.get(VideoGenerationRecord, job_id)
        job.status, job.stage = "running", "lipsync_generating"
        session.commit()
    runs = []
    monkeypatch.setattr(talking, "process_generation", lambda *a, **k: runs.append(a))
    assert talking.sweep_once(factory, settings, provider) == []
    with factory() as session:
        assert session.get(VideoGenerationRecord, job_id).status == "running"
    assert runs == []
