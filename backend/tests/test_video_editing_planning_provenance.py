"""Captured planning adoption protocol; no real model, media render or billing."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app import video_editing_planning_worker as planning_worker
from app.errors import ApiError
from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_native_plans import (
    frozen_plan_snapshot,
    register_gateway_plan,
)
from app.video_editing_planning_provenance import (
    verify_gateway_planning,
    verify_render_provenance,
)
from app.video_editing_task_models import (
    EditingArtifactRecord,
    EditingPlanningTaskRecord,
)
from tests.test_video_editing_native_plans import saved_plan, task_owner
from tests.test_video_editing_planning_tasks import (
    Provider,
    create,
    enable_fixture,
    prepare,
)
from tests.test_video_projects import base

pytest_plugins = ["tests.test_video_projects"]


def captured_job(video, tmp_path, monkeypatch):
    client, auth, ws, settings, source, task, semantic, recipes = saved_plan(
        video, tmp_path, monkeypatch
    )
    monkeypatch.setattr(planning_worker, "verify_package", lambda _: None)
    client.app.state.editing_planning_dispatcher = lambda _: None

    def protocol_request(transcript, package, model, cards, choices):
        # Explicit 132-group wire fixture; not a real Tengli result or library.
        payload = {
            "transcript": {
                "tokens": [{"id": t.id, "text": t.text} for t in transcript.tokens]
            },
            "full_library": read_json(package / "catalog/groups.json")["groups"],
            "available_project_materials": cards,
            "project_library_choices": choices,
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "protocol only"},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        encoded = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
        return body, {
            "request_sha256": hashlib.sha256(encoded).hexdigest(),
            "request_bytes": len(encoded),
            "catalog_group_count": 132,
            "model": model,
            "max_output_tokens": 5000,
        }

    monkeypatch.setattr(planning_worker.planner, "build_request", protocol_request)
    parent = prepare(client, ws, settings, task)
    enable_fixture(settings)
    job = create(client, ws, task["id"], "generate", parent["id"]).json()
    provider = Provider(semantic)
    planning_worker.process(
        job["id"], settings, client.app.state.session_factory, provider
    )
    assert provider.calls == 1  # Fake in-memory protocol provider only.
    settings.video_editing_planning_enabled = False
    settings.video_script_planning_enabled = False
    recipes.planning_origin = "tengli_gateway"
    return (
        client,
        ws,
        settings,
        source,
        task,
        semantic,
        recipes,
        job["id"],
        parent["id"],
    )


def register(client, ws, settings, task, recipes, planning_id, request_id=None):
    with client.app.state.session_factory() as session:
        return register_gateway_plan(
            session,
            settings,
            ws,
            task_owner(session, task["id"]),
            planning_id,
            request_id or str(uuid4()),
            recipes,
        )


def test_captured_result_adopts_once_and_passes_verified_hash_to_native_worker(
    video, tmp_path, monkeypatch
):
    client, ws, settings, source, task, semantic, recipes, job, parent = captured_job(
        video, tmp_path, monkeypatch
    )
    request_id = str(uuid4())
    row = register(client, ws, settings, task, recipes, job, request_id)
    assert row.origin == "tengli_gateway"
    assert row.details["planning_provenance"]["planning_task_id"] == job
    assert row.details["semantic_review"] == "unreviewed"
    assert register(client, ws, settings, task, recipes, job, request_id).id == row.id
    with client.app.state.session_factory() as session:
        artifact = session.get(EditingArtifactRecord, row.base_transcript_artifact_id)
        frozen = frozen_plan_snapshot(row, artifact)
        verified = verify_gateway_planning(
            session, settings, ws, row.owner_user_id, job
        )
        expected = hashlib.sha256(semantic.model_dump_json().encode()).hexdigest()
        assert verify_render_provenance(session, settings, frozen) == expected
        assert verified.semantic == semantic
        # Read-only adoption remains valid when current provider config changes.
        settings.video_script_base_url = "https://different.example.invalid"
        assert verify_render_provenance(session, settings, frozen) == expected
    response = client.get(base(ws) + f"/projects/{row.project_id}/editing-native-plans")
    assert response.json()[0]["origin"] == "tengli_gateway"
    assert "recipes" not in response.text and str(tmp_path) not in response.text
    settings.video_editing_native_plan_enabled = True
    submitted = client.post(
        base(ws) + "/editing-tasks",
        json={
            "request_id": str(uuid4()),
            "source_id": source,
            "options": {
                "mode": "native_plan",
                "native_plan_id": row.id,
                "source_subtitles": "none",
            },
        },
    )
    assert submitted.status_code == 200, submitted.text
    from app import video_editing_worker as worker
    from app.video_editing_pipeline import EditingFailure

    observed = []
    monkeypatch.setattr(worker, "verify_package", lambda _: None)
    monkeypatch.setattr(
        worker,
        "prepare",
        lambda *args: {
            "source_sha256": verified.transcript.source_sha256,
            "audio_sha256": verified.transcript.audio_sha256,
            "duration_ms": verified.transcript.duration_ms,
        },
    )

    def compile_probe(*args, **kwargs):
        observed.append(kwargs["verified_gateway_plan_hash"])
        raise EditingFailure("PROTOCOL_STOP_BEFORE_NATIVE_RENDER")

    monkeypatch.setattr(worker, "compile_episode", compile_probe)
    worker.process(submitted.json()["id"], settings, client.app.state.session_factory)
    assert observed == [expected]
    result = client.get(base(ws) + "/editing-tasks/" + submitted.json()["id"]).json()
    assert result["error_code"] == "PROTOCOL_STOP_BEFORE_NATIVE_RENDER"
    assert not result["artifacts"]  # No fixture is presented as a real video.


def test_prepared_or_other_owner_cannot_claim_model_provenance(
    video, tmp_path, monkeypatch
):
    client, ws, settings, _, task, _, recipes, job, parent = captured_job(
        video, tmp_path, monkeypatch
    )
    with client.app.state.session_factory() as session:
        owner = task_owner(session, task["id"])
        for planning_id, user, expected in (
            (parent, owner, "EDITING_PLANNING_RESULT_REQUIRED"),
            (job, "other-owner", "EDITING_PLANNING_NOT_FOUND"),
        ):
            with pytest.raises(ApiError) as error:
                verify_gateway_planning(session, settings, ws, user, planning_id)
            assert error.value.code == expected


@pytest.mark.parametrize(
    "changed",
    [
        "response",
        "receipt",
        "request",
        "intent",
        "transcript",
        "escape",
        "semantic",
        "parent",
        "prepared_file",
    ],
)
def test_changed_captures_cannot_be_adopted(video, tmp_path, monkeypatch, changed):
    client, ws, settings, _, task, _, recipes, job, _ = captured_job(
        video, tmp_path, monkeypatch
    )
    with client.app.state.session_factory() as session:
        row = session.get(EditingPlanningTaskRecord, job)
        if changed in {"response", "receipt", "request", "transcript"}:
            artifact = next(a for a in row.result["artifacts"] if a["role"] == changed)
            Path(artifact["path"]).write_text("{}", encoding="utf-8")
        elif changed == "intent":
            from app.video_editing_planning_store import planning_root

            intent = (
                planning_root(settings, job) / "provider/semantic-submit-intent.json"
            )
            atomic_json(intent, {**read_json(intent), "gateway": {"host": "other"}})
        elif changed == "escape":
            outside = tmp_path / "outside.json"
            atomic_json(outside, row.result["semantic"])
            row.result = {
                **row.result,
                "artifacts": [
                    {
                        **a,
                        "path": str(outside),
                        "sha256": sha256(outside),
                        "bytes": outside.stat().st_size,
                    }
                    if a["role"] == "semantic_plan"
                    else a
                    for a in row.result["artifacts"]
                ],
            }
        elif changed == "semantic":
            row.result = {
                **row.result,
                "semantic": {
                    **row.result["semantic"],
                    "audience_question": "unverified change",
                },
            }
        elif changed == "prepared_file":
            parent = session.get(EditingPlanningTaskRecord, row.prepared_task_id)
            artifact = next(
                a for a in parent.result["artifacts"] if a["role"] == "request"
            )
            Path(artifact["path"]).write_text("{}", encoding="utf-8")
        else:
            row.prepared_task_id = str(uuid4())
        session.commit()
    with pytest.raises(ApiError) as error:
        register(client, ws, settings, task, recipes, job)
    assert error.value.code == "EDITING_PLANNING_PROVENANCE_CHANGED"


def test_native_model_snapshot_cannot_change_source_or_semantic_or_origin(
    video, tmp_path, monkeypatch
):
    client, ws, settings, _, task, _, recipes, job, _ = captured_job(
        video, tmp_path, monkeypatch
    )
    row = register(client, ws, settings, task, recipes, job)
    with client.app.state.session_factory() as session:
        artifact = session.get(EditingArtifactRecord, row.base_transcript_artifact_id)
        native = frozen_plan_snapshot(row, artifact)
        for changed in (
            {**native, "source_id": "other-source"},
            {**native, "project_id": "other-project"},
            {**native, "planning_provenance": None},
            {**native, "asset_files": {}},
            {
                **native,
                "choice_snapshot": {**native["choice_snapshot"], "sha256": "0" * 64},
            },
            {
                **native,
                "semantic": {**native["semantic"], "audience_question": "changed"},
            },
            {**native, "origin": "operator_candidate"},
        ):
            with pytest.raises(ValueError):
                verify_render_provenance(session, settings, changed)


def test_changed_response_after_queued_adoption_stops_before_compile_or_fallback(
    video, tmp_path, monkeypatch
):
    from app import video_editing_worker as worker

    client, ws, settings, source, task, _, recipes, job, _ = captured_job(
        video, tmp_path, monkeypatch
    )
    row = register(client, ws, settings, task, recipes, job)
    settings.video_editing_native_plan_enabled = True
    submitted = client.post(
        base(ws) + "/editing-tasks",
        json={
            "request_id": str(uuid4()),
            "source_id": source,
            "options": {
                "mode": "native_plan",
                "native_plan_id": row.id,
                "source_subtitles": "none",
            },
        },
    )
    assert submitted.status_code == 200
    with client.app.state.session_factory() as session:
        planning = session.get(EditingPlanningTaskRecord, job)
        response = next(
            a for a in planning.result["artifacts"] if a["role"] == "response"
        )
        Path(response["path"]).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(worker, "verify_package", lambda _: None)
    monkeypatch.setattr(worker, "prepare", lambda *args: {})
    monkeypatch.setattr(worker, "load_plan_transcript", lambda *args: None)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Changed capture cannot compile, render, replan or use ASR"
        )

    for operation in (
        "compile_episode",
        "compile_baseline",
        "load_transcript",
        "native_export",
    ):
        monkeypatch.setattr(worker, operation, forbidden)
    worker.process(submitted.json()["id"], settings, client.app.state.session_factory)
    result = client.get(base(ws) + "/editing-tasks/" + submitted.json()["id"]).json()
    assert result["status"] == "failed" and result["artifacts"] == []
    assert result["error_code"] == "EDITING_PLANNER_PROVENANCE_REQUIRED"
