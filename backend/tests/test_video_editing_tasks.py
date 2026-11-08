"""Business isolation and durable cancellation, without paid/video providers."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.video_editing_task_models import EditingAttemptRecord, EditingTaskRecord
from app.video_editing_worker import process
from tests.test_video_projects import base, payload

pytest_plugins = ["tests.test_video_projects"]


def setup_source(video, tmp_path):
    client, auth, ws, user, settings = video
    package = tmp_path / "library"
    package.mkdir()
    (package / "adapter.py").write_text("# API test: never rendered\n")
    settings.video_editing_enabled = True
    settings.video_editing_library_dir = package
    settings.video_editing_tasks_dir = tmp_path / "editing"
    client.app.state.editing_dispatcher = lambda task_id: None
    pid = str(uuid4())
    assert client.put(base(ws) + "/projects/" + pid, json=payload()).status_code == 200
    result = client.post(
        base(ws) + "/editing-sources",
        data={"project_id": pid},
        files={
            "file": ("scope-test.mp4", b"not-real-media-api-boundary-only", "video/mp4")
        },
    )
    assert result.status_code == 200, result.text
    return client, auth, ws, user, settings, pid, result.json()["id"]


def test_task_replay_cancel_retry_and_no_paths_exposed(video, tmp_path):
    client, _, ws, _, settings, _, source = setup_source(video, tmp_path)
    url = base(ws) + "/editing-tasks"
    body = {"request_id": str(uuid4()), "source_id": source}
    first = client.post(url, json=body)
    assert first.status_code == 200, first.text
    task_id = first.json()["id"]
    assert client.post(url, json=body).json()["id"] == task_id
    assert (
        client.post(url, json={**body, "options": {"language": "en"}}).status_code
        == 409
    )
    assert "media_path" not in first.text and str(tmp_path) not in first.text
    assert client.post(url + f"/{task_id}/cancel").json()["cancel_requested"]
    process(task_id, settings, client.app.state.session_factory)
    cancelled = client.get(url + f"/{task_id}").json()
    assert cancelled["status"] == "cancelled" and cancelled["artifacts"] == []
    assert client.post(url + f"/{task_id}/retry").json()["status"] == "queued"
    assert client.post(url + f"/{task_id}/retry").status_code == 409
    with client.app.state.session_factory() as session:
        attempts = list(session.scalars(select(EditingAttemptRecord)))
        assert attempts == []  # Queued cancellation never needs a live worker.


def test_task_and_source_are_scoped_to_owner_and_project(video, tmp_path):
    from tests.test_auth_external import verified_identity

    client, auth, ws, _, _, pid, source = setup_source(video, tmp_path)
    url = base(ws) + "/editing-tasks"
    created = client.post(
        url, json={"request_id": str(uuid4()), "source_id": source}
    ).json()
    auth.identity = verified_identity(
        primary_user_id="other-user", email="1474953130@qq.com"
    )
    assert client.get(url + "/" + created["id"]).status_code in (403, 404)
    assert client.post(
        url, json={"request_id": str(uuid4()), "source_id": source}
    ).status_code in (403, 404)
    assert client.post(
        base(ws) + "/editing-sources",
        data={"project_id": pid},
        files={"file": ("cross.mp4", b"x", "video/mp4")},
    ).status_code in (403, 404)


def test_valid_worker_lease_cannot_be_stolen_and_expired_run_is_fenced(video, tmp_path):
    client, _, ws, _, settings, _, source = setup_source(video, tmp_path)
    created = client.post(
        base(ws) + "/editing-tasks",
        json={"request_id": str(uuid4()), "source_id": source},
    ).json()
    factory = client.app.state.session_factory
    old_token = str(uuid4())
    with factory() as session:
        row = session.get(EditingTaskRecord, created["id"])
        row.status, row.owner_token = "running", old_token
        row.lease_until = datetime.now(UTC) + timedelta(minutes=2)
        session.commit()
    process(created["id"], settings, factory)
    with factory() as session:
        row = session.get(EditingTaskRecord, created["id"])
        assert row.owner_token == old_token and row.attempts == 0
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        row.cancel_requested = True
        session.commit()
    process(created["id"], settings, factory)
    with factory() as session:
        row = session.get(EditingTaskRecord, created["id"])
        assert (
            row.status == "cancelled" and row.owner_token is None and row.attempts == 1
        )


def test_recovery_reserves_delivery_and_broker_loss_keeps_durable_job(
    video, tmp_path, monkeypatch
):
    from app.video_editing_worker import celery_app, recover

    client, _, ws, _, _, _, source = setup_source(video, tmp_path)
    created = client.post(
        base(ws) + "/editing-tasks",
        json={"request_id": str(uuid4()), "source_id": source},
    ).json()
    factory = client.app.state.session_factory
    sent = []
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: sent.append((a, kw)))
    assert recover(factory) == 1
    assert recover(factory) == 0
    assert len(sent) == 1
    with factory() as session:
        row = session.get(EditingTaskRecord, created["id"])
        assert row.status == "queued" and row.attempts == 0
        row.checkpoint = {**row.checkpoint, "dispatch_not_before": 0}
        session.commit()

    def unavailable(*a, **kw):
        raise ConnectionError("test broker unavailable")

    monkeypatch.setattr(celery_app, "send_task", unavailable)
    assert recover(factory) == 0
    with factory() as session:
        row = session.get(EditingTaskRecord, created["id"])
        assert row.status == "queued" and row.checkpoint["dispatch_not_before"] > 0


def test_create_task_never_connects_to_broker_in_request_thread(
    video, tmp_path, monkeypatch
):
    from app.video_editing_worker import celery_app

    client, _, ws, _, _, _, source = setup_source(video, tmp_path)
    del client.app.state.editing_dispatcher

    def forbidden(*args, **kwargs):
        raise AssertionError("API must only persist, never publish or transcribe")

    monkeypatch.setattr(celery_app, "send_task", forbidden)
    result = client.post(
        base(ws) + "/editing-tasks",
        json={"request_id": str(uuid4()), "source_id": source},
    )
    assert result.status_code == 200 and result.json()["status"] == "queued"
