import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import video_writing_routes
from app.main import create_app
from app.video_assistance_models import VideoAssistanceRecord
from app.video_assistance_provider import VideoAssistanceProvider
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_projects import EMAIL, payload

POST_A = "7635624004494435825"
POST_B = "7635624004494435826"
POST_C = "7635624004494435827"
CURSOR = "fixture-private-page-token"
SIGNED_URL = "https://media.invalid/clip.mp4?signature=fixture-private"


def item(post_id, **changes):
    return {
        "id": post_id,
        "url": f"https://www.douyin.com/video/{post_id}?tracking=test",
        "text": "这是发布描述",
        "media_type": "video",
        "video_url": SIGNED_URL,
        "posted_at": "2026-11-01T09:00:00+08:00",
        "duration_sec": 24,
        "like_count": 20,
        "collect_count": 4,
        "share_count": 0,
        "view_count": 0,
        "author_id": "fixture-author",
        **changes,
    }


@pytest.fixture
def benchmark(tmp_path):
    auth = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
    settings = external_settings(tmp_path).model_copy(
        update={
            "video_benchmark_search_enabled": True,
            "video_extract_enabled": True,
            "video_extract_api_key": SecretStr("local-fixture"),
        }
    )
    calls = []
    pages = {
        "": httpx.Response(
            200,
            json={
                "id": "receipt-1",
                "results": [
                    item(POST_A),
                    item(POST_A),
                    item(POST_B, media_type="image"),
                    item(POST_B, duration_sec=301),
                    item(POST_B, url=["malformed"]),
                    item(POST_B, url="https://elsewhere.invalid/video/" + POST_B),
                    item(POST_B, url="https://www.douyin.com/video/" + POST_C),
                ],
                "next_page_token": CURSOR,
                "billing": {
                    "charged": True,
                    "charged_usd": 0.00833,
                    "balance_after_usd": 8,
                },
            },
        ),
        CURSOR: httpx.Response(
            200,
            json={
                "results": [
                    item(POST_A),
                    item(POST_B, like_count=None, collect_count=None, author_id=None),
                    item(POST_C, like_count=0, duration_sec=None, posted_at="昨天"),
                ],
            },
        ),
    }

    def send(request):
        assert request.method == "POST"
        assert str(request.url) == "https://api.everyinfra.com/api/v1/social"
        body = json.loads(request.content)
        calls.append(body)
        if body["action"] == "search":
            return pages[body["params"]["page_token"]]
        assert body["action"] == "transcript"
        post_id = body["params"]["url"].rsplit("/", 1)[-1]
        text = "这是语音提取的独立原文。" if post_id == POST_A else ""
        return httpx.Response(200, json={"results": {"text": text}})

    app = create_app(settings, auth)
    app.state.video_assistance_provider = VideoAssistanceProvider(
        settings,
        httpx.MockTransport(send),
    )
    with TestClient(app) as client:
        workspace_id = client.get("/api/v1/workspaces").json()[0]["id"]
        root = f"/api/v1/video-studio/workspaces/{workspace_id}"
        project_id = str(uuid4())
        assert (
            client.put(root + "/projects/" + project_id, json=payload()).status_code
            == 200
        )
        body = {
            "request_id": str(uuid4()),
            "project_id": project_id,
            "expected_revision": 1,
            "keyword": "  厨房清洁  ",
            "sort": "most_liked",
            "publish_time": "one_week",
        }
        yield client, auth, root, body, calls, pages


def result_rows(client, root, body):
    response = client.get(
        root + "/assistance-tasks", params={"project_id": body["project_id"]}
    )
    assert response.status_code == 200
    assert CURSOR not in response.text and SIGNED_URL not in response.text
    assert "charged_usd" not in response.text
    return {row["id"]: row for row in response.json()}


def test_search_pages_are_separately_submitted_deduplicated_and_private(benchmark):
    client, _, root, body, calls, _ = benchmark
    assert client.get(root + "/benchmark-config").json() == {
        "enabled": True,
        "can_extract": True,
        "can_save_reference": False,
    }
    before = client.get(root + "/projects/" + body["project_id"]).json()
    initial = client.post(root + "/benchmark-searches", json=body)
    assert initial.status_code == 200, initial.text
    first_id = initial.json()["id"]
    assert client.post(root + "/benchmark-searches", json=body).json()["id"] == first_id
    assert (
        client.post(
            root + "/benchmark-searches", json={**body, "keyword": "别的"}
        ).status_code
        == 409
    )
    assert len(calls) == 1
    first = result_rows(client, root, body)[first_id]
    assert first["status"] == "completed" and first["receipt"] == {}
    page = first["result"]
    assert (page["received_count"], page["duplicate_count"], page["skipped_count"]) == (
        7,
        1,
        5,
    )
    assert page["has_more"] and page["root_task_id"] == first_id
    assert page["author_count"] == page["top_author_item_count"] == 1
    (row,) = page["items"]
    assert row["platform_id"] == POST_A
    assert row["source_url"] == "https://www.douyin.com/video/" + POST_A
    assert row["description"] == "这是发布描述" and "text" not in row
    assert row["posted_at"] == "2026-11-01T01:00:00+00:00"
    assert row["collect_like_ratio"] == 0.2 and row["share_like_ratio"] == 0
    assert row["comment_count"] is None and "view_count" not in row
    assert row["media_status"] == "link_reported"
    with client.app.state.session_factory() as db:
        receipt = db.get(VideoAssistanceRecord, first_id).receipt
        assert receipt["original_rows"][0]["view_count"] == 0
        assert receipt["next_page_token"] == CURSOR and SIGNED_URL not in str(receipt)
        assert receipt["billing"]["charged"] is True

    route = root + f"/benchmark-searches/{first_id}/next"
    next_response = client.post(route)
    assert next_response.status_code == 200, next_response.text
    next_id = next_response.json()["id"]
    assert client.post(route).json()["id"] == next_id
    assert len(calls) == 2
    assert calls[0] == {
        "platform": "douyin",
        "action": "search",
        "params": {
            "keyword": "厨房清洁",
            "page_token": "",
            "sort": "most_liked",
            "publish_time": "one_week",
            "limit": 10,
        },
    }
    assert calls[1] == {
        **calls[0],
        "params": {**calls[0]["params"], "page_token": CURSOR},
    }
    page = result_rows(client, root, body)[next_id]["result"]
    assert page["previous_task_id"] == first_id and page["page"] == 2
    assert page["duplicate_count"] == 1 and not page["has_more"]
    assert page["unknown_author_count"] == 1
    missing, zero = page["items"]
    assert missing["collect_like_ratio"] is None and missing["like_count"] is None
    assert zero["like_count"] == 0 and zero["collect_like_ratio"] is None
    assert zero["posted_at"] is None and zero["duration_seconds"] is None
    assert client.post(root + f"/benchmark-searches/{next_id}/next").status_code == 409
    assert client.get(root + "/projects/" + body["project_id"]).json() == before


def test_search_disabled_stale_and_unknown_requests_do_not_repeat(benchmark):
    client, _, root, body, calls, pages = benchmark
    settings = client.app.state.settings
    settings.video_benchmark_search_enabled = False
    assert client.get(root + "/benchmark-config").json()["enabled"] is False
    assert client.post(root + "/benchmark-searches", json=body).status_code == 503
    settings.video_benchmark_search_enabled = True
    assert (
        client.post(
            root + "/benchmark-searches", json={**body, "expected_revision": 2}
        ).status_code
        == 409
    )
    assert not calls
    pages[""] = httpx.Response(504)
    task_id = client.post(root + "/benchmark-searches", json=body).json()["id"]
    assert result_rows(client, root, body)[task_id]["status"] == "unknown"
    assert client.post(root + f"/assistance-tasks/{task_id}/resume").status_code == 409
    assert client.post(root + f"/benchmark-searches/{task_id}/next").status_code == 409
    assert client.post(root + "/benchmark-searches", json=body).json()["id"] == task_id
    assert len(calls) == 1


def test_search_expired_page_and_unowned_project(benchmark):
    client, auth, root, body, calls, _ = benchmark
    task_id = client.post(root + "/benchmark-searches", json=body).json()["id"]
    with client.app.state.session_factory() as db:
        task = db.get(VideoAssistanceRecord, task_id)
        task.result = {
            **task.result,
            "next_page_expires_at": (
                datetime.now(UTC) - timedelta(seconds=1)
            ).isoformat(),
        }
        db.commit()
    route = root + f"/benchmark-searches/{task_id}/next"
    assert client.post(route).json()["error"]["code"] == "VIDEO_BENCHMARK_PAGE_EXPIRED"
    auth.identity = verified_identity(email="ordinary@example.com")
    assert client.post(route).status_code in {403, 404}
    assert client.post(root + "/benchmark-searches", json=body).status_code in {
        403,
        404,
    }
    assert len(calls) == 1


def test_batch_extraction_is_scoped_idempotent_and_keeps_separate_reference(
    benchmark, monkeypatch
):
    client, _, root, body, calls, _ = benchmark
    before = client.get(root + "/projects/" + body["project_id"]).json()
    first = (
        client.post(root + "/benchmark-searches", json=body).raise_for_status().json()
    )
    second = (
        client.post(root + f"/benchmark-searches/{first['id']}/next")
        .raise_for_status()
        .json()
    )
    first_pick = {"search_task_id": first["id"], "platform_id": POST_A}
    second_pick = {"search_task_id": second["id"], "platform_id": POST_B}
    batch = {
        "project_id": body["project_id"],
        "expected_revision": 1,
        "items": [first_pick, second_pick],
    }
    route = root + "/benchmark-extractions"
    assert (
        client.post(
            route, json={**batch, "items": [first_pick, first_pick]}
        ).status_code
        == 422
    )
    assert (
        client.post(
            route,
            json={
                **batch,
                "items": [first_pick, {**first_pick, "platform_id": POST_B}],
            },
        ).status_code
        == 404
    )
    other_project = str(uuid4())
    assert (
        client.put(root + "/projects/" + other_project, json=payload()).status_code
        == 200
    )
    assert (
        client.post(route, json={**batch, "project_id": other_project}).status_code
        == 404
    )
    assert len(calls) == 2
    one, two = client.post(route, json=batch).raise_for_status().json()
    assert [row["benchmark_source"]["platform_id"] for row in (one, two)] == [
        POST_A,
        POST_B,
    ]
    results = result_rows(client, root, body)
    assert results[one["id"]]["status"] == "completed"
    assert results[two["id"]]["status"] == "failed"
    assert results[two["id"]]["error_code"] == "VIDEO_TRANSCRIPT_EMPTY"
    assert [row["action"] for row in calls] == [
        "search",
        "search",
        "transcript",
        "transcript",
    ]
    replay = (
        client.post(
            route,
            json={**batch, "expected_revision": 2, "items": [second_pick, first_pick]},
        )
        .raise_for_status()
        .json()
    )
    assert [row["id"] for row in replay] == [two["id"], one["id"]]
    assert len(calls) == 4

    client.app.state.settings.video_writing_workflow_enabled = True
    monkeypatch.setattr(video_writing_routes, "verify_writing_package", lambda _: None)
    save = root + "/writing-documents/reference/from-benchmark/"
    assert client.post(save + two["id"]).status_code == 409
    stored = client.post(save + one["id"]).raise_for_status().json()
    assert stored["assistance_task_id"] == one["id"]
    assert stored["body"]["original_text"] == "这是语音提取的独立原文。"
    assert stored["body"]["source_url"].endswith(POST_A)
    assert stored["body"]["visual_evidence"] == "not_provided"
    assert client.post(save + one["id"]).json()["id"] == stored["id"]
    assert client.get(root + "/projects/" + body["project_id"]).json() == before
