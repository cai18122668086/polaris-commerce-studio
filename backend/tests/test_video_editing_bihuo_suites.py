"""Full-suite queue integration and semantic clock bridge; no provider calls."""

import json
import sys
from uuid import uuid4

from app import video_editing_apple_pipeline as pipeline
from app import video_editing_planning_store as store
from app import video_editing_planning_worker as worker
from app.bihuo_suite import registry
from app.video_editing_apple_contracts import build_request, compile_render_input
from app.video_editing_contracts import EditingPlanningTaskCreate
from tests.test_video_editing_apple_contracts import plan, span, transcript
from tests.test_video_editing_apple_pipeline import SuiteProvider
from tests.test_video_editing_planning_tasks import enable_fixture
from tests.test_video_projects import base

pytest_plugins = [
    "tests.test_video_projects",
    "tests.test_video_editing_apple_pipeline",
]


def test_selected_style_reaches_the_single_full_script_request():
    meta = registry.definition("bihuo-36-v1")
    body, _ = build_request(
        transcript(),
        "fixture",
        [],
        template_profile={
            **meta,
            "engine": registry.ENGINE,
            "version": "1.0.0",
            "flow": meta["description"],
        },
    )
    payload = json.loads(body["messages"][1]["content"])
    assert payload["template"]["id"] == "bihuo-36-v1"
    assert payload["transcript"]["tokens"][-1]["id"] == "w17"
    assert meta["name"] in body["messages"][0]["content"]
    assert "你为苹果极简" not in body["messages"][0]["content"]


def test_shared_resolver_preserves_all_native_word_times(tmp_path):
    value = plan()
    value.update(body_variant="points", materials=[], points=[span(3, 5)])
    captured = {}

    options_seen = {}

    def compile_suite(resolved, **options):
        captured.update(resolved)
        options_seen.update(options)
        return {"duration": resolved["duration"], "source": options["source_path"]}

    result = compile_render_input(
        value,
        transcript(),
        {},
        str(tmp_path / "source.mp4"),
        {},
        creative_options={
            "name_card": {"enabled": True, "name": "", "description": "知识博主"},
            "foreground_cache": {"source_sha256": "host-bound", "frames": {}},
        },
        recipe_compiler=compile_suite,
    )
    assert result["duration"] == 18
    assert captured["tokens"] == [
        token.model_dump(mode="json") for token in transcript().tokens
    ]
    assert captured["points"][0]["start"] == 3
    assert captured["conclusion"]["second"]["end"] == 18
    assert options_seen["creative_options"]["name_card"]["enabled"] is True
    assert (
        options_seen["creative_options"]["foreground_cache"]["source_sha256"]
        == "host-bound"
    )


def test_text_only_template_excludes_materials_from_model_request():
    meta = registry.definition("bihuo-36-v1")
    body, _ = build_request(
        transcript(),
        "fixture",
        [{"id": "uploaded", "kind": "image"}],
        template_profile={
            **meta,
            "engine": registry.ENGINE,
            "version": "1",
            "flow": meta["description"],
        },
    )
    assert json.loads(body["messages"][1]["content"])["available_materials"] == []
    assert "materials必须为空" in body["messages"][0]["content"]


def test_installed_silver_and_optional_identity_use_real_runtime(tmp_path):
    assert registry.available("bihuo-36-v1")
    assert not registry.available("not-a-template")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"compile-only-source")
    resolved = {
        "duration": 18,
        "title": "商品图",
        "opening_end": 3,
        "captions": [{"text": "先看商品图", "time": [3, 6]}],
        "chapters": [],
        "conclusion": None,
        "materials": [],
    }
    empty = registry.compile_request(
        "bihuo-36-v1", resolved, source_path=str(source), creative_options={}
    )
    named = registry.compile_request(
        "bihuo-36-v1",
        resolved,
        source_path=str(source),
        creative_options={"name_card": {"enabled": True, "name": "讲师"}},
    )
    assert empty["config"]["identity"]["enabled"] is False
    assert named["config"]["identity"]["name"] == "讲师"
    assert named["config"]["frame_count"] == 450


def test_new_style_prepare_generate_preview_keeps_its_identity(
    suite_fixture, monkeypatch
):
    client, _auth, ws, settings, source, task = suite_fixture
    identity = {
        "engine": registry.ENGINE,
        "template_id": "bihuo-36-v1",
        "version": "fixture",
        "sha256": "d" * 64,
    }
    monkeypatch.setattr(store, "suite_bundle", lambda *_: identity)
    monkeypatch.setattr(pipeline, "suite_bundle", lambda *_: identity)
    module = sys.modules["app.video_editing_apple_contracts"]
    prior = module.build_request
    monkeypatch.setattr(module, "build_request", lambda *args, **_kw: prior(*args))
    endpoint = base(ws) + f"/editing-tasks/{task['id']}/planning-tasks"
    prepared = client.post(
        endpoint,
        json={
            "request_id": str(uuid4()),
            "template_id": "bihuo-36-v1",
            "music": "off",
            "creative_options": {"name_card": {"enabled": False}},
        },
    )
    assert prepared.status_code == 200, prepared.text
    pid = prepared.json()["id"]
    worker.process(pid, settings, client.app.state.session_factory)
    view = client.get(base(ws) + f"/editing-planning-tasks/{pid}").json()
    assert view["status"] == "prepared", view
    assert view["template_id"] == "bihuo-36-v1"
    enable_fixture(settings)
    created = client.post(
        endpoint,
        json={"request_id": str(uuid4()), "mode": "generate", "prepared_task_id": pid},
    )
    assert created.status_code == 200, created.text
    provider = SuiteProvider()
    plan_id = created.json()["id"]
    worker.process(plan_id, settings, client.app.state.session_factory, provider)
    preview = client.post(base(ws) + f"/editing-planning-tasks/{plan_id}/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["template_id"] == "bihuo-36-v1"
    assert preview.json()["source_id"] == source
    assert (
        client.post(base(ws) + f"/editing-planning-tasks/{plan_id}/preview").json()[
            "id"
        ]
        == preview.json()["id"]
    )
    assert provider.calls == 1
    request = EditingPlanningTaskCreate(
        request_id=uuid4(), template_id="bihuo-36-v1", creative_options={}
    )
    assert request.creative_options is not None
