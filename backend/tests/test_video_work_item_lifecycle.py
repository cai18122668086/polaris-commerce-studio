"""我的作品：软删除（B1）、游标翻页与分组（B2）、已发布标记（C10）。"""

import importlib.util
import os
from datetime import timedelta
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, update
from sqlalchemy.engine import make_url

from app.main import create_app
from app.models import WorkspaceMemberRecord, utc_now
from app.video_cover_models import VideoCoverCandidateRecord
from app.video_work_models import VideoWorkBatchRecord, VideoWorkItemRecord
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_projects import EMAIL, base
from tests.test_video_work_items import batch_body, create, item, patch

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations/versions/20261128_0061_video_work_item_flags.py"
)


def _database_url(tmp_path):
    """SQLite by default; a fresh schema on PostgreSQL when
    POLARIS_TEST_DATABASE_URL points at a local test/CI database (CI PG job)."""
    raw = os.environ.get("POLARIS_TEST_DATABASE_URL")
    if not raw:
        yield None
        return
    url = make_url(raw)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not url.database
        or not any(token in url.database.lower() for token in ("test", "ci"))
    ):
        raise pytest.UsageError("requires a local test/CI database")
    schema = "work_items_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        yield url.update_query_dict(
            {"options": f"-csearch_path={schema}"}
        ).render_as_string(hide_password=False)
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def video(tmp_path):
    for database_url in _database_url(tmp_path):
        settings = external_settings(tmp_path)
        if database_url:
            settings = settings.model_copy(update={"database_url": database_url})
        auth = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
        with TestClient(create_app(settings, auth)) as client:
            user = client.get("/api/v1/me").json()["id"]
            ws = client.get("/api/v1/workspaces").json()[0]["id"]
            yield client, auth, ws, user, None
        client.app.state.engine.dispose()


def _set(client, item_id, **values):
    with client.app.state.session_factory() as session:
        session.execute(
            update(VideoWorkItemRecord)
            .where(VideoWorkItemRecord.id == item_id)
            .values(**values)
        )
        session.commit()


def _items(client, ws, **params):
    response = client.get(base(ws) + "/work-items", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _summary(client, ws):
    response = client.get(base(ws) + "/work-items/summary")
    assert response.status_code == 200, response.text
    return response.json()


def _as_other_user(client, auth, ws):
    auth.identity = verified_identity(primary_user_id="work-item-other", email=EMAIL)
    other = client.get("/api/v1/me").json()["id"]
    with client.app.state.session_factory() as session:
        if session.get(WorkspaceMemberRecord, (ws, other)) is None:
            session.add(
                WorkspaceMemberRecord(
                    workspace_id=ws, user_id=other, role="owner", status="active"
                )
            )
            session.commit()
    return other


# ---- B1 软删除 ----


def test_failed_item_is_soft_deleted_and_leaves_every_list(video):
    client, _, ws, _, _ = video
    batch = create(client, ws, batch_body(item("稿一"), item("稿二"), item("稿三")))
    failed, kept, done = batch["item_ids"]
    _set(client, failed, status="failed", error="口播没有生成成功")
    _set(client, done, stage="done", status="succeeded")
    assert _summary(client, ws) == {
        "total": 3,
        "active": 0,
        "failed": 1,
        "done": 1,
        "finishing": 0,
        "other": 1,
    }

    removed = client.delete(base(ws) + f"/work-items/{failed}")
    assert removed.status_code == 200, removed.text
    assert removed.json()["deleted_at"] is not None
    assert removed.json()["version"] == 2
    # Repeating the delete answers the deleted row (idempotent).
    again = client.delete(base(ws) + f"/work-items/{failed}")
    assert again.status_code == 200 and again.json()["version"] == 2

    assert [row["id"] for row in _items(client, ws)] == [kept, done]
    assert _items(client, ws, ids=f"{failed},{kept}")[0]["id"] == kept
    assert len(_items(client, ws, ids=failed)) == 0
    assert _summary(client, ws)["total"] == 2
    assert _summary(client, ws)["failed"] == 0
    # The batch is not deleted and still knows the item; the row is kept.
    whole = client.get(base(ws) + f"/work-batches/{batch['id']}").json()
    assert whole["item_ids"] == batch["item_ids"]
    assert whole["items"][0]["deleted_at"] is not None
    assert client.get(base(ws) + f"/work-items/{failed}").status_code == 200
    # A deleted item can't be edited or regenerated any more.
    assert (
        patch(
            client, ws, failed, expected_version=2, publish_title="新标题"
        ).status_code
        == 404
    )
    retry = client.post(base(ws) + f"/work-items/{failed}/talking-retry")
    assert retry.status_code == 404


def test_items_still_generating_or_editing_cannot_be_deleted(video):
    client, _, ws, user, _ = video
    batch = create(
        client,
        ws,
        batch_body(item("排队"), item("生成中"), item("剪辑中"), item("做封面")),
    )
    queued, running, editing, covering = batch["item_ids"]
    _set(client, queued, status="queued")
    _set(client, running, status="running")
    _set(client, editing, stage="editing", status="running")
    _set(client, covering, stage="finishing", status="pending")
    with client.app.state.session_factory() as session:
        session.add(
            VideoCoverCandidateRecord(
                id=str(uuid4()),
                workspace_id=ws,
                owner_user_id=user,
                request_id=str(uuid4()),
                request_hash="0" * 64,
                slot=1,
                work_item_id=covering,
                source_kind="editing",
                source_id=str(uuid4()),
                platform="douyin",
                cover_text="封面",
                background="ai",
                status="running",
                params={},
                checks={},
                files={},
                receipt={},
            )
        )
        session.commit()
    for item_id in (queued, running, editing, covering):
        refused = client.delete(base(ws) + f"/work-items/{item_id}")
        assert refused.status_code == 409, item_id
        assert refused.json()["error"]["code"] == "VIDEO_WORK_ITEM_BUSY"
    assert len(_items(client, ws)) == 4
    # Once the work is over the same items can go.
    _set(client, running, status="failed")
    assert client.delete(base(ws) + f"/work-items/{running}").status_code == 200
    assert _summary(client, ws)["active"] == 2


def test_other_users_item_cannot_be_deleted(video):
    client, auth, ws, _, _ = video
    mine = create(client, ws, batch_body(item("我的稿")))["item_ids"][0]
    _set(client, mine, status="failed")
    _as_other_user(client, auth, ws)
    assert client.delete(base(ws) + f"/work-items/{mine}").status_code == 404
    assert _summary(client, ws)["total"] == 0
    auth.identity = verified_identity(email=EMAIL)
    assert [row["id"] for row in _items(client, ws)] == [mine]
    assert _items(client, ws)[0]["deleted_at"] is None


def test_deleted_pending_item_is_not_queued_by_a_later_submit(video):
    client, _, ws, _, _ = video
    batch = create(client, ws, batch_body(item("稿一"), item("稿二")))
    first, second = batch["item_ids"]
    assert client.delete(base(ws) + f"/work-items/{first}").status_code == 200
    from app import video_work_talking as talking

    with client.app.state.session_factory() as session:
        rows = [session.get(VideoWorkItemRecord, i) for i in (first, second)]
        talking.confirm(session, client.app.state.settings, ws, rows)
        assert session.get(VideoWorkItemRecord, first).status == "pending"
        assert session.get(VideoWorkItemRecord, second).status == "queued"


# ---- B2 游标翻页 + 分组 ----


def _make_items(client, ws, total):
    ids = []
    while len(ids) < total:
        count = min(20, total - len(ids))
        batch = create(
            client, ws, batch_body(*[item(f"稿{len(ids) + n}") for n in range(count)])
        )
        ids.extend(batch["item_ids"])
    return ids


def _expected_order(client, ws):
    with client.app.state.session_factory() as session:
        rows = session.query(VideoWorkItemRecord).filter_by(workspace_id=ws).all()
        return [
            row.id
            for row in sorted(
                rows,
                key=lambda row: (
                    -row.created_at.timestamp(),
                    row.batch_id,
                    row.position,
                ),
            )
            if row.deleted_at is None
        ]


def _walk(client, ws, limit, **params):
    seen, after, pages = [], None, 0
    while True:
        page = _items(
            client, ws, limit=limit, **params, **({"after": after} if after else {})
        )
        pages += 1
        seen.extend(row["id"] for row in page)
        if len(page) < limit:
            return seen, pages
        after = page[-1]["id"]


def test_cursor_pages_through_250_items_without_gaps_or_repeats(video):
    client, _, ws, _, _ = video
    ids = _make_items(client, ws, 250)
    # Several batches sharing one timestamp: ties fall back to batch_id, position.
    same = utc_now() - timedelta(days=3)
    with client.app.state.session_factory() as session:
        batch_ids = list(
            dict.fromkeys(
                session.get(VideoWorkItemRecord, item_id).batch_id for item_id in ids
            )
        )
        for batch_id in batch_ids[2:6]:
            session.execute(
                update(VideoWorkItemRecord)
                .where(VideoWorkItemRecord.batch_id == batch_id)
                .values(created_at=same)
            )
            session.execute(
                update(VideoWorkBatchRecord)
                .where(VideoWorkBatchRecord.id == batch_id)
                .values(created_at=same)
            )
        session.commit()
    expected = _expected_order(client, ws)
    assert len(expected) == 250 and set(expected) == set(ids)
    for limit in (50, 7, 200):
        seen, pages = _walk(client, ws, limit)
        assert seen == expected, limit
        assert len(seen) == len(set(seen)) == 250
    seen, pages = _walk(client, ws, 50)
    assert pages == 6  # 5 full pages + the empty end page
    # The oldest item is reachable and complete (title/body intact).
    oldest = _items(client, ws, ids=expected[-1])[0]
    assert oldest["publish_title"] and oldest["publish_body"]

    # Deleting the last row of a page does not break the next page.
    first_page = _items(client, ws, limit=50)
    anchor = first_page[-1]["id"]
    _set(client, anchor, status="failed")
    assert client.delete(base(ws) + f"/work-items/{anchor}").status_code == 200
    next_page = _items(client, ws, limit=50, after=anchor)
    assert [row["id"] for row in next_page] == expected[50:100]

    # Inside one batch: by position.
    batch_id = batch_ids[0]
    whole = [row["id"] for row in _items(client, ws, batch_id=batch_id, limit=200)]
    part = _items(client, ws, batch_id=batch_id, limit=8)
    rest = _items(client, ws, batch_id=batch_id, limit=200, after=part[-1]["id"])
    assert [row["id"] for row in part + rest] == whole


def test_completed_only_is_filtered_on_the_server(video):
    client, _, ws, _, _ = video
    ids = _make_items(client, ws, 60)
    done = ids[::3]
    for item_id in done:
        _set(client, item_id, stage="done", status="succeeded")
    for item_id in ids[1::3][:5]:
        _set(client, item_id, status="failed")
    for item_id in ids[2::3][:4]:
        _set(client, item_id, stage="finishing", status="pending")
    expected = [i for i in _expected_order(client, ws) if i in set(done)]
    seen, _ = _walk(client, ws, 6, group="done")
    assert seen == expected and len(seen) == 20
    both = _items(client, ws, group=["done", "finishing"], limit=200)
    assert len(both) == 24
    summary = _summary(client, ws)
    assert summary == {
        "total": 60,
        "active": 0,
        "failed": 5,
        "done": 20,
        "finishing": 4,
        "other": 31,
    }
    for name in ("active", "failed", "done", "finishing", "other"):
        assert len(_items(client, ws, group=name, limit=200)) == summary[name]


def test_invalid_or_foreign_cursor_is_refused(video):
    client, auth, ws, _, _ = video
    mine = create(client, ws, batch_body(item()))["item_ids"][0]
    bad = client.get(base(ws) + "/work-items", params={"after": "nope"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "VIDEO_WORK_CURSOR_INVALID"
    _as_other_user(client, auth, ws)
    foreign = client.get(base(ws) + "/work-items", params={"after": mine})
    assert foreign.status_code == 422


# ---- C10 已发布标记 ----


def test_published_mark_is_the_only_new_writable_field(video):
    client, _, ws, _, _ = video
    item_id = create(client, ws, batch_body(item()))["item_ids"][0]
    _set(client, item_id, stage="done", status="succeeded")
    marked = patch(client, ws, item_id, expected_version=1, published=True)
    assert marked.status_code == 200, marked.text
    stamp = marked.json()["published_at"]
    assert stamp and marked.json()["version"] == 2
    # A retried mark (old version) is answered with the same row and time.
    retried = patch(client, ws, item_id, expected_version=1, published=True)
    assert retried.status_code == 200 and retried.json()["published_at"] == stamp
    # Marking again keeps the first time.
    again = patch(client, ws, item_id, expected_version=2, published=True)
    assert again.json()["published_at"] == stamp
    cleared = patch(
        client, ws, item_id, expected_version=again.json()["version"], published=False
    )
    assert cleared.status_code == 200 and cleared.json()["published_at"] is None
    # The timestamp itself is not writable, and null is not a value for the mark.
    raw = patch(
        client,
        ws,
        item_id,
        expected_version=cleared.json()["version"],
        published_at="2026-01-01T00:00:00Z",
    )
    assert raw.status_code == 422
    empty = patch(
        client, ws, item_id, expected_version=cleared.json()["version"], published=None
    )
    assert empty.status_code == 422
    assert _items(client, ws)[0]["published_at"] is None


# ---- 迁移 0061 ----


def _migration():
    spec = importlib.util.spec_from_file_location("work_flags_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flags_migration_round_trips(video):
    client, _, ws, _, _ = video
    module = _migration()
    assert module.down_revision == "20261128_m0060w3"
    engine = client.app.state.engine
    with (
        engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        module.downgrade()
        module.upgrade()
    item_id = create(client, ws, batch_body(item("迁移后")))["item_ids"][0]
    _set(client, item_id, status="failed")
    assert client.delete(base(ws) + f"/work-items/{item_id}").status_code == 200


def test_flags_migration_is_additive_on_postgres():
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        _migration().upgrade()
    sql = output.getvalue()
    assert "ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE" in sql
    assert "ADD COLUMN published_at TIMESTAMP WITH TIME ZONE" in sql
    assert "DROP" not in sql
