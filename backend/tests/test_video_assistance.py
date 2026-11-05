import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.errors import ApiError
from app.main import create_app
from app.video_assistance_provider import (
    VideoAssistanceProvider,
    transcript_result,
    video_source_url,
)
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_projects import payload


def test_transcript_length_matches_reference_limit_without_truncation():
    raw = "原" * 6000
    assert transcript_result({"results": {"text": raw}}, "source")["text"] == raw
    with pytest.raises(ApiError) as error:
        transcript_result({"results": {"text": raw + "文"}}, "source")
    assert error.value.code == "VIDEO_TRANSCRIPT_TOO_LONG"


class FakeAssistance:
    def __init__(self):
        self.calls = []
        self.status = "succeeded"
        self.unknown = False

    def plan(self, kind, inputs):
        self.calls.append((kind, inputs))
        if self.unknown:
            raise ApiError(502, "VIDEO_ASSISTANCE_OUTCOME_UNKNOWN", "fixture unknown")
        return {
            "title": "收纳介绍",
            "script": "把桌面上的小物集中整理起来，让日常拿取更方便。",
            "warnings": ["产品价格尚未提供"],
        }, {"usage": {"total_tokens": 100}}

    def extract(self, inputs):
        self.calls.append(("extract", inputs))
        return {"job_id": "job-fixture", "billing": {"charged": True}}

    def extract_status(self, task_id):
        self.calls.append(("poll", task_id))
        return {
            "status": self.status,
            "results": {
                "text": "参考视频的完整语音原文，价格99元。",
                "title": "参考来源",
                "segments": [{"start": 0, "end": 2, "text": "参考原文"}],
            },
        }


@pytest.fixture
def assistance(tmp_path):
    auth = FakeExternalAuthBackend(
        identity=verified_identity(email="1474953130@qq.com")
    )
    settings = external_settings(tmp_path).model_copy(
        update={"video_script_planning_enabled": True, "video_extract_enabled": True}
    )
    app = create_app(settings, auth)
    service = FakeAssistance()
    app.state.video_assistance_provider = service
    with TestClient(app) as client:
        ws = client.get("/api/v1/workspaces").json()[0]["id"]
        root = f"/api/v1/video-studio/workspaces/{ws}"
        pid = str(uuid4())
        body = payload()
        body["content"]["product_facts"] = "桌面收纳盒，100毫升；未确认价格。"
        body["content"]["references"] = [
            {
                "id": str(uuid4()),
                "kind": "url",
                "url": "https://www.douyin.com/video/123456789",
                "original_text": "原产品99元，500毫升",
                "note": "参考",
            }
        ]
        assert client.put(root + "/projects/" + pid, json=body).status_code == 200
        yield client, auth, service, root, pid


def body(pid, kind="create"):
    return {
        "request_id": str(uuid4()),
        "project_id": pid,
        "expected_revision": 1,
        "kind": kind,
        "brief": "介绍桌面收纳盒",
    }


def jobs(client, root, pid):
    return client.get(root + "/assistance-tasks", params={"project_id": pid}).json()


def test_planning_is_idempotent_owned_and_never_auto_applies(assistance):
    client, _, service, root, pid = assistance
    before = client.get(root + "/projects/" + pid).json()
    request = body(pid)
    first = client.post(root + "/assistance-tasks", json=request)
    assert first.status_code == 200, first.text
    client.post(root + "/assistance-tasks", json=request)
    task = jobs(client, root, pid)[0]
    assert task["status"] == "completed" and task["result"]["script"]
    assert len(service.calls) == 1
    assert service.calls[0][1]["product_facts"] == before["content"]["product_facts"]
    assert client.get(root + "/projects/" + pid).json() == before
    assert (
        client.post(
            root + "/assistance-tasks", json={**request, "brief": "不同内容"}
        ).status_code
        == 409
    )


def test_rewrite_snapshots_facts_and_keeps_original_separate(assistance):
    client, _, service, root, pid = assistance
    client.post(root + "/assistance-tasks", json=body(pid, "rewrite"))
    inputs = service.calls[0][1]
    assert (
        "99元" in inputs["reference_text"] and "未确认价格" in inputs["product_facts"]
    )
    assert "99元" not in jobs(client, root, pid)[0]["result"]["script"]


def test_unknown_planner_does_not_resubmit(assistance):
    client, _, service, root, pid = assistance
    service.unknown = True
    request = body(pid)
    client.post(root + "/assistance-tasks", json=request)
    task = jobs(client, root, pid)[0]
    assert task["status"] == "unknown" and task["can_resume"] is False
    client.post(root + "/assistance-tasks", json=request)
    assert (
        client.post(root + f"/assistance-tasks/{task['id']}/resume").status_code == 409
    )
    assert len(service.calls) == 1


def test_extract_resume_polls_existing_job_without_another_charge(
    assistance, monkeypatch
):
    monkeypatch.setattr("app.video_assistance.time.sleep", lambda _: None)
    client, _, service, root, pid = assistance
    service.status = "running"
    client.post(root + "/assistance-tasks", json=body(pid, "extract"))
    task = jobs(client, root, pid)[0]
    assert task["status"] == "awaiting_resume"
    service.status = "succeeded"
    client.post(root + f"/assistance-tasks/{task['id']}/resume")
    task = jobs(client, root, pid)[0]
    assert task["status"] == "completed" and task["result"]["segments"][0]["start"] == 0
    assert len([x for x in service.calls if x[0] == "extract"]) == 1


def test_assistance_gray_gate_and_owner_isolation(assistance):
    client, auth, service, root, pid = assistance
    client.post(root + "/assistance-tasks", json=body(pid))
    task = jobs(client, root, pid)[0]
    auth.identity = verified_identity(email="ordinary@example.com")
    assert (
        client.get(
            root + "/assistance-tasks",
            params={"project_id": pid},
            headers={"X-User-Email": "1474953130@qq.com"},
        ).status_code
        == 404
    )
    assert client.post(root + "/assistance-tasks", json=body(pid)).status_code == 404
    assert (
        client.post(root + f"/assistance-tasks/{task['id']}/resume").status_code == 404
    )
    auth.identity = verified_identity(
        primary_user_id="other", email="1474953130@qq.com"
    )
    assert client.post(root + "/assistance-tasks", json=body(pid)).status_code == 404
    assert len(service.calls) == 1


def test_stale_project_and_disabled_planner_never_call_upstream(assistance):
    client, _, service, root, pid = assistance
    assert (
        client.post(
            root + "/assistance-tasks", json={**body(pid), "expected_revision": 2}
        ).status_code
        == 409
    )
    client.app.state.settings.video_script_planning_enabled = False
    assert client.post(root + "/assistance-tasks", json=body(pid)).status_code == 503
    assert service.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "https://evil.example/video/1",
        "https://user:pass@www.douyin.com/video/1",
    ],
)
def test_only_supported_public_source_hosts(url):
    with pytest.raises(ApiError):
        video_source_url(url)


def test_search_modal_link_normalizes_to_selected_video_before_provider_call(
    assistance,
):
    client, _, service, root, pid = assistance
    original = "https://www.douyin.com/search/洗洁精团购?aid=tracking&modal_id=7679330733021859091&type=general"
    content = client.get(root + "/projects/" + pid).json()["content"]
    content["references"][0]["url"] = original
    client.put(
        root + "/projects/" + pid,
        json={"request_id": str(uuid4()), "expected_revision": 1, "content": content},
    )
    request = {**body(pid, "extract"), "expected_revision": 2}
    client.post(root + "/assistance-tasks", json=request)
    inputs = next(value for kind, value in service.calls if kind == "extract")
    assert inputs["source_url"] == "https://www.douyin.com/video/7679330733021859091"
    assert inputs["original_source_url"] == original
    assert "aid=" not in jobs(client, root, pid)[0]["result"]["source_url"]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.douyin.com/search/洗洁精",
        "https://www.douyin.com/search/x?modal_id=bad",
        "https://www.douyin.com/search/x?modal_id=123456&modal_id=234567",
    ],
)
def test_search_page_without_one_valid_video_is_rejected(url):
    with pytest.raises(ApiError):
        video_source_url(url)


def test_empty_transcript_is_not_replaced_by_a_title_and_fake_timings():
    with pytest.raises(ApiError):
        transcript_result(
            {"results": {"title": "发布标题", "text": ""}},
            "https://www.douyin.com/video/1",
        )
    result = transcript_result(
        {
            "results": {
                "text": "真实原文",
                "segments": [{"start": -1, "end": 3, "text": "bad"}],
            }
        },
        "https://www.douyin.com/video/1",
    )
    assert result["segments"] == []


def test_malformed_completed_model_response_keeps_usage_for_review(tmp_path):
    settings = external_settings(tmp_path).model_copy(
        update={
            "video_script_planning_enabled": True,
            "video_script_api_key": SecretStr("test-token"),
        }
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": None}}],
                "usage": {"total_tokens": 8},
            },
        )
    )
    result, receipt = VideoAssistanceProvider(settings, transport).plan(
        "create", {"brief": "普通收纳盒"}
    )
    assert result["validation_error"] == "VIDEO_SCRIPT_INVALID"
    assert receipt["usage"]["total_tokens"] == 8


def test_assistance_migration_preserves_projects_and_compiles_postgres(assistance):
    import importlib.util
    from io import StringIO
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.video_assistance_models import VideoAssistanceRecord

    client, _, _, root, pid = assistance
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261105_0037_video_assistance.py"
    )
    spec = importlib.util.spec_from_file_location("video_assistance_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with client.app.state.engine.begin() as connection:
        VideoAssistanceRecord.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
    assert client.get(root + "/projects/" + pid).status_code == 200
    assert client.post(root + "/assistance-tasks", json=body(pid)).status_code == 200
    output = StringIO()
    with Operations.context(
        MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
        )
    ):
        module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE video_assistance_tasks" in sql and "JSONB" in sql
    assert "DROP" not in sql and "UPDATE users" not in sql


@pytest.mark.parametrize(
    "script,valid",
    [
        ("这个收纳盒售价99元，整理桌面方便拿取。", False),
        ("这个100ml收纳盒，可以集中整理桌面小物。", True),
    ],
)
def test_provider_does_not_inherit_numeric_claims_from_reference(
    tmp_path, script, valid
):
    seen = []

    def transport(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"title": "介绍", "script": script, "warnings": []},
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 5},
            },
        )

    settings = external_settings(tmp_path).model_copy(
        update={
            "video_script_planning_enabled": True,
            "video_script_api_key": SecretStr("test-token"),
        }
    )
    result, receipt = VideoAssistanceProvider(
        settings, httpx.MockTransport(transport)
    ).plan(
        "rewrite",
        {
            "product_facts": "100毫升，旧型号199元，当前未确认售价",
            "reference_text": "参考商品99元",
        },
    )
    assert ("validation_error" not in result) is valid
    assert receipt["usage"]["total_tokens"] == 5 and len(seen) == 1
