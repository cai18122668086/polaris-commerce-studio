import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import SecretStr

from app.models import WorkspaceMemberRecord
from app.video_editing_models import VideoEditingHandoffRecord
from tests.test_video_generation import request_body

pytest_plugins = ["tests.test_video_generation"]


def complete_and_grant(client, root, pid):
    client.app.state.settings.video_editing_handoff_secret = SecretStr("x" * 48)
    job = client.post(root + "/generation-tasks", json=request_body(pid)).json()
    path = root + f"/generation-tasks/{job['id']}/editing-handoffs"
    body = {"request_id": str(uuid4()), "expires_in_seconds": 3600}
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    return path, body, response.json()


def test_handoff_grant_replay_scope_expiry_and_revocation(video_gen):
    client, _, _, root, pid, _ = video_gen
    path, body, grant = complete_and_grant(client, root, pid)
    assert client.post(path, json=body).json() == grant
    assert client.post(path, json={**body, "expires_in_seconds": 60}).status_code == 409
    headers = {"Authorization": "Bearer " + grant["access_token"]}
    assert client.get(grant["manifest_url"]).status_code == 401
    assert (
        client.get(
            grant["manifest_url"], headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    result = client.get(grant["manifest_url"], headers=headers)
    assert result.status_code == 200, result.text
    manifest = result.json()
    assert "access_token" not in result.text and "local_path" not in result.text
    assert manifest["subtitles"]["status"] == "pending_alignment"
    for kind in ["audio", "video"]:
        content = client.get(manifest["assets"][kind], headers=headers)
        assert content.status_code == 200
        assert (
            hashlib.sha256(content.content).hexdigest()
            == manifest[kind + "_format"]["sha256"]
        )
    assert (
        client.get(manifest["assets"]["script"], headers=headers).text
        == client.get(root + "/generation-tasks").json()[0]["snapshot"]["draft"]["text"]
    )
    assert client.post(path + "/" + grant["id"] + "/revoke").status_code == 200
    assert client.get(grant["manifest_url"], headers=headers).status_code == 401
    _, _, another = complete_and_grant(client, root, pid)
    assert client.get(another["manifest_url"], headers=headers).status_code == 401
    with client.app.state.session_factory() as session:
        row = session.get(VideoEditingHandoffRecord, another["id"])
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert (
        client.get(
            another["manifest_url"],
            headers={"Authorization": "Bearer " + another["access_token"]},
        ).status_code
        == 401
    )


def test_editing_callbacks_deduplicate_check_order_and_bind_exact_confirmed_script(
    video_gen,
):
    client, _, provider, root, pid, _ = video_gen
    _, _, grant = complete_and_grant(client, root, pid)
    posts_before = len(provider.posts)
    headers = {"Authorization": "Bearer " + grant["access_token"]}
    manifest = client.get(grant["manifest_url"], headers=headers).json()
    event = {
        "event_id": str(uuid4()),
        "sequence": 1,
        "status": "accepted",
        "service_task_id": "editor-123",
    }
    assert (
        client.post(grant["events_url"], json=event, headers=headers).status_code == 200
    )
    assert (
        client.post(grant["events_url"], json=event, headers=headers).json()["revision"]
        == 1
    )
    assert (
        client.post(
            grant["events_url"], json={**event, "status": "aligning"}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.post(
            grant["events_url"],
            json={**event, "event_id": str(uuid4()), "sequence": 3},
            headers=headers,
        ).status_code
        == 409
    )
    result = {
        "event_id": str(uuid4()),
        "sequence": 2,
        "status": "result_ready",
        "service_task_id": "editor-123",
        "result_reference": "editor-object-456",
        "script_sha256": "0" * 64,
    }
    assert (
        client.post(
            grant["events_url"],
            json={**result, "service_task_id": "another-editor"},
            headers=headers,
        ).status_code
        == 409
    )
    assert (
        client.post(grant["events_url"], json=result, headers=headers).status_code
        == 422
    )
    result["script_sha256"] = manifest["script_sha256"]
    response = client.post(grant["events_url"], json=result, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "result_ready"
    assert len(provider.posts) == posts_before
    assert (
        client.post(
            grant["events_url"],
            json={
                **event,
                "event_id": str(uuid4()),
                "sequence": 3,
                "status": "editing",
            },
            headers=headers,
        ).status_code
        == 409
    )


def test_parent_permission_revocation_invalidates_grant(video_gen):
    client, _, _, root, pid, user = video_gen
    _, _, grant = complete_and_grant(client, root, pid)
    with client.app.state.session_factory() as session:
        row = session.get(VideoEditingHandoffRecord, grant["id"])
        member = session.get(WorkspaceMemberRecord, (row.workspace_id, user))
        member.status = "suspended"
        session.commit()
    assert (
        client.get(
            grant["manifest_url"],
            headers={"Authorization": "Bearer " + grant["access_token"]},
        ).status_code
        == 401
    )
