"""Durable suite glue tests use an explicit planner fixture, never a paid model."""

import hashlib
import json
import sys
from types import ModuleType
from uuid import uuid4

import pytest

from app import video_editing_apple_pipeline as apple
from app import video_editing_planning_store as store
from app import video_editing_planning_worker as worker
from app.video_editing_contracts import EditingOptions, EditingPlanningTaskCreate
from app.video_editing_task_models import EditingPlanningTaskRecord, EditingTaskRecord
from tests.test_video_editing_planning_tasks import enable_fixture, setup
from tests.test_video_projects import base

pytest_plugins = ["tests.test_video_projects"]


@pytest.fixture
def suite_fixture(video, tmp_path, monkeypatch):
    client, auth, ws, settings, source, task, _semantic = setup(
        video, tmp_path, monkeypatch
    )
    identity = {"engine": apple.ENGINE, "version": "fixture-only", "sha256": "c" * 64}
    monkeypatch.setattr(store, "suite_bundle", lambda _: identity)
    monkeypatch.setattr(apple, "suite_bundle", lambda _: identity)
    module = ModuleType("app.video_editing_apple_contracts")

    def build_request(transcript, model, cards, creative_options=None):
        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "words": [t.model_dump() for t in transcript.tokens],
                            "cards": cards,
                            "creative": creative_options,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        }
        encoded = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
        return body, {
            "request_sha256": hashlib.sha256(encoded).hexdigest(),
            "request_bytes": len(encoded),
            "model": model,
            "catalog_group_count": 0,
            "max_output_tokens": 2000,
        }

    def verify_plan(raw, _transcript, _cards):
        if raw != {"suite_fixture": True}:
            raise ValueError("Invalid protocol fixture")
        return raw

    module.build_request = build_request
    module.verify_plan = verify_plan
    monkeypatch.setitem(sys.modules, "app.video_editing_apple_contracts", module)
    return client, auth, ws, settings, source, task


class SuiteProvider:
    def __init__(self, outcome="valid"):
        self.calls = 0
        self.outcome = outcome

    def request(self, *_args, **_kwargs):
        self.calls += 1
        if self.outcome == "lost":
            raise OSError("fixture: acknowledgement lost after submission")
        content = (
            json.dumps({"suite_fixture": True})
            if self.outcome == "valid"
            else "{invalid"
        )
        return {"choices": [{"message": {"content": content}}], "model": "fixture"}


def prepare_suite(context):
    client, _auth, ws, settings, _source, task = context
    payload = {
        "request_id": str(uuid4()),
        "template_id": apple.TEMPLATE_ID,
        "music": "off",
        "creative_options": {
            "title": "新标题",
            "name_card": {"enabled": True, "name": "测试讲师"},
            "cover": "none",
        },
    }
    endpoint = base(ws) + f"/editing-tasks/{task['id']}/planning-tasks"
    response = client.post(endpoint, json=payload)
    assert response.status_code == 200, response.text
    assert client.post(endpoint, json=payload).json()["id"] == response.json()["id"]
    assert client.post(endpoint, json={**payload, "music": "lower"}).status_code == 409
    prepared_id = response.json()["id"]
    worker.process(prepared_id, settings, client.app.state.session_factory)
    prepared = client.get(base(ws) + f"/editing-planning-tasks/{prepared_id}").json()
    assert prepared["status"] == "prepared", prepared
    assert prepared["engine"] == apple.ENGINE and prepared["semantic"] is None
    assert prepared["auto_preview_available"] is True
    return prepared_id


def test_suite_creative_contract_does_not_change_legacy_defaults():
    assert "suite_plan_id" not in EditingOptions().model_dump()
    assert (
        "creative_options"
        not in EditingPlanningTaskCreate(request_id=uuid4()).model_dump()
    )
    with pytest.raises(ValueError):
        EditingPlanningTaskCreate(
            request_id=uuid4(),
            template_id="knowledge-talk-v1",
            creative_options={"title": "无效"},
        )
    with pytest.raises(ValueError):
        EditingOptions(mode="suite_plan")
    assert (
        EditingOptions(
            mode="suite_plan", suite_plan_id=uuid4(), delivery="preview_first"
        ).native_plan_id
        is None
    )


def test_suite_full_queue_keeps_choices_frozen_and_reuses_one_preview(suite_fixture):
    context = suite_fixture
    client, _auth, ws, settings, source, task = context
    prepared_id = prepare_suite(context)
    enable_fixture(settings)
    created = client.post(
        base(ws) + f"/editing-tasks/{task['id']}/planning-tasks",
        json={
            "request_id": str(uuid4()),
            "mode": "generate",
            "prepared_task_id": prepared_id,
        },
    )
    assert created.status_code == 200, created.text
    plan_id = created.json()["id"]
    provider = SuiteProvider()
    worker.process(plan_id, settings, client.app.state.session_factory, provider)
    view = client.get(base(ws) + f"/editing-planning-tasks/{plan_id}").json()
    assert view["status"] == "completed", view
    assert view["suite_plan"] == {"suite_fixture": True}
    assert view["semantic"] is None and view["call_state"] == "response_saved"
    assert any(a["role"] == "suite_plan" for a in view["artifacts"])
    with client.app.state.session_factory() as session:
        row = session.get(EditingPlanningTaskRecord, plan_id)
        assert row.snapshot["creative_options"]["title"] == "新标题"
        assert row.snapshot["creative_options"]["cover"] == "none"
        assert row.snapshot["music"] == "off"
        assert row.snapshot["engine_bundle"]["sha256"] == "c" * 64
    endpoint = base(ws) + f"/editing-planning-tasks/{plan_id}/preview"
    first = client.post(endpoint)
    assert first.status_code == 200, first.text
    assert first.json()["options"]["suite_plan_id"] == plan_id
    assert first.json()["options"]["mode"] == "suite_plan"
    assert first.json()["template_id"] == apple.TEMPLATE_ID
    assert first.json()["source_id"] == source
    assert client.post(endpoint).json()["id"] == first.json()["id"]
    worker.process(plan_id, settings, client.app.state.session_factory, provider)
    assert provider.calls == 1


@pytest.mark.parametrize("outcome", ["lost", "malformed"])
def test_suite_recovery_never_repeats_a_billed_submission(suite_fixture, outcome):
    client, _auth, ws, settings, _source, task = suite_fixture
    prepared_id = prepare_suite(suite_fixture)
    enable_fixture(settings)
    pending = client.post(
        base(ws) + f"/editing-tasks/{task['id']}/planning-tasks",
        json={
            "request_id": str(uuid4()),
            "mode": "generate",
            "prepared_task_id": prepared_id,
        },
    ).json()
    provider = SuiteProvider(outcome)
    worker.process(pending["id"], settings, client.app.state.session_factory, provider)
    endpoint = base(ws) + f"/editing-planning-tasks/{pending['id']}"
    failed = client.get(endpoint).json()
    assert failed["status"] == "failed"
    retry = client.post(endpoint + "/retry")
    if outcome == "lost":
        assert retry.status_code == 409
    else:
        assert retry.status_code == 200
        worker.process(
            pending["id"], settings, client.app.state.session_factory, provider
        )
    assert provider.calls == 1


def test_changed_bundle_blocks_before_provider_call(suite_fixture, monkeypatch):
    client, _auth, ws, settings, _source, task = suite_fixture
    prepared_id = prepare_suite(suite_fixture)
    enable_fixture(settings)
    pending = client.post(
        base(ws) + f"/editing-tasks/{task['id']}/planning-tasks",
        json={
            "request_id": str(uuid4()),
            "mode": "generate",
            "prepared_task_id": prepared_id,
        },
    ).json()
    monkeypatch.setattr(
        apple,
        "suite_bundle",
        lambda _: {"engine": apple.ENGINE, "version": "changed", "sha256": "d" * 64},
    )
    provider = SuiteProvider()
    worker.process(pending["id"], settings, client.app.state.session_factory, provider)
    failed = client.get(base(ws) + f"/editing-planning-tasks/{pending['id']}").json()
    assert failed["error_code"] == "EDITING_APPLE_BUNDLE_CHANGED"
    assert provider.calls == 0


def test_suite_rejects_burned_subtitles_before_planning(suite_fixture):
    client, _auth, ws, _settings, _source, task = suite_fixture
    with client.app.state.session_factory() as session:
        row = session.get(EditingTaskRecord, task["id"])
        row.options = {**row.options, "source_subtitles": "present"}
        session.commit()
    response = client.post(
        base(ws) + f"/editing-tasks/{task['id']}/planning-tasks",
        json={"request_id": str(uuid4()), "template_id": apple.TEMPLATE_ID},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EDITING_APPLE_CLEAN_SOURCE_REQUIRED"
