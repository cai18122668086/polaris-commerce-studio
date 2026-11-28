"""B9: the server, not the request body, moves work items between stages."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import UserRecord
from app.video_editing_task_models import EditingTaskRecord
from app.video_generation_models import VideoGenerationRecord
from app.video_work_models import VideoWorkBatchRecord, VideoWorkItemRecord
from tests.test_video_editing_planning_tasks import setup
from tests.test_video_projects import base
from tests.test_video_work_items import (
    batch_body,
    create,
    generation,
    item,
    patch,
    server_set,
)

pytest_plugins = ["tests.test_video_projects"]


def _batches(client):
    with client.app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(VideoWorkBatchRecord))


def test_a_talking_result_cannot_become_a_second_item_at_batch_creation(video):
    client, _, ws, user, _ = video
    talking = create(client, ws, batch_body(item("口播稿")))
    task = generation(client, ws, user)
    server_set(
        client,
        ws,
        user,
        talking["item_ids"][0],
        generation_task_id=task,
        status="succeeded",
    )
    before = _batches(client)
    for kind in ("talking", "library"):
        copy = client.post(
            base(ws) + "/work-batches",
            json=batch_body(
                item(
                    drive_mode="uploaded_video",
                    source_video_ref={"kind": kind, "id": task},
                ),
                source="editing_upload",
            ),
        )
        assert copy.status_code == 409, copy.text
        error = copy.json()["error"]
        assert error["code"] == "VIDEO_WORK_SOURCE_HAS_ITEM"
        assert error["details"]["item_id"] == talking["item_ids"][0]
    assert _batches(client) == before  # no empty batch left behind
    # A video no batch owns is still accepted.
    free = generation(client, ws, user)
    ok = client.post(
        base(ws) + "/work-batches",
        json=batch_body(
            item(
                drive_mode="uploaded_video",
                source_video_ref={"kind": "library", "id": free},
            ),
            source="editing_upload",
        ),
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.parametrize(
    "fields",
    [
        {"stage": "done"},
        {"status": "succeeded"},
        {"error": "x"},
        {"generation_task_id": "t"},
        {"editing_task_id": "t"},
        {"cover_asset_id": "c"},
        {"source_video_ref": {"kind": "upload", "id": "u"}},
    ],
)
def test_patch_refuses_stage_status_and_task_fields(video, fields):
    client, _, ws, _, _ = video
    item_id = create(client, ws, batch_body(item()))["item_ids"][0]
    refused = patch(client, ws, item_id, expected_version=1, **fields)
    assert refused.status_code == 422, (fields, refused.text)
    row = client.get(base(ws) + f"/work-items/{item_id}").json()
    assert (row["stage"], row["status"], row["version"]) == ("talking", "pending", 1)


def test_patch_still_edits_content_and_the_published_mark(video):
    client, _, ws, _, _ = video
    item_id = create(client, ws, batch_body(item()))["item_ids"][0]
    edited = patch(
        client,
        ws,
        item_id,
        expected_version=1,
        publish_title="新标题",
        publish_body="新正文",
        script_text="新口播稿",
        avatar_id="female-021",
        voice_id="calm",
        persona_id=None,
        published=True,
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["publish_title"], body["avatar_id"], body["version"]) == (
        "新标题",
        "female-021",
        2,
    )
    assert body["stage"] == "talking" and body["status"] == "pending"


def test_finish_requires_a_finished_video(video):
    client, _, ws, user, _ = video
    first, second = create(client, ws, batch_body(item("甲"), item("乙")))["item_ids"]

    def finish(item_id):
        version = client.get(base(ws) + f"/work-items/{item_id}").json()["version"]
        return client.post(
            base(ws) + f"/work-items/{item_id}/finish",
            json={
                "expected_version": version,
                "cover_candidate_id": str(uuid4()),
                "publish_title": "标题",
            },
        )

    # Talking not finished yet: no playable video.
    refused = finish(first)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "VIDEO_WORK_ITEM_NOT_READY"
    # Still editing: a stale tab cannot mark it 已完成.
    server_set(client, ws, user, second, stage="editing", status="running")
    busy = finish(second)
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "VIDEO_WORK_ITEM_BUSY"
    # A finished talking video passes this check (the cover is checked next).
    task = generation(client, ws, user)
    with client.app.state.session_factory() as session:
        session.get(VideoGenerationRecord, task).status = "completed"
        session.commit()
    server_set(client, ws, user, first, generation_task_id=task, status="succeeded")
    assert finish(first).json()["error"]["code"] == "COVER_NOT_FOUND"


def _copy_task(session, task_id, **changes):
    row = session.get(EditingTaskRecord, task_id)
    values = {c.name: getattr(row, c.name) for c in EditingTaskRecord.__table__.columns}
    values.update(id=str(uuid4()), request_id=str(uuid4()), **changes)
    session.add(EditingTaskRecord(**values))
    session.commit()
    return values["id"]


def test_adopt_editing_moves_to_finishing_keeps_history_and_is_idempotent(
    video, tmp_path, monkeypatch
):
    client, _, ws, _settings, source, task, _ = setup(video, tmp_path, monkeypatch)
    batch = create(
        client,
        ws,
        batch_body(
            item(
                drive_mode="uploaded_video",
                source_video_ref={"kind": "upload", "id": source},
            ),
            source="editing_upload",
        ),
    )
    item_id = batch["item_ids"][0]
    root = base(ws) + f"/work-items/{item_id}/adopt-editing"
    factory = client.app.state.session_factory
    with factory() as session:
        first = _copy_task(session, task["id"], status="completed")
        second = _copy_task(session, task["id"], status="completed")
        unfinished = _copy_task(session, task["id"], status="running")
        session.add(
            UserRecord(id="usr_other_b9", auth_provider="test", auth_subject="b9")
        )
        session.commit()
        foreign = _copy_task(
            session, task["id"], status="completed", owner_user_id="usr_other_b9"
        )

    adopted = client.post(root, json={"editing_task_id": first})
    assert adopted.status_code == 200, adopted.text
    body = adopted.json()
    assert (body["editing_task_id"], body["stage"], body["status"]) == (
        first,
        "finishing",
        "pending",
    )
    assert "video_updated" not in body["history"]  # first video: nothing replaced
    again = client.post(root, json={"editing_task_id": first})
    assert again.status_code == 200 and again.json()["version"] == body["version"]

    replaced = client.post(root, json={"editing_task_id": second}).json()
    assert replaced["editing_task_id"] == second
    assert replaced["history"]["editing"] == [first]
    assert len(replaced["history"]["video_updated"]) == 1
    assert replaced["stage"] == "finishing"

    not_done = client.post(root, json={"editing_task_id": unfinished})
    assert not_done.status_code == 409
    assert not_done.json()["error"]["code"] == "VIDEO_WORK_EDITING_NOT_DONE"
    stranger = client.post(root, json={"editing_task_id": foreign})
    assert stranger.status_code == 422
    assert stranger.json()["error"]["code"] == "VIDEO_WORK_REFERENCE_INVALID"
    with factory() as session:
        assert session.get(VideoWorkItemRecord, item_id).editing_task_id == second
