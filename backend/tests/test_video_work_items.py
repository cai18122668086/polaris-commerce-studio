"""Contract C2: work batches / work items (isolation, idempotency, retry)."""

import importlib.util
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import WorkspaceMemberRecord, WorkspaceRecord
from app.video_generation_models import VideoAvatarRecord, VideoGenerationRecord
from app.video_work_models import VideoWorkBatchRecord, VideoWorkItemRecord
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_projects import EMAIL, base

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations/versions/20261128_0055_video_work_items.py"
)


@pytest.fixture
def video(tmp_path):
    auth = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
    with TestClient(create_app(external_settings(tmp_path), auth)) as client:
        user = client.get("/api/v1/me").json()["id"]
        ws = client.get("/api/v1/workspaces").json()[0]["id"]
        yield client, auth, ws, user, None


def item(text="第一条口播稿", **extra):
    return {
        "publish_title": "夏天必备的冰丝凉席",
        "publish_body": "睡得凉快 #好物推荐",
        "script_text": text,
        "avatar_id": "female-020",
        "voice_id": "warm",
        **extra,
    }


def batch_body(*items, source="talking"):
    return {"request_id": str(uuid4()), "source": source, "items": list(items)}


def create(client, ws, body):
    response = client.post(base(ws) + "/work-batches", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def patch(client, ws, item_id, **fields):
    return client.patch(base(ws) + f"/work-items/{item_id}", json=fields)


def generation(client, ws, user, task_id=None):
    task_id = task_id or str(uuid4())
    with client.app.state.session_factory() as session:
        if session.get(VideoAvatarRecord, "work-test-avatar") is None:
            session.add(
                VideoAvatarRecord(
                    id="work-test-avatar", source="quanyu_public", name="测试形象"
                )
            )
            session.flush()
        session.add(
            VideoGenerationRecord(
                id=task_id,
                workspace_id=ws,
                owner_user_id=user,
                avatar_id="work-test-avatar",
                request_id=str(uuid4()),
                request_hash="0" * 64,
                kind="lipsync",
                details={},
            )
        )
        session.commit()
    return task_id


def test_batch_creates_ordered_items_and_survives_reads(video):
    client, _, ws, _, _ = video
    batch = create(
        client,
        ws,
        batch_body(item("稿一"), item("稿二", avatar_id="male-003"), item("稿三")),
    )
    assert len(batch["item_ids"]) == 3
    assert [i["position"] for i in batch["items"]] == [0, 1, 2]
    assert [i["script_text"] for i in batch["items"]] == ["稿一", "稿二", "稿三"]
    assert batch["items"][1]["avatar_id"] == "male-003"
    assert {i["stage"] for i in batch["items"]} == {"talking"}
    assert batch["status_counts"] == {"pending": 3}
    assert batch["created_at"].endswith("Z")
    detail = client.get(base(ws) + f"/work-batches/{batch['id']}").json()
    assert detail["item_ids"] == batch["item_ids"]
    listed = client.get(base(ws) + "/work-batches").json()
    assert [b["id"] for b in listed] == [batch["id"]]
    one = client.get(base(ws) + f"/work-items/{batch['item_ids'][2]}").json()
    assert one["script_text"] == "稿三" and one["version"] == 1


def test_batch_request_is_idempotent_and_reuse_is_refused(video):
    client, _, ws, _, _ = video
    body = batch_body(item("稿一"), item("稿二"))
    first = create(client, ws, body)
    assert create(client, ws, body) == first
    changed = {**body, "items": [item("被改过的稿")]}
    reused = client.post(base(ws) + "/work-batches", json=changed)
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "VIDEO_REQUEST_REUSED"
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(VideoWorkBatchRecord)) == 1
        )
        assert (
            session.scalar(select(func.count()).select_from(VideoWorkItemRecord)) == 2
        )


def test_other_user_and_other_workspace_cannot_see_or_write(video):
    client, auth, ws, user, _ = video
    batch = create(client, ws, batch_body(item()))
    item_id = batch["item_ids"][0]
    auth.identity = verified_identity(
        primary_user_id="another-verified-user", email=EMAIL
    )
    other = client.get("/api/v1/me").json()["id"]
    with client.app.state.session_factory() as session:
        session.add(
            WorkspaceMemberRecord(
                workspace_id=ws, user_id=other, role="owner", status="active"
            )
        )
        session.commit()
    assert client.get(base(ws) + "/work-batches").json() == []
    assert client.get(base(ws) + "/work-items").json() == []
    assert client.get(base(ws) + f"/work-batches/{batch['id']}").status_code == 404
    assert client.get(base(ws) + f"/work-items/{item_id}").status_code == 404
    assert (
        patch(client, ws, item_id, expected_version=1, status="queued").status_code
        == 404
    )
    # Another user's generation task can't be attached to my item either.
    foreign_task = generation(client, ws, other)
    auth.identity = verified_identity(email=EMAIL)
    refused = patch(
        client, ws, item_id, expected_version=1, generation_task_id=foreign_task
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "VIDEO_WORK_REFERENCE_INVALID"

    ws2 = "ws_video_work_other"
    with client.app.state.session_factory() as session:
        session.add(
            WorkspaceRecord(
                id=ws2, name="其他工作区", created_by_user_id=user, status="active"
            )
        )
        session.flush()
        session.add(
            WorkspaceMemberRecord(
                workspace_id=ws2, user_id=user, role="owner", status="active"
            )
        )
        session.commit()
    assert client.get(base(ws2) + "/work-batches").json() == []
    assert client.get(base(ws2) + f"/work-items/{item_id}").status_code == 404
    with client.app.state.session_factory() as session:
        session.get(WorkspaceMemberRecord, (ws, user)).role = "viewer"
        session.commit()
    assert client.get(base(ws) + f"/work-items/{item_id}").status_code == 200
    assert (
        client.post(base(ws) + "/work-batches", json=batch_body(item())).status_code
        == 403
    )
    assert (
        patch(client, ws, item_id, expected_version=1, status="queued").status_code
        == 403
    )


def test_patch_uses_versions_and_retried_patch_is_answered(video):
    client, _, ws, user, _ = video
    item_id = create(client, ws, batch_body(item()))["item_ids"][0]
    task = generation(client, ws, user)
    first = patch(
        client,
        ws,
        item_id,
        expected_version=1,
        generation_task_id=task,
        status="queued",
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 2
    # Same request again (lost response): answered with the current row.
    again = patch(
        client,
        ws,
        item_id,
        expected_version=1,
        generation_task_id=task,
        status="queued",
    )
    assert again.status_code == 200 and again.json()["version"] == 2
    stale = patch(client, ws, item_id, expected_version=1, status="running")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VIDEO_WORK_ITEM_CONFLICT"
    assert client.get(base(ws) + f"/work-items/{item_id}").json()["status"] == "queued"


def test_failed_item_retries_alone_and_keeps_history(video):
    client, _, ws, user, _ = video
    batch = create(client, ws, batch_body(item("稿一"), item("稿二")))
    first_id, second_id = batch["item_ids"]
    old_task, ok_task = generation(client, ws, user), generation(client, ws, user)
    patch(
        client,
        ws,
        first_id,
        expected_version=1,
        generation_task_id=old_task,
        status="queued",
    )
    patch(
        client,
        ws,
        second_id,
        expected_version=1,
        generation_task_id=ok_task,
        status="queued",
    )
    failed = patch(
        client, ws, first_id, expected_version=2, status="failed", error="口型合成失败"
    )
    assert failed.json()["error"] == "口型合成失败"
    done = patch(client, ws, second_id, expected_version=2, status="succeeded")
    assert done.json()["status"] == "succeeded"
    new_task = generation(client, ws, user)
    retried = patch(
        client,
        ws,
        first_id,
        expected_version=3,
        generation_task_id=new_task,
        status="queued",
    )
    assert retried.status_code == 200, retried.text
    body = retried.json()
    assert body["generation_task_id"] == new_task
    assert body["history"] == {"generation": [old_task]}
    assert body["error"] is None and body["status"] == "queued"
    after = client.get(base(ws) + f"/work-batches/{batch['id']}").json()
    assert after["status_counts"] == {"queued": 1, "succeeded": 1}
    assert after["items"][1]["generation_task_id"] == ok_task


def test_list_filters_by_batch_stage_status_and_ids(video):
    client, _, ws, _, _ = video
    first = create(client, ws, batch_body(item("甲"), item("乙")))
    second = create(client, ws, batch_body(item("丙")))
    moved = patch(
        client, ws, first["item_ids"][1], expected_version=1, stage="finishing"
    )
    assert moved.status_code == 200
    by_batch = client.get(
        base(ws) + "/work-items", params={"batch_id": first["id"]}
    ).json()
    assert [i["script_text"] for i in by_batch] == ["甲", "乙"]
    finishing = client.get(
        base(ws) + "/work-items", params={"stage": "finishing"}
    ).json()
    assert [i["script_text"] for i in finishing] == ["乙"]
    both = client.get(
        base(ws) + "/work-items", params=[("stage", "talking"), ("stage", "finishing")]
    ).json()
    assert [i["script_text"] for i in both] == ["丙", "甲", "乙"]
    picked = client.get(
        base(ws) + "/work-items",
        params={"ids": f"{first['item_ids'][0]},{second['item_ids'][0]}"},
    ).json()
    assert sorted(i["script_text"] for i in picked) == ["丙", "甲"]
    assert (
        client.get(base(ws) + "/work-items", params={"stage": "bogus"}).status_code
        == 422
    )


def test_editing_upload_batch_and_field_validation(video):
    client, _, ws, _, _ = video
    upload = create(
        client,
        ws,
        batch_body(
            {
                "drive_mode": "uploaded_video",
                "source_video_ref": {"kind": "upload", "id": "src-1"},
            },
            source="editing_upload",
        ),
    )
    row = upload["items"][0]
    assert row["stage"] == "editing" and row["publish_title"] == ""
    assert row["source_video_ref"] == {"kind": "upload", "id": "src-1"}
    bad = [
        batch_body(item("")),
        batch_body({"drive_mode": "audio"}),
        batch_body(*[item(f"稿{i}") for i in range(21)]),
        batch_body(item(publish_title="长" * 81)),
        batch_body(item(), source="editing_upload"),
        batch_body(item(storage_key="x")),
        {"request_id": str(uuid4()), "items": []},
    ]
    for body in bad:
        assert client.post(base(ws) + "/work-batches", json=body).status_code == 422, (
            body
        )
    item_id = upload["item_ids"][0]
    for fields in (
        {"expected_version": 1},
        {"expected_version": 1, "stage": "published"},
        {"expected_version": 1, "status": None},
        {"expected_version": 1, "version": 9},
        {"expected_version": 1, "editing_task_id": "not-mine"},
    ):
        assert patch(client, ws, item_id, **fields).status_code == 422, fields


def _migration():
    spec = importlib.util.spec_from_file_location("work_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_round_trips_and_matches_models(video):
    client, _, ws, _, _ = video
    module = _migration()
    assert module.down_revision == "20261125_0053"
    engine = client.app.state.engine
    with engine.begin() as connection:
        VideoWorkItemRecord.__table__.drop(connection)
        VideoWorkBatchRecord.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.downgrade()
            module.upgrade()
    batch = create(client, ws, batch_body(item("迁移后")))
    assert batch["items"][0]["script_text"] == "迁移后"


def test_migration_compiles_for_postgres_without_destructive_sql():
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        _migration().upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE video_work_batches" in sql
    assert "CREATE TABLE video_work_items" in sql
    assert "JSONB" in sql
    assert "DROP" not in sql and "ALTER TABLE" not in sql.replace(
        "ALTER TABLE video_work", ""
    )


@pytest.mark.parametrize("path", ["/work-batches", "/work-items"])
def test_routes_require_video_access(video, path):
    client, auth, ws, _, _ = video
    auth.identity = None
    assert client.get(base(ws) + path).status_code in {401, 403}


def test_script_document_must_be_my_live_library_entry(video):
    client, auth, ws, _, _ = video
    entry = client.post(
        base(ws) + "/script-library",
        json={
            "request_id": str(uuid4()),
            "script": "文案库里的口播稿",
            "publish_title": "标题",
        },
    )
    assert entry.status_code == 200, entry.text
    entry_id = entry.json()["id"]
    ok = create(client, ws, batch_body(item(script_document_id=entry_id)))
    assert ok["items"][0]["script_document_id"] == entry_id
    unknown = client.post(
        base(ws) + "/work-batches", json=batch_body(item(script_document_id="nope"))
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "VIDEO_WORK_REFERENCE_INVALID"
    assert client.delete(base(ws) + f"/script-library/{entry_id}").status_code == 200
    deleted = client.post(
        base(ws) + "/work-batches", json=batch_body(item(script_document_id=entry_id))
    )
    assert deleted.status_code == 422
    auth.identity = verified_identity(primary_user_id="library-other", email=EMAIL)
    other = client.get("/api/v1/me").json()["id"]
    with client.app.state.session_factory() as session:
        session.add(
            WorkspaceMemberRecord(
                workspace_id=ws, user_id=other, role="owner", status="active"
            )
        )
        session.commit()
    mine = client.post(
        base(ws) + "/script-library",
        json={"request_id": str(uuid4()), "script": "别人的稿"},
    ).json()["id"]
    auth.identity = verified_identity(email=EMAIL)
    foreign = client.post(
        base(ws) + "/work-batches", json=batch_body(item(script_document_id=mine))
    )
    assert foreign.status_code == 422
