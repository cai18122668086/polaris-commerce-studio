import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import UserRecord, WorkspaceMemberRecord, WorkspaceRecord
from app.video_studio_models import (
    VideoMutationRecord,
    VideoProjectRecord,
    VideoScriptVersionRecord,
    VideoTaskRecord,
)
from app.video_studio_schemas import VideoProjectContent
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)

EMAIL = "1474953130@qq.com"


@pytest.fixture
def video(tmp_path):
    auth = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
    settings = external_settings(tmp_path)
    with TestClient(create_app(settings, auth)) as client:
        user = client.get("/api/v1/me").json()["id"]
        ws = client.get("/api/v1/workspaces").json()[0]["id"]
        yield client, auth, ws, user, settings


def base(ws):
    return f"/api/v1/video-studio/workspaces/{ws}"


def payload(text="产品介绍", revision=0, action="save"):
    content = VideoProjectContent().model_dump(mode="json")
    content["draft"].update(name="演示产品", text=text, voiceId="warm")
    content["product_facts"] = "不含香精；实际价格以产品资料为准"
    content["references"] = [
        {
            "id": str(uuid4()),
            "kind": "url",
            "url": "https://example.com/reference",
            "original_text": "参考口播原文",
            "note": "用户提供，尚未采集",
        }
    ]
    content["media"] = [
        {
            "id": str(uuid4()),
            "kind": "audio",
            "name": "sample.wav",
            "mime_type": "audio/wav",
            "size_bytes": 1200,
            "availability": "local_only",
        }
    ]
    return {
        "request_id": str(uuid4()),
        "expected_revision": revision,
        "content": content,
        "action": action,
    }


def put(client, ws, pid, body):
    response = client.put(base(ws) + f"/projects/{pid}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_project_version_confirmation_and_task_survive_new_app(video):
    client, auth, ws, user, settings = video
    pid = str(uuid4())
    first = put(client, ws, pid, payload())
    library = put(client, ws, pid, payload("确认前文案", 1, "library"))
    confirmed = put(client, ws, pid, payload("最终确认稿", 2, "demo"))
    put(client, ws, pid, payload("继续编辑的新草稿", 3))
    assert first["project"]["revision"] == 1
    assert library["version"]["kind"] == "library"
    assert confirmed["task"]["confirmed_version_id"] == confirmed["version"]["id"]
    with TestClient(
        create_app(
            settings, FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
        )
    ) as device:
        project = device.get(base(ws) + f"/projects/{pid}").json()
        assert project["content"]["draft"]["text"] == "继续编辑的新草稿"
        assert project["content"]["product_facts"]
        assert project["content"]["references"][0]["original_text"] == "参考口播原文"
        assert project["content"]["media"][0]["availability"] == "local_only"
        assert project["created_at"].endswith("Z")
        assert project["updated_at"].endswith("Z")
        versions = device.get(
            base(ws) + "/versions", params={"project_id": pid, "kind": "draft"}
        ).json()
        assert len(versions) == 4
        task = device.get(base(ws) + "/tasks").json()[0]
        assert task["snapshot"]["draft"]["text"] == "最终确认稿"
        assert task["status"] == "demo"
        assert device.patch(
            base(ws) + "/versions/" + task["confirmed_version_id"],
            json={"text": "伪造"},
        ).status_code in {404, 405}


def test_retries_are_idempotent_and_stale_device_cannot_overwrite(video):
    client, _, ws, _, _ = video
    pid, body = str(uuid4()), payload(action="demo")
    first = put(client, ws, pid, body)
    assert put(client, ws, pid, body) == first
    changed = {**body, "action": "library"}
    assert client.put(base(ws) + f"/projects/{pid}", json=changed).status_code == 409
    put(client, ws, pid, payload("另一设备的新内容", 1))
    stale = client.put(base(ws) + f"/projects/{pid}", json=payload("旧设备覆盖", 1))
    assert stale.status_code == 409
    assert (
        client.get(base(ws) + f"/projects/{pid}").json()["content"]["draft"]["text"]
        == "另一设备的新内容"
    )
    assert len(client.get(base(ws) + "/tasks").json()) == 1


def test_concurrent_writers_have_one_winner(video):
    client, _, ws, _, _ = video
    pid = str(uuid4())
    put(client, ws, pid, payload())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda text: client.put(
                    base(ws) + f"/projects/{pid}", json=payload(text, 1)
                ),
                ["设备A", "设备B"],
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    assert client.get(base(ws) + f"/projects/{pid}").json()["revision"] == 2


def test_user_and_workspace_are_both_required_and_viewer_cannot_write(video):
    client, auth, ws, user, _ = video
    pid = str(uuid4())
    put(client, ws, pid, payload(action="demo"))
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
    for endpoint in ["projects", "versions", "tasks"]:
        assert client.get(base(ws) + "/" + endpoint).json() == []
    assert client.get(base(ws) + f"/projects/{pid}").status_code == 404
    assert (
        client.put(base(ws) + f"/projects/{pid}", json=payload(revision=1)).status_code
        == 404
    )
    auth.identity = verified_identity(email=EMAIL)
    ws2 = "ws_video_other"
    with client.app.state.session_factory() as session:
        session.add(
            WorkspaceRecord(
                id=ws2, name="Other workspace", created_by_user_id=user, status="active"
            )
        )
        session.flush()
        session.add(
            WorkspaceMemberRecord(
                workspace_id=ws2, user_id=user, role="owner", status="active"
            )
        )
        session.commit()
    assert client.get(base(ws2) + "/projects").json() == []
    assert client.get(base(ws2) + f"/projects/{pid}").status_code == 404
    assert (
        client.put(base(ws2) + f"/projects/{pid}", json=payload(revision=1)).status_code
        == 404
    )
    with client.app.state.session_factory() as session:
        session.get(WorkspaceMemberRecord, (ws, user)).role = "viewer"
        session.commit()
    assert client.get(base(ws) + f"/projects/{pid}").status_code == 200
    assert (
        client.put(base(ws) + f"/projects/{pid}", json=payload(revision=1)).status_code
        == 403
    )


@pytest.mark.parametrize("identity", [None, "ordinary", "unverified"])
def test_every_business_route_keeps_gray_gate_and_ignores_spoofed_headers(
    video, identity
):
    client, auth, ws, _, _ = video
    from app.supertokens_auth import ExternalIdentity

    auth.identity = (
        None
        if identity is None
        else (
            ExternalIdentity("unverified", "unverified", EMAIL, False)
            if identity == "unverified"
            else verified_identity(email="ordinary@example.com")
        )
    )
    expected = 401 if identity is None else 403 if identity == "unverified" else 404
    headers = {
        "X-User-Id": EMAIL,
        "X-User-Email": EMAIL,
        "X-Video-Studio-Allowed": "true",
    }
    for endpoint in ["projects", "versions", "tasks", f"projects/{uuid4()}"]:
        response = client.get(
            base(ws) + "/" + endpoint + "?allowed=true", headers=headers
        )
        assert response.status_code == expected
        assert EMAIL not in response.text
        assert "no-store" in response.headers["cache-control"]
    assert (
        client.put(
            base(ws) + f"/projects/{uuid4()}", json=payload(), headers=headers
        ).status_code
        == expected
    )
    assert (
        client.post(
            base(ws) + "/imports/legacy",
            json={"request_id": str(uuid4()), "draft": {}},
            headers=headers,
        ).status_code
        == expected
    )


def test_removed_membership_and_unknown_workspace_fail_closed(video):
    client, _, ws, user, _ = video
    with client.app.state.session_factory() as session:
        session.get(WorkspaceMemberRecord, (ws, user)).status = "inactive"
        session.commit()
    assert client.get(base(ws) + "/projects").status_code == 404
    assert (
        client.put(base("unknown") + f"/projects/{uuid4()}", json=payload()).status_code
        == 404
    )


@pytest.mark.parametrize("invalid", ["owner", "storage", "url", "length", "status"])
def test_content_validation_rejects_trust_and_storage_injection(video, invalid):
    client, _, ws, _, _ = video
    body = payload()
    if invalid == "owner":
        body["owner_user_id"] = "someone-else"
    if invalid == "storage":
        body["content"]["media"][0]["storage_key"] = "another/users/file.mp4"
    if invalid == "url":
        body["content"]["references"][0]["url"] = "javascript:alert(1)"
    if invalid == "length":
        body["content"]["draft"]["text"] = "x" * 3001
    if invalid == "status":
        body["status"] = "succeeded"
    assert client.put(base(ws) + f"/projects/{uuid4()}", json=body).status_code == 422
    assert client.get(base(ws) + "/projects").json() == []


def test_legacy_import_is_transactional_and_idempotent(video):
    client, _, ws, _, _ = video
    draft = payload()["content"]["draft"]
    body = {
        "request_id": str(uuid4()),
        "draft": draft,
        "copies": [
            {
                "id": "legacy-copy",
                "title": "旧文案",
                "text": "保存的旧文案",
                "date": "2026-11-01",
            }
        ],
        "works": [
            {
                "id": "legacy-work",
                "draft": {**draft, "text": "旧演示确认稿"},
                "date": "2026-11-01",
            }
        ],
    }
    first = client.post(base(ws) + "/imports/legacy", json=body)
    assert first.status_code == 200, first.text
    assert client.post(base(ws) + "/imports/legacy", json=body).json() == first.json()
    assert len(client.get(base(ws) + "/projects").json()) == 1
    assert (
        client.get(base(ws) + "/versions").json()[0]["snapshot"]["draft"]["text"]
        == "保存的旧文案"
    )
    assert (
        client.get(base(ws) + "/tasks").json()[0]["snapshot"]["draft"]["text"]
        == "旧演示确认稿"
    )


def test_migration_adds_only_video_tables_and_preserves_users(video):
    client, _, ws, user, _ = video
    tables = [
        VideoMutationRecord.__table__,
        VideoTaskRecord.__table__,
        VideoScriptVersionRecord.__table__,
        VideoProjectRecord.__table__,
    ]
    engine = client.app.state.engine
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261104_0035_video_projects.py"
    )
    spec = importlib.util.spec_from_file_location("video_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        for table in tables:
            table.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
    with client.app.state.session_factory() as session:
        assert session.get(UserRecord, user) is not None
        assert session.scalar(select(func.count()).select_from(VideoProjectRecord)) == 0

    assert (
        put(client, ws, str(uuid4()), payload(action="demo"))["task"]["status"]
        == "demo"
    )


def test_video_migration_compiles_for_postgres_without_destructive_sql():
    from io import StringIO

    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261104_0035_video_projects.py"
    )
    spec = importlib.util.spec_from_file_location("video_pg_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "JSONB" in sql
    assert "CREATE TABLE video_projects" in sql
    assert "DROP" not in sql
    assert "UPDATE users" not in sql


def test_concurrent_identical_request_replays_one_demo(video):
    client, _, ws, _, _ = video
    pid, body = str(uuid4()), payload(action="demo")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: client.put(base(ws) + f"/projects/{pid}", json=body), range(2)
            )
        )
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json() == results[1].json()
    assert len(client.get(base(ws) + "/tasks").json()) == 1
