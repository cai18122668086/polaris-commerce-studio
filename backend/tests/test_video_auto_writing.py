"""全自动爆款文案：编排、断点续跑、事实只取原话、AI 选对标的兜底。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import video_auto_writing as auto
from app.main import create_app
from app.video_assistance_models import VideoAssistanceRecord
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_projects import EMAIL, payload

FACTS = "我是做了6年的美甲师。我自己做的护手霜叫小熊暖暖护手霜，一支59元。"


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    auth = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
    settings = external_settings(tmp_path).model_copy(
        update={
            "video_writing_workflow_enabled": True,
            "video_script_planning_enabled": True,
            "video_benchmark_search_enabled": True,
            "video_extract_enabled": True,
            "video_extract_api_key": SecretStr("local-fixture"),
        }
    )
    app = create_app(settings, auth)
    with TestClient(app) as client:
        workspace_id = client.get("/api/v1/workspaces").json()[0]["id"]
        root = f"/api/v1/video-studio/workspaces/{workspace_id}"
        project = str(uuid4())
        assert (
            client.put(f"{root}/projects/{project}", json=payload()).status_code == 200
        )
        yield app, client, root, project


def start(client, root, project, monkeypatch, steps):
    monkeypatch.setattr(auto, "STEPS", steps)
    body = {
        "request_id": str(uuid4()),
        "project_id": project,
        "expected_revision": 1,
        "platform": "xiaohongshu",
        "query": "护手霜",
        "facts_text": FACTS,
    }
    response = client.post(f"{root}/auto-writing", json=body)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def stored(app, run_id):
    with app.state.session_factory() as session:
        return session.get(VideoAssistanceRecord, run_id)


def test_a_run_goes_through_every_step_and_keeps_what_the_user_typed(
    app_client, monkeypatch
):
    app, client, root, project = app_client
    seen = []

    def step(name, value):
        def run(run, inputs, state=None):
            seen.append(name)
            run.save(**{auto.DONE_WHEN.get(name, name): value})

        return run

    steps = [(name, step(name, f"{name}-done")) for name, _ in auto.STEPS]
    monkeypatch.setattr(auto, "step_search", steps[0][1])
    run_id = start(client, root, project, monkeypatch, steps)
    row = stored(app, run_id)
    assert row.status == "completed" and row.result["stage"] == "done"
    assert seen == ["search", "pick", "extract", "analyse", "facts", "write"]
    assert row.result["request"]["facts_text"] == FACTS
    listed = client.get(
        f"{root}/assistance-tasks", params={"project_id": project}
    ).json()
    assert any(job["id"] == run_id and job["kind"] == "auto_writing" for job in listed)


def test_a_stopped_run_explains_itself_and_resumes_from_its_checkpoint(
    app_client, monkeypatch
):
    app, client, root, project = app_client
    calls = []

    def search(run, inputs, state=None):
        calls.append("search")
        run.save(search_task_id="page-1")

    def pick(run, inputs, state):
        calls.append("pick")
        if len(calls) < 3:
            raise auto.Stop("VIDEO_AUTO_NO_CANDIDATES", "没有找到可用的视频")
        run.save(ranked=[{"platform_id": "a", "reason": "r"}])

    rest = [
        (
            name,
            lambda run, inputs, state, n=name: run.save(
                **{auto.DONE_WHEN.get(n, n): 1}
            ),
        )
        for name, _ in auto.STEPS[2:]
    ]
    monkeypatch.setattr(auto, "step_search", search)
    run_id = start(
        client, root, project, monkeypatch, [("search", search), ("pick", pick), *rest]
    )
    row = stored(app, run_id)
    assert (row.status, row.error_code) == ("failed", "VIDEO_AUTO_NO_CANDIDATES")
    assert row.result["message"] == "没有找到可用的视频"

    resumed = client.post(f"{root}/auto-writing/{run_id}/resume")
    assert resumed.status_code == 200
    row = stored(app, run_id)
    assert row.status == "completed" and row.result["retry"] == 1
    assert calls == ["search", "pick", "pick"]  # the finished search was not repeated

    other = client.post(f"{root}/assistance-tasks/{run_id}/resume")
    assert other.status_code == 409  # only the auto-writing page resumes a run


class FakeRun(SimpleNamespace):
    def ask(self, system, payload, max_tokens=1500):
        return self.answer(payload)


def test_facts_are_only_the_users_own_words():
    run = FakeRun(
        answer=lambda payload: {
            "facts": [
                {"category": "identity", "label": "身份", "value": "做了6年的美甲师"},
                {"category": "product", "label": "产品", "value": "小熊暖暖护手霜"},
                {
                    "category": "product",
                    "label": "功效",
                    "value": "七天美白",
                },  # invented
                {
                    "category": "rights",
                    "label": "错类",
                    "value": "一支59元",
                },  # wrong category
            ]
        }
    )
    facts = auto.sort_facts(run, {"facts_text": FACTS})
    assert [f["value"] for f in facts] == ["做了6年的美甲师", "小熊暖暖护手霜"]
    assert all(f["status"] == "user_declared" for f in facts)

    broken = FakeRun(
        answer=lambda payload: (_ for _ in ()).throw(ValueError("no json"))
    )
    (whole,) = auto.sort_facts(broken, {"facts_text": FACTS})
    assert whole["value"] == FACTS


def test_ai_picks_are_kept_only_when_real_and_backed_up_by_likes(monkeypatch):
    items = [
        {"platform_id": "a", "title": "A", "like_count": 10, "duration_seconds": 40},
        {"platform_id": "b", "title": "B", "like_count": 900, "duration_seconds": 30},
        {"platform_id": "c", "title": "C", "like_count": 500, "duration_seconds": 600},
    ]
    saved = {}
    run = FakeRun(
        answer=lambda payload: {
            "picks": [
                {"platform_id": "zzz", "reason": "编的"},
                {"platform_id": "a", "reason": "最相关"},
            ]
        },
        task=lambda task_id: SimpleNamespace(result={"items": items}),
        save=lambda **values: saved.update(values),
    )
    auto.step_pick(
        run,
        {"query": "护手霜", "facts_text": FACTS},
        {"search_task_id": "p", "mode": "search"},
    )
    assert [r["platform_id"] for r in saved["ranked"]] == [
        "a",
        "b",
    ]  # 600s video left out
    assert saved["ranked"][0]["reason"] == "最相关"
