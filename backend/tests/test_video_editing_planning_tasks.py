"""Queue/charging boundaries with explicit protocol fixtures, never a paid model."""

import hashlib
import importlib.util
import json
import wave
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, select, text

from app import video_editing_hypit as hypit
from app import video_editing_planning_routes as planning_routes
from app import video_editing_planning_worker as worker
from app import video_editing_task_routes as task_routes
from app.config import Settings
from app.errors import ApiError
from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_azl_panels import azl_blockers
from app.video_editing_contracts import SemanticPlan, Transcript, TranscriptToken
from app.video_editing_cxbr import CXBR_PAPER_GROUPS, CXBR_PURPOSES, cxbr_blockers
from app.video_editing_judgment import JUDGMENT_EVENTS, judgment_entry_frame
from app.video_editing_native_sound import verify_rendered_sound
from app.video_editing_overlay_templates import overlay_template
from app.video_editing_presenter_motion import motion_blockers
from app.video_editing_question_branch import QUESTION_FONT
from app.video_editing_subtitle_foreground import FOREGROUND_SUBTITLE_DEPENDENCIES
from app.video_editing_task_models import (
    EditingPlanningAttemptRecord,
    EditingPlanningTaskRecord,
    EditingTaskRecord,
)
from app.video_editing_template_materials import (
    template_image_requirements,
    validate_template_images,
)
from app.video_editing_unified_scenes import (
    UNIFIED_EXPANDED_TEMPLATE_ID,
    UNIFIED_GROUPS,
    UNIFIED_SCENE_GROUPS,
    UNIFIED_TEMPLATE_ID,
    require_clean_unified_source,
    require_spoken_year,
)
from app.video_editing_yy6_scenes import YY6_GROUPS, yy6_scene_inputs
from app.video_editing_yy_openings import require_clean_yy_source
from tests.test_video_editing_native_plans import saved_plan
from tests.test_video_projects import base, payload, put

pytest_plugins = ["tests.test_video_projects"]


def setup(video, tmp_path, monkeypatch):
    client, auth, ws, settings, source, task, semantic, _ = saved_plan(
        video, tmp_path, monkeypatch
    )
    monkeypatch.setattr(worker, "verify_package", lambda _: None)

    def request(
        transcript, package, model, cards, choices, template=None, runtime=None
    ):
        body = {
            "model": model,
            "words": [{"id": t.id, "text": t.text} for t in transcript.tokens],
            "cards": cards,
            "choices": choices,
            **({"overlay_template": template} if template else {}),
            **({"runtime": runtime} if runtime else {}),
        }
        data = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
        return body, {
            "request_sha256": hashlib.sha256(data).hexdigest(),
            "request_bytes": len(data),
            "catalog_group_count": 132,
            "model": model,
            "max_output_tokens": 5000,
        }

    monkeypatch.setattr(worker.planner, "build_request", request)
    client.app.state.editing_planning_dispatcher = lambda _: None
    return client, auth, ws, settings, source, task, semantic


def create(client, ws, tid, mode="prepare", prepared=None, request_id=None):
    return client.post(
        base(ws) + f"/editing-tasks/{tid}/planning-tasks",
        json={
            "request_id": request_id or str(uuid4()),
            "mode": mode,
            "prepared_task_id": prepared,
        },
    )


def prepare(client, ws, settings, task):
    submitted = create(client, ws, task["id"])
    assert submitted.status_code == 200, submitted.text
    worker.process(submitted.json()["id"], settings, client.app.state.session_factory)
    result = client.get(base(ws) + "/editing-planning-tasks/" + submitted.json()["id"])
    assert result.json()["status"] == "prepared", result.text
    return result.json()


def test_selected_overlay_template_is_frozen_in_preparation(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, _, task, _ = setup(video, tmp_path, monkeypatch)
    root = base(ws)
    options = client.get(root + "/editing-templates").json()
    assert {row["id"] for row in options} == {
        "label-compare-v1",
        "roll-compare-v2",
        "question-story-v1",
        "question-card-story-v1",
        "picture-compare-v2",
        "rotation-cards-v1",
        "numbered-pictures-v1",
        "live-strip-story-v1",
        "package-specs-v1",
        "line-story-v1",
        "presenter-openings-v1",
        "yy-presenter-openings-v3",
        "presenter-reframing-v1",
        "azl-panels-v1",
        "chenxi-broll-v1",
        UNIFIED_EXPANDED_TEMPLATE_ID,
        "evidence-judgment-v1",
        "explainer-steps-v1",
        "subtitle-story-v1",
        "subtitle-relay-v1",
        "subtitle-progress-v1",
        "subtitle-foreground-v1",
    }
    assert all(len(row["slots"]) >= 10 for row in options)
    unified = next(row for row in options if row["id"] == UNIFIED_EXPANDED_TEMPLATE_ID)
    previous_unified = overlay_template(UNIFIED_TEMPLATE_ID)
    assert unified["slots"][3:] == previous_unified["slots"]
    assert {
        row["group_id"]
        for row in previous_unified["slots"]
        if row.get("layer") == "scene"
    } == set(UNIFIED_GROUPS)
    assert {
        row["group_id"] for row in unified["slots"] if row.get("layer") == "scene"
    } == UNIFIED_SCENE_GROUPS
    unified_blocked = {}
    require_clean_unified_source(unified, "present", unified_blocked)
    assert unified_blocked == dict.fromkeys(
        UNIFIED_SCENE_GROUPS, ["clean_source_required"]
    )
    progress = next(row for row in options if row["id"] == "subtitle-progress-v1")
    relay = next(row for row in options if row["id"] == "subtitle-relay-v1")
    assert len(progress["slots"]) == len(relay["slots"]) + 8
    assert progress["slots"][8:] == relay["slots"]
    foreground = next(row for row in options if row["id"] == "subtitle-foreground-v1")
    assert len(foreground["slots"]) == len(progress["slots"]) + 6
    assert foreground["slots"][6:] == progress["slots"]
    rotation = next(row for row in options if row["id"] == "rotation-cards-v1")
    assert rotation["slots"][0]["group_id"] == "CX-G04"
    openings = next(row for row in options if row["id"] == "presenter-openings-v1")
    assert {
        slot["group_id"] for slot in openings["slots"] if slot.get("layer") == "scene"
    } == {"LYO01", "LYO02", "LYO03", "LYO04"}
    yy = next(row for row in options if row["id"] == "yy-presenter-openings-v3")
    yy_groups = {
        slot["group_id"] for slot in yy["slots"] if slot.get("layer") == "scene"
    }
    assert yy_groups == {
        *(f"YYO{i:02}" for i in range(1, 9)),
        *(f"YY6O{i:02}" for i in range(1, 7)),
    }
    expanded = overlay_template("yy-presenter-openings-v2")
    assert [
        slot for slot in yy["slots"] if slot["group_id"] not in YY6_GROUPS
    ] == expanded["slots"]
    frozen = overlay_template("yy-presenter-openings-v1")
    assert expanded["slots"][:6] + expanded["slots"][9:] == frozen["slots"]
    unavailable = {"YYO02": ["missing-original"]}
    require_clean_yy_source(yy, "present", unavailable)
    assert set(unavailable) == yy_groups
    assert unavailable["YYO02"] == ["missing-original", "clean_source_required"]
    framing = next(row for row in options if row["id"] == "presenter-reframing-v1")
    assert {
        slot["group_id"] for slot in framing["slots"] if slot.get("layer") == "scene"
    } == {f"YYP{i:02}" for i in range(1, 8)}
    template = next(row for row in options if row["id"] == "question-story-v1")
    scene = next(slot for slot in template["slots"] if slot["group_id"] == "W-R18")
    assert scene["layer"] == "scene" and scene["native_branch"] == "question"
    card = next(row for row in options if row["id"] == "question-card-story-v1")
    assert card["slots"][0]["group_id"] == "AH-S03"
    assert card["slots"][0]["native_branch"] == "input-A"
    url = root + f"/editing-tasks/{task['id']}/planning-tasks"
    body = {"request_id": str(uuid4()), "template_id": template["id"]}
    saved = client.post(url, json=body)
    assert saved.status_code == 200 and saved.json()["overlay_template"] == template
    assert (
        client.post(url, json={**body, "template_id": options[1]["id"]}).status_code
        == 409
    )
    worker.process(saved.json()["id"], settings, client.app.state.session_factory)
    ready = client.get(root + "/editing-planning-tasks/" + saved.json()["id"]).json()
    assert ready["status"] == "prepared" and ready["call_state"] == "not_submitted"
    artifact = next(row for row in ready["artifacts"] if row["role"] == "request")
    assert client.get(artifact["url"]).json()["overlay_template"] == template


def enable_fixture(settings):
    settings.video_editing_planning_enabled = True
    settings.video_script_planning_enabled = True
    settings.video_script_api_key = SecretStr("protocol-fixture-never-sent")


class Provider:
    def __init__(self, semantic, lost=False, malformed=False, during=None):
        self.semantic, self.lost, self.malformed, self.during = (
            semantic,
            lost,
            malformed,
            during,
        )
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        if self.during:
            self.during()
        if self.lost:
            raise ApiError(502, "VIDEO_ASSISTANCE_OUTCOME_UNKNOWN", "Fixture only")
        if self.malformed == "envelope":
            return {"id": "fixture-empty-envelope", "choices": []}
        return {
            "id": "fixture-not-a-model-result",
            "model": "fixture",
            "usage": {"completion_tokens": 10},
            "choices": [
                {
                    "message": {
                        "content": "invalid"
                        if self.malformed
                        else self.semantic.model_dump_json()
                    }
                }
            ],
        }


def test_free_preparation_is_durable_scoped_and_contains_no_paths(
    video, tmp_path, monkeypatch
):
    client, auth, ws, settings, source, task, semantic = setup(
        video, tmp_path, monkeypatch
    )
    rid = str(uuid4())
    submitted = create(client, ws, task["id"], request_id=rid)
    assert submitted.status_code == 200 and submitted.json()["mode"] == "prepare"
    assert (
        create(client, ws, task["id"], request_id=rid).json()["id"]
        == submitted.json()["id"]
    )
    provider = Provider(semantic)
    worker.process(
        submitted.json()["id"], settings, client.app.state.session_factory, provider
    )
    result = client.get(
        base(ws) + "/editing-planning-tasks/" + submitted.json()["id"]
    ).json()
    assert result["status"] == "prepared" and result["catalog_group_count"] == 132
    assert result["call_state"] == "not_submitted" and result["semantic"] is None
    assert result["semantic_origin"] is None and not result["execution_available"]
    assert provider.calls == 0
    assert str(tmp_path) not in json.dumps(result)
    artifact = next(a for a in result["artifacts"] if a["role"] == "request")
    payload = client.get(artifact["url"])
    assert payload.status_code == 200 and str(tmp_path) not in payload.text
    assert payload.json()["cards"][0]["id"] == "source-" + source
    assert create(client, ws, task["id"], "generate", result["id"]).status_code == 503
    from tests.test_auth_external import verified_identity

    auth.identity = verified_identity(
        primary_user_id="another-user", email="1474953130@qq.com"
    )
    assert client.get(artifact["url"]).status_code in (403, 404)
    assert client.get(
        base(ws) + "/editing-planning-tasks/" + result["id"]
    ).status_code in (403, 404)


@pytest.mark.parametrize(
    ("template_id", "removed", "affected"),
    [
        ("question-story-v1", QUESTION_FONT, ["W-R18"]),
        ("subtitle-foreground-v1", "font-06b2048c592b1dae", ["BG-S10", "BG-S11"]),
    ],
)
def test_missing_original_after_preparation_stops_before_model_submission(
    video, tmp_path, monkeypatch, template_id, removed, affected
):
    client, _, ws, settings, _, task, semantic = setup(video, tmp_path, monkeypatch)
    index = settings.video_editing_library_dir / "catalog/external-resources.json"
    catalog = read_json(index)
    ids = (
        {rid for group in FOREGROUND_SUBTITLE_DEPENDENCIES.values() for rid in group}
        if template_id == "subtitle-foreground-v1"
        else {QUESTION_FONT}
    )
    fonts = {}
    for rid in ids:
        font = tmp_path / rid
        font.write_bytes(b"source")
        fonts[rid] = str(font)
        catalog["resources"].append(
            {"id": rid, "kind": "font", "bytes": 6, "sha256": sha256(font)}
        )
    atomic_json(index, catalog)
    registry = tmp_path / "registry.json"
    atomic_json(registry, {"resources": fonts})
    settings.video_editing_native_bindings_file = registry
    enable_fixture(settings)

    route = base(ws) + f"/editing-tasks/{task['id']}/planning-tasks"
    task_route = base(ws) + "/editing-planning-tasks/"
    factory = client.app.state.session_factory
    provider = Provider(semantic)

    def prepare_template():
        prepared = (
            client.post(
                route,
                json={"request_id": str(uuid4()), "template_id": template_id},
            )
            .raise_for_status()
            .json()
        )
        worker.process(prepared["id"], settings, factory, provider)
        return client.get(task_route + prepared["id"]).raise_for_status().json()

    prepared = prepare_template()
    assert prepared["status"] == "prepared"
    assert prepared["unavailable_template_group_ids"] == []
    Path(fonts[removed]).write_bytes(b"broken")
    submitted = create(client, ws, task["id"], "generate", prepared["id"])
    assert submitted.status_code == 200
    job = submitted.json()["id"]
    worker.process(job, settings, factory, provider)
    failed = client.get(task_route + job).raise_for_status().json()
    assert failed["error_code"] == "EDITING_TEMPLATE_DEPENDENCIES_CHANGED"
    assert failed["call_state"] == "not_submitted"
    assert provider.calls == 0

    fresh = prepare_template()
    assert fresh["status"] == "prepared"
    assert fresh["unavailable_template_group_ids"] == affected
    request = next(a for a in fresh["artifacts"] if a["role"] == "request")
    frozen = client.get(request["url"]).raise_for_status().json()["runtime"]
    assert frozen["unavailable_template_groups"] == {
        group: [removed] for group in affected
    }
    assert fonts[removed] not in json.dumps(frozen)


def test_strip_planning_checks_scoped_runtime_and_original_subtitles(
    tmp_path, monkeypatch
):
    cli = tmp_path / "bin" / "hypit.mjs"
    cli.parent.mkdir()
    cli.write_bytes(b"local verification fixture")
    chrome = tmp_path / "chrome"
    chrome.touch()
    atomic_json(tmp_path / "package.json", {"version": "0.2.12"})
    monkeypatch.setattr(hypit, "CLI_SHA256", sha256(cli))
    settings = Settings(
        _env_file=None,
        environment="test",
        auth_mode="development",
        video_editing_hypit_internal_workspace="internal",
        video_editing_hypit_local_module=cli,
        video_editing_hypit_local_chrome=chrome,
    )
    template = overlay_template("live-strip-story-v1")
    assert worker.live_strip_blockers(settings, "internal", template, "none") == {}
    assert worker.live_strip_blockers(settings, "internal", template, "present") == {
        "HY-A5": ["source-subtitles-must-be-none"]
    }
    unavailable = {"HY-A5": ["original-hypit-internal-runtime-unavailable"]}
    assert (
        worker.live_strip_blockers(settings, "other", template, "none") == unavailable
    )
    cli.write_bytes(b"changed")
    assert (
        worker.live_strip_blockers(settings, "internal", template, "none")
        == unavailable
    )
    assert worker.live_strip_blockers(settings, "internal", None, "none") == {}


def test_one_execution_per_prepared_request_and_valid_response_contract(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, _, task, semantic = setup(video, tmp_path, monkeypatch)
    prepared = prepare(client, ws, settings, task)
    enable_fixture(settings)
    submitted = create(client, ws, task["id"], "generate", prepared["id"])
    assert submitted.status_code == 200, submitted.text
    assert (
        create(client, ws, task["id"], "generate", prepared["id"]).json()["id"]
        == submitted.json()["id"]
    )
    provider = Provider(semantic)
    worker.process(
        submitted.json()["id"], settings, client.app.state.session_factory, provider
    )
    worker.process(
        submitted.json()["id"], settings, client.app.state.session_factory, provider
    )
    result = client.get(
        base(ws) + "/editing-planning-tasks/" + submitted.json()["id"]
    ).json()
    assert result["status"] == "completed", result
    assert (
        result["semantic_origin"] == "tengli_gateway"
        and result["semantic_review"] == "unreviewed"
    )
    assert (
        result["native_render_state"] == "not_compiled"
        and result["call_state"] == "response_saved"
    )
    assert provider.calls == 1
    assert result["semantic"] == semantic.model_dump(mode="json")


def test_completed_planning_preview_is_linked_before_dispatch_and_replayed(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, source, task, semantic = setup(
        video, tmp_path, monkeypatch
    )
    factory = client.app.state.session_factory
    settings.video_editing_native_plan_enabled = True
    prepared = prepare(client, ws, settings, task)
    root = base(ws) + "/editing-planning-tasks/"
    rejected = client.post(root + prepared["id"] + "/preview")
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "EDITING_PLANNING_RESULT_REQUIRED"
    enable_fixture(settings)
    pending = create(client, ws, task["id"], "generate", prepared["id"]).json()
    provider = Provider(semantic)
    worker.process(pending["id"], settings, factory, provider)
    candidate = SimpleNamespace(
        id=str(uuid4()),
        source_id=source,
        details={"source_subtitles": "none"},
        recipes={"design": {"caption_font_id": "font-d1961be1161ea1be"}},
    )
    adopted = []

    def gateway(_session, _settings, _workspace, row):
        assert row.status == "completed"
        adopted.append(row.id)
        return candidate

    def admit(_session, _settings, _plan, original, options):
        assert original.id == source
        assert str(options.native_plan_id) == candidate.id
        assert options.delivery == "preview_first"

    monkeypatch.setattr(planning_routes, "gateway_candidate", gateway)
    monkeypatch.setattr(task_routes, "admit_render_plan", admit)
    dispatched = []

    def observe(preview_id):
        with factory() as session:
            row = session.get(EditingPlanningTaskRecord, pending["id"])
            render = session.get(EditingTaskRecord, preview_id)
            assert row.result["preview_task_id"] == render.id
        dispatched.append(preview_id)

    client.app.state.editing_dispatcher = observe
    response = client.post(root + pending["id"] + "/preview")
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["status"] == "queued" and not preview["artifacts"]
    replay = client.post(root + pending["id"] + "/preview").json()
    assert replay["id"] == preview["id"]
    assert adopted == [pending["id"]] and dispatched == [preview["id"]]
    planning = client.get(root + pending["id"]).json()
    assert planning["preview_task_id"] == preview["id"]
    assert planning["native_render_state"] == "preview_requested"
    assert planning["semantic"] == semantic.model_dump(mode="json")
    assert provider.calls == 1


def test_batch_previews_commit_independently_and_replay_single_ids(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, source, task, semantic = setup(
        video, tmp_path, monkeypatch
    )
    factory = client.app.state.session_factory
    prepared = prepare(client, ws, settings, task)
    enable_fixture(settings)
    provider = Provider(semantic)
    plans = []
    for _ in range(2):
        ready = prepare(client, ws, settings, task)
        pending = create(client, ws, task["id"], "generate", ready["id"]).json()
        worker.process(pending["id"], settings, factory, provider)
        plans.append(pending["id"])

    def gateway(_session, _settings, _workspace, row):
        if row.status != "completed":
            raise ApiError(409, "EDITING_PLANNING_RESULT_REQUIRED", "规划候选未就绪。")
        return SimpleNamespace(
            id=str(uuid4()),
            source_id=source,
            details={"source_subtitles": "none"},
            recipes={"design": {"caption_font_id": "font-d1961be1161ea1be"}},
        )

    monkeypatch.setattr(planning_routes, "gateway_candidate", gateway)
    monkeypatch.setattr(task_routes, "admit_render_plan", lambda *args: None)
    dispatched = []
    client.app.state.editing_dispatcher = dispatched.append
    batch = base(ws) + f"/projects/{task['project_id']}/editing-planning-preview-batch"

    def submit(ids):
        return client.post(batch, json={"planning_task_ids": ids})

    assert submit([plans[0]]).status_code == 422
    assert submit([str(uuid4()) for _ in range(6)]).status_code == 422
    assert submit([plans[0], plans[0]]).status_code == 422
    assert submit([plans[0], str(uuid4())]).status_code == 404
    other_project = str(uuid4())
    put(client, ws, other_project, payload())
    with factory() as session:
        row = session.get(EditingPlanningTaskRecord, prepared["id"])
        row.project_id = other_project
        session.commit()
    assert submit([plans[0], prepared["id"]]).status_code == 404
    assert dispatched == []
    with factory() as session:
        row = session.get(EditingPlanningTaskRecord, prepared["id"])
        row.project_id = task["project_id"]
        session.commit()

    requested = [plans[0], prepared["id"], plans[1]]
    response = submit(requested)
    assert response.status_code == 200, response.text
    first, rejected, last = response.json()
    assert [item["planning_task_id"] for item in response.json()] == requested
    assert rejected["error_code"] == "EDITING_PLANNING_RESULT_REQUIRED"
    assert rejected["task"] is None
    for item in (first, last):
        preview = item["task"]
        assert preview["status"] == "queued" and not preview["artifacts"]
        assert preview["options"]["delivery"] == "preview_first"
        route = base(ws) + f"/editing-planning-tasks/{item['planning_task_id']}"
        assert client.get(route).json()["preview_task_id"] == preview["id"]
        assert client.post(route + "/preview").json()["id"] == preview["id"]
    assert submit(requested).json() == response.json()
    assert dispatched == [first["task"]["id"], last["task"]["id"]]
    assert len(set(dispatched)) == 2
    assert provider.calls == 2


@pytest.mark.parametrize("malformed", [False, True, "envelope"])
def test_unknown_or_invalid_result_cannot_bill_again(
    video, tmp_path, monkeypatch, malformed
):
    client, _, ws, settings, _, task, semantic = setup(video, tmp_path, monkeypatch)
    prepared = prepare(client, ws, settings, task)
    enable_fixture(settings)
    submitted = create(client, ws, task["id"], "generate", prepared["id"]).json()
    provider = Provider(semantic, lost=not malformed, malformed=malformed)
    worker.process(
        submitted["id"], settings, client.app.state.session_factory, provider
    )
    url = base(ws) + "/editing-planning-tasks/" + submitted["id"]
    result = client.get(url).json()
    assert result["status"] == "failed" and provider.calls == 1
    retry = client.post(url + "/retry")
    if malformed:
        assert retry.status_code == 200
        worker.process(
            submitted["id"], settings, client.app.state.session_factory, provider
        )
        assert client.get(url).json()["status"] == "failed"
    else:
        assert (
            retry.status_code == 409
            and retry.json()["error"]["code"] == "EDITING_PLAN_ALREADY_SUBMITTED"
        )
    assert provider.calls == 1


def test_late_response_is_saved_but_lost_lease_cannot_publish_then_readonly_recovery(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, _, task, semantic = setup(video, tmp_path, monkeypatch)
    prepared = prepare(client, ws, settings, task)
    enable_fixture(settings)
    submitted = create(client, ws, task["id"], "generate", prepared["id"]).json()
    factory = client.app.state.session_factory

    def reclaim():
        with factory() as session:
            row = session.get(EditingPlanningTaskRecord, submitted["id"])
            row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        worker.process(submitted["id"], settings, factory, provider)

    provider = Provider(semantic, during=reclaim)
    worker.process(submitted["id"], settings, factory, provider)
    url = base(ws) + "/editing-planning-tasks/" + submitted["id"]
    result = client.get(url).json()
    assert result["status"] == "failed" and result["call_state"] == "response_saved"
    assert result["semantic"] is None and provider.calls == 1
    settings.video_editing_planning_enabled = settings.video_script_planning_enabled = (
        False
    )
    assert client.post(url + "/retry").status_code == 200
    worker.process(submitted["id"], settings, factory, provider)
    assert client.get(url).json()["status"] == "completed"
    assert provider.calls == 1
    with factory() as session:
        attempts = list(
            session.scalars(
                select(EditingPlanningAttemptRecord)
                .where(EditingPlanningAttemptRecord.task_id == submitted["id"])
                .order_by(EditingPlanningAttemptRecord.number)
            )
        )
        assert [a.status for a in attempts] == ["superseded", "failed", "completed"]


def test_api_never_connects_broker_and_cancelled_prepare_never_runs(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, _, task, semantic = setup(video, tmp_path, monkeypatch)
    del client.app.state.editing_planning_dispatcher
    monkeypatch.setattr(
        worker.celery_app,
        "send_task",
        lambda *a, **k: pytest.fail("Request thread must not publish"),
    )
    submitted = create(client, ws, task["id"])
    assert submitted.status_code == 200
    url = base(ws) + "/editing-planning-tasks/" + submitted.json()["id"]
    assert client.post(url + "/cancel").json()["status"] == "cancelled"
    provider = Provider(semantic)
    worker.process(
        submitted.json()["id"], settings, client.app.state.session_factory, provider
    )
    assert client.get(url).json()["attempts"] == 0 and provider.calls == 0


def test_prepared_artifact_change_fails_before_model_submission(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, _, task, semantic = setup(video, tmp_path, monkeypatch)
    prepared = prepare(client, ws, settings, task)
    enable_fixture(settings)
    submitted = create(client, ws, task["id"], "generate", prepared["id"]).json()
    with client.app.state.session_factory() as session:
        row = session.get(EditingPlanningTaskRecord, prepared["id"])
        file = Path(
            next(a["path"] for a in row.result["artifacts"] if a["role"] == "request")
        )
    file.write_text("{}")
    provider = Provider(semantic)
    worker.process(
        submitted["id"], settings, client.app.state.session_factory, provider
    )
    result = client.get(base(ws) + "/editing-planning-tasks/" + submitted["id"]).json()
    assert result["error_code"] == "EDITING_PREPARED_REQUEST_CHANGED"
    assert provider.calls == 0 and result["call_state"] == "not_submitted"


def test_planning_migration_roundtrip_preserves_prior_rows(tmp_path):
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261109_0047_editing_planning_tasks.py"
    )
    spec = importlib.util.spec_from_file_location("planning_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path / 'planning.db'}")
    with engine.begin() as connection:
        for name in (
            "workspaces",
            "users",
            "video_projects",
            "video_editing_sources",
            "video_editing_tasks",
            "video_editing_artifacts",
        ):
            connection.execute(
                text(f"CREATE TABLE {name} (id VARCHAR(40) PRIMARY KEY)")
            )
        connection.execute(text("INSERT INTO users VALUES ('preserved')"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert (
            len(
                inspect(connection).get_unique_constraints(
                    "video_editing_planning_tasks"
                )
            )
            == 2
        )
        module.downgrade()
        assert connection.scalar(text("SELECT id FROM users")) == "preserved"
    engine.dispose()


def test_changed_project_choice_requires_a_new_preparation_before_spending(
    video, tmp_path, monkeypatch
):
    from app.motion_library import MOTION_SHA256
    from app.video_editing_task_models import EditingLibraryNoteRecord

    client, _, ws, settings, _, task, _ = setup(video, tmp_path, monkeypatch)
    prepared = prepare(client, ws, settings, task)
    enable_fixture(settings)
    with client.app.state.session_factory() as session:
        row = session.get(EditingPlanningTaskRecord, prepared["id"])
        session.add(
            EditingLibraryNoteRecord(
                id=str(uuid4()),
                workspace_id=row.workspace_id,
                owner_user_id=row.owner_user_id,
                project_id=row.project_id,
                library_release=MOTION_SHA256,
                request_id=str(uuid4()),
                request_hash="f" * 64,
                target_kind="group",
                target_id="T001",
                sequence=1,
                choice="avoid",
                reason="fixture changed selection",
                details={"target_name": "T001"},
            )
        )
        session.commit()
    result = create(client, ws, task["id"], "generate", prepared["id"])
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "EDITING_CHOICES_CHANGED_REPLAN_REQUIRED"


def test_broker_loss_keeps_planning_job_durable_and_reserves_redelivery(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, _, task, _ = setup(video, tmp_path, monkeypatch)
    submitted = create(client, ws, task["id"]).json()
    factory = client.app.state.session_factory

    def unavailable(*args, **kwargs):
        raise ConnectionError("fixture broker unavailable")

    monkeypatch.setattr(worker.celery_app, "send_task", unavailable)
    assert worker.recover(factory) == 0
    with factory() as session:
        row = session.get(EditingPlanningTaskRecord, submitted["id"])
        assert row.status == "queued" and row.checkpoint["dispatch_not_before"] > 0
        row.checkpoint = {"dispatch_not_before": 0}
        session.commit()
    sent = []
    monkeypatch.setattr(
        worker.celery_app, "send_task", lambda *a, **k: sent.append((a, k))
    )
    assert worker.recover(factory) == 1 and worker.recover(factory) == 0
    assert len(sent) == 1


def test_gateway_cannot_change_after_preparation_or_while_execution_is_queued(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, _, task, semantic = setup(video, tmp_path, monkeypatch)
    prepared = prepare(client, ws, settings, task)
    original = settings.video_script_base_url
    enable_fixture(settings)
    settings.video_script_base_url = "https://changed.example.invalid"
    denied = create(client, ws, task["id"], "generate", prepared["id"])
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "EDITING_PLAN_ENDPOINT_CHANGED"
    settings.video_script_base_url = original
    submitted = create(client, ws, task["id"], "generate", prepared["id"]).json()
    settings.video_script_base_url = "https://changed.example.invalid"
    provider = Provider(semantic)
    worker.process(
        submitted["id"], settings, client.app.state.session_factory, provider
    )
    result = client.get(base(ws) + "/editing-planning-tasks/" + submitted["id"]).json()
    assert (
        result["status"] == "failed"
        and result["error_code"] == "EDITING_PLAN_ENDPOINT_CHANGED"
    )
    assert provider.calls == 0 and result["call_state"] == "not_submitted"


@pytest.mark.parametrize(
    ("template_id", "group_id", "required"),
    [
        ("picture-compare-v2", "CX-G07", 3),
        ("rotation-cards-v1", "CX-G04", 3),
        ("package-specs-v1", "Z-M12", 4),
    ],
)
def test_template_prepares_distinct_verified_project_images(
    video, tmp_path, monkeypatch, template_id, group_id, required
):
    client, _, ws, settings, _, task, semantic = setup(video, tmp_path, monkeypatch)
    factory = client.app.state.session_factory
    root = base(ws)
    route = root + f"/editing-tasks/{task['id']}/planning-tasks"
    material_route = root + f"/projects/{task['project_id']}/editing-materials"

    def upload(color):
        buffer = BytesIO()
        Image.new("RGB", (32, 32), color).save(buffer, format="PNG")
        return (
            client.post(
                material_route,
                data={
                    "request_id": str(uuid4()),
                    "label": color,
                    "description": "用途测试",
                },
                files={"file": ("item.png", buffer.getvalue(), "image/png")},
            )
            .raise_for_status()
            .json()["id"]
        )

    colors = ("red", "red", "blue", "green", "yellow")
    ids = [upload(color) for color in colors[: required + 1]]
    provider = Provider(semantic)
    for selected, count in (([], 0), (ids[:-1], required - 1), (ids, required)):
        new = (
            client.post(
                route,
                json={
                    "request_id": str(uuid4()),
                    "template_id": template_id,
                    "material_ids": selected,
                },
            )
            .raise_for_status()
            .json()
        )
        worker.process(new["id"], settings, factory, provider)
        task_route = root + "/editing-planning-tasks/" + new["id"]
        result = client.get(task_route).raise_for_status().json()
        expected = [
            {
                "group_id": group_id,
                "required_distinct_images": required,
                "selected_distinct_images": count,
            }
        ]
        assert result["status"] == "prepared", result
        assert result["project_image_requirements"] == expected
        artifact = (
            client.get(task_route + "/artifacts/request").raise_for_status().json()
        )
        assert artifact["runtime"]["project_image_requirements"] == expected
        assert artifact["overlay_template"]["slots"][0]["group_id"] == group_id
    assert provider.calls == 0


@pytest.mark.parametrize(
    ("template_id", "group_id", "required"),
    [("picture-compare-v2", "CX-G07", 3), ("package-specs-v1", "Z-M12", 4)],
)
def test_current_card_rejects_reused_project_bytes_and_presenter_slot(
    template_id, group_id, required
):
    template = overlay_template(template_id)
    source = {"id": "source-one", "kind": "original_video", "sha256": "source"}
    images = [
        {"id": f"material-{i}", "kind": "image", "sha256": digest}
        for i, digest in enumerate(("a", "a", "b", "c", "d")[: required + 1])
    ]

    def runtime(cards):
        return {
            "project_image_requirements": template_image_requirements(template, cards)
        }

    def plan(ids, group=group_id):
        tokens = "abcd"[:required]
        return SemanticPlan.model_validate(
            {
                "audience_question": "用途",
                "argument_outline": ["解释用途"],
                "style_reason": "按用途配图",
                "beats": [
                    {
                        "id": "cards",
                        "group_id": group,
                        "reason": "逐项说明",
                        "relation": "parallel",
                        "first_token_id": "a",
                        "last_token_id": tokens[-1],
                        "relation_items": [
                            {
                                "id": token,
                                "first_token_id": token,
                                "last_token_id": token,
                                "asset_ids": [asset],
                            }
                            for token, asset in zip(tokens, ids, strict=True)
                        ],
                    }
                ],
            }
        )

    cards = [source, *images]
    good = ["material-0", *(f"material-{i}" for i in range(2, required + 1))]
    validate_template_images(plan(good), runtime(cards), cards)
    with pytest.raises(ValueError, match="lacks distinct project images"):
        validate_template_images(plan(good), runtime(cards[:-1]), cards[:-1])
    for ids in (["material-0", "material-1", *good[2:]], ["source-one", *good[1:]]):
        with pytest.raises(ValueError, match="own project image"):
            validate_template_images(plan(ids), runtime(cards), cards)
    validate_template_images(plan(good, group="BG-S04"), runtime([source]), [source])
    validate_template_images(plan(good), {"version": "legacy"}, [])


def test_judgment_preparation_recognizes_only_meaningful_image_transparency(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, _, task, semantic = setup(video, tmp_path, monkeypatch)
    factory = client.app.state.session_factory
    root = base(ws)
    materials = []
    for alpha in (0, 255, 128):
        image = Image.new("RGBA", (20, 20), (100, 30, 20, alpha))
        if alpha == 128:
            image.putpixel((0, 0), (0, 0, 0, 0))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        response = client.post(
            root + f"/projects/{task['project_id']}/editing-materials",
            data={
                "request_id": str(uuid4()),
                "label": "本期说明图",
                "description": "透明素材测试",
            },
            files={"file": ("evidence.png", buffer.getvalue(), "image/png")},
        )
        materials.append(response.raise_for_status().json())
    created = (
        client.post(
            root + f"/editing-tasks/{task['id']}/planning-tasks",
            json={
                "request_id": str(uuid4()),
                "template_id": "evidence-judgment-v1",
                "material_ids": [m["id"] for m in materials],
            },
        )
        .raise_for_status()
        .json()
    )
    fixture = Provider(semantic)
    worker.process(created["id"], settings, factory, fixture)
    result = (
        client.get(root + "/editing-planning-tasks/" + created["id"])
        .raise_for_status()
        .json()
    )
    assert result["status"] == "prepared", result
    assert fixture.calls == 0
    assert result["project_image_requirements"] == [
        {
            "group_id": "W-R14",
            "required_distinct_images": 2,
            "selected_distinct_images": 3,
            "transparent_image_ids": [materials[2]["asset_id"]],
        }
    ]


def test_judgment_sound_follows_the_original_remapped_mark_frames(tmp_path):
    shot = {
        "group_id": "W-R14",
        "layer": "scene",
        "start_seconds": 0.410,
        "config": {
            "content": {"captions": []},
            "timing": {
                "events": {
                    "evidence_entries": [0.320, 0.500],
                    "check_in": 0.680,
                    "cross_in": 5.460,
                    "conclusion_in": 7.120,
                    "exit_in": 7.560,
                }
            },
        },
    }
    # The original uses t > 1.1/1.75 on the rounded virtual 30fps clock.
    # The much longer check-to-cross interval delays the first check pixels.
    assert judgment_entry_frame(shot, 30, JUDGMENT_EVENTS[2]) == 37
    assert judgment_entry_frame(shot, 30, JUDGMENT_EVENTS[3]) == 176
    with pytest.raises(ValueError, match="visible entry"):
        judgment_entry_frame(shot, 30, JUDGMENT_EVENTS[5])

    atomic_json(tmp_path / "episode.json", {"output": {"fps": 30}, "shots": [shot]})
    for path in ("voice.wav", "fx.wav", "fx-cues/0000.wav"):
        output = tmp_path / "audio" / path
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as stream:
            stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            stream.writeframes(bytes(96))
    seconds = 37 / 30
    cue = {
        "asset_id": "fixture",
        "asset_sha256": "source",
        "anchor_seconds": seconds,
        "onset_policy": "measured",
        "word_binding": {"path": JUDGMENT_EVENTS[2]},
        "judgment_entry": {
            "shot_index": 0,
            "event_path": JUDGMENT_EVENTS[2],
            "output_frame": 37,
        },
    }
    native = {
        "audio_signal": {"finite": True, "overload": False, "peak_dbfs": -20},
        "fx_receipt": {
            "sha256": sha256(tmp_path / "audio/fx.wav"),
            "events": [
                {
                    "index": 0,
                    "asset_id": "fixture",
                    "source_sha256": "source",
                    "anchor_basis": {"kind": "explicit_current_clock"},
                    "anchor_seconds": seconds,
                    "effective_onset_seconds": seconds,
                    "lead_removed_seconds": 0,
                    "processed_sha256": sha256(tmp_path / "audio/fx-cues/0000.wav"),
                }
            ],
        },
    }
    plan = {"fx": [cue], "music": []}
    assert (
        verify_rendered_sound(tmp_path, native, plan)["fx"][0][
            "effective_onset_seconds"
        ]
        == seconds
    )
    cue["judgment_entry"]["output_frame"] += 1
    with pytest.raises(ValueError, match="binding or measured onset"):
        verify_rendered_sound(tmp_path, native, plan)


def test_presenter_motion_preparation_rejects_duplicate_or_short_clips():
    template = overlay_template("presenter-reframing-v1")
    clip = {"id": "material-a", "kind": "video", "sha256": "a", "duration_ms": 900}
    second = {**clip, "id": "material-b"}
    unavailable = {}
    motion_blockers(template, "none", [clip, second], "source", unavailable)
    assert unavailable == {"YYP05": ["two_distinct_project_clips_required"]}
    second.update(sha256="b", duration_ms=499)
    unavailable = {}
    motion_blockers(template, "none", [clip, second], "source", unavailable)
    assert "YYP05" in unavailable
    second["duration_ms"] = 500
    unavailable = {}
    motion_blockers(template, "none", [clip, second], "source", unavailable)
    assert unavailable == {}
    motion_blockers(template, "present", [clip, second], "source", unavailable)
    assert unavailable == {f"YYP{i:02}": ["clean_source_required"] for i in range(1, 8)}


def test_azl_preparation_requires_distinct_assets_by_original_slot_count():
    template = overlay_template("azl-panels-v1")
    photo = {"id": "material-a", "kind": "image", "sha256": "a"}
    same = {**photo, "id": "material-b"}
    clip = {"id": "material-c", "kind": "video", "sha256": "c", "duration_ms": 1199}
    unavailable = {}
    azl_blockers(template, "none", [photo, same, clip], "source", unavailable)
    assert set(unavailable) == {"AZL02", "AZL04", "AZL05"}
    clip["duration_ms"] = 1200
    unavailable = {}
    azl_blockers(template, "none", [photo, same, clip], "source", unavailable)
    assert set(unavailable) == {"AZL04"}


def test_chenxi_preflight_preserves_native_video_and_paper_roles():
    template = overlay_template("chenxi-broll-v1")
    source = {
        "id": "material-source",
        "kind": "video",
        "sha256": "source",
        "duration_ms": 4000,
    }
    paper = {"id": "material-paper", "kind": "image", "sha256": "paper"}
    clip = {
        "id": "material-broll",
        "kind": "video",
        "sha256": "clip",
        "duration_ms": 2133,
    }
    unavailable = {}
    cxbr_blockers(template, "none", [source, clip], "source", unavailable)
    assert unavailable == {
        **dict.fromkeys(CXBR_PAPER_GROUPS, ["paper_image_required"]),
        "CXBR04": ["independent_video_required"],
    }
    clip["duration_ms"] = 2134
    unavailable = {}
    cxbr_blockers(template, "present", [source, clip, paper], "source", unavailable)
    assert unavailable == dict.fromkeys(CXBR_PURPOSES, ["clean_source_required"])
    unavailable = {}
    cxbr_blockers(template, "none", [source, paper], "source", unavailable)
    assert unavailable == dict.fromkeys(CXBR_PURPOSES, ["independent_video_required"])


def test_year_preparation_requires_a_continuous_measured_year():
    template = overlay_template(UNIFIED_EXPANDED_TEMPLATE_ID)
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=2500,
        provider="fixture",
        model="fixture",
        language="zh",
        tokens=[
            TranscriptToken(
                id=f"t{i}", text=text, start_ms=i * 100, end_ms=i * 100 + 80
            )
            for i, text in enumerate(("自", "二", "零", "二", "六", "年，", "测试"))
        ],
        utterances=[],
    )
    unavailable = {}
    require_spoken_year(template, transcript, unavailable)
    assert unavailable == {}
    transcript.tokens[2].text = "零，"
    unavailable = {"AH-S07": ["missing-original"]}
    require_spoken_year(template, transcript, unavailable)
    assert unavailable == {"AH-S07": ["missing-original", "spoken_year_required"]}
    unavailable = {}
    require_spoken_year(overlay_template(UNIFIED_TEMPLATE_ID), transcript, unavailable)
    assert unavailable == {}


def test_yy6_preparation_requires_measured_quantity_pairs_and_distinct_stills():
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=3000,
        provider="fixture",
        model="fixture",
        language="zh",
        tokens=[
            TranscriptToken(id=f"t{i}", text=text, start_ms=ms, end_ms=ms + 100)
            for i, (text, ms) in enumerate(
                [
                    ("谁", 100),
                    ("两", 200),
                    ("大", 300),
                    ("瓶，", 400),
                    ("三", 800),
                    ("斤", 1400),
                    ("一，", 1500),
                    ("件", 1600),
                ]
            )
        ],
        utterances=[],
    )
    image = {"id": "material-a", "kind": "image", "sha256": "a"}
    another = {**image, "id": "material-b"}
    template = overlay_template("yy-presenter-openings-v3")
    unavailable = {}
    inputs = yy6_scene_inputs(template, transcript, [image, another], unavailable)
    assert inputs["quantity_pairs"] == [{"count_token_id": "t1", "unit_token_id": "t3"}]
    assert unavailable == {"YY6O02": ["distinct_opening_backgrounds_required"]}
    unavailable = {}
    another["sha256"] = "b"
    no_quantity = transcript.model_copy(update={"tokens": transcript.tokens[4:]})
    yy6_scene_inputs(template, no_quantity, [image, another], unavailable)
    assert all(
        "measured_quantity_required" in unavailable[group] for group in YY6_GROUPS
    )
    assert "measured_question_required" in unavailable["YY6O01"]
