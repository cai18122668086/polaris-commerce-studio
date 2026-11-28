"""B6: one dispatcher per user for talking and editing, on real PostgreSQL.

The advisory lock is a no-op on SQLite, so these tests only run when
POLARIS_TEST_ROUTE_DATABASE_URL moves the route tests to PostgreSQL (the CI
job ``video-v3-postgres``)."""

import threading
import time
from collections import Counter
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app import video_work_editing as editing
from app.video_dispatch_lock import DispatchLock
from app.video_work_editing_models import ACTIVE_PHASES, VideoWorkEditingRunRecord
from app.video_work_models import VideoWorkBatchRecord
from app.video_work_talking import _workspace_for
from tests.test_video_projects import base
from tests.test_video_work_editing import prepare_world, submit

pytest_plugins = ["tests.test_video_projects"]


def _require_postgres(factory):
    with factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("advisory locks only exist on PostgreSQL")


def test_dispatch_lock_is_exclusive_per_user_and_stage(video, tmp_path, monkeypatch):
    client = video[0]
    factory = client.app.state.session_factory
    _require_postgres(factory)
    with factory() as one, factory() as two:
        first = DispatchLock(one, "editing", "usr_a")
        assert first.acquire()
        try:
            assert not DispatchLock(two, "editing", "usr_a").acquire()
            # Other users and the other stage are not blocked.
            other_user = DispatchLock(two, "editing", "usr_b")
            assert other_user.acquire()
            other_user.release()
            other_stage = DispatchLock(two, "talking", "usr_a")
            assert other_stage.acquire()
            other_stage.release()
        finally:
            first.release()
        again = DispatchLock(two, "editing", "usr_a")
        assert again.acquire()
        again.release()


def test_twenty_concurrent_dispatches_start_each_item_once_and_at_most_two(
    video, tmp_path, monkeypatch
):
    client, ws, settings, factory, _semantic, batch_a = prepare_world(
        video, tmp_path, monkeypatch, count=3
    )
    _require_postgres(factory)
    batch_b = client.post(
        base(ws) + "/work-batches",
        json={
            "request_id": str(uuid4()),
            "source": "editing_upload",
            "items": [
                {
                    "drive_mode": "uploaded_video",
                    "source_video_ref": dict(item["source_video_ref"]),
                }
                for item in batch_a["items"]
            ],
        },
    )
    assert batch_b.status_code == 200, batch_b.text
    batch_b = batch_b.json()
    # Submit both batches without dispatching: six runs wait in "queued".
    with monkeypatch.context() as quiet:
        quiet.setattr(editing, "dispatch", lambda *args, **kwargs: None)
        for batch in (batch_a, batch_b):
            response = submit(client, ws, batch)
            assert response.status_code == 200, response.text

    created: Counter[str] = Counter()
    guard = threading.Lock()
    recognized = editing.persist_editing_task

    def slow_persist(body, settings_, workspace, session, **kwargs):
        with guard:
            created[str(body.request_id)] += 1
        time.sleep(0.2)  # Widen the window two dispatchers would race in.
        return recognized(body, settings_, workspace, session, **kwargs)

    monkeypatch.setattr(editing, "persist_editing_task", slow_persist)
    with factory() as session:
        row = session.get(VideoWorkBatchRecord, batch_a["id"])
        workspace = _workspace_for(session, row.workspace_id, row.owner_user_id)
        user_id = row.owner_user_id
    assert workspace is not None

    barrier = threading.Barrier(20, timeout=30)
    errors: list[BaseException] = []

    def call(batch_id: str) -> None:
        try:
            barrier.wait()
            with factory() as session:
                editing.dispatch(session, settings, workspace, batch_id)
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [
        threading.Thread(target=call, args=((batch_a, batch_b)[n % 2]["id"],))
        for n in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not errors, errors

    with factory() as session:
        active = session.scalar(
            select(func.count())
            .select_from(VideoWorkEditingRunRecord)
            .where(
                VideoWorkEditingRunRecord.owner_user_id == user_id,
                VideoWorkEditingRunRecord.phase.in_(ACTIVE_PHASES),
            )
        )
        queued = session.scalar(
            select(func.count())
            .select_from(VideoWorkEditingRunRecord)
            .where(VideoWorkEditingRunRecord.phase == "queued")
        )
    assert active == editing.EDITING_PARALLEL == 2
    assert queued == 4
    # Every started item created its recognition task exactly once.
    assert len(created) == 2 and set(created.values()) == {1}, created
