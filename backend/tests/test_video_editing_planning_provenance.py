"""Captured planning adoption protocol; no real model, media render or billing."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app import video_editing_planning_worker as planning_worker
from app.errors import ApiError
from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_contracts import SemanticPlan, TranscriptToken
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
    EditingNativePlanRecord,
    EditingPlanningTaskRecord,
    EditingTaskRecord,
)
from app.video_editing_transcript_store import read_transcript_artifact
from tests.test_video_editing_native_plans import saved_plan, task_owner
from tests.test_video_editing_planning_tasks import (
    Provider,
    create,
    enable_fixture,
    prepare,
)
from tests.test_video_projects import base

pytest_plugins = ["tests.test_video_projects"]


def captured_job(video, tmp_path, monkeypatch, template=False, missing_event=False):
    client, auth, ws, settings, source, task, semantic, recipes = saved_plan(
        video, tmp_path, monkeypatch
    )
    monkeypatch.setattr(planning_worker, "verify_package", lambda _: None)
    client.app.state.editing_planning_dispatcher = lambda _: None
    if template:
        package = settings.video_editing_library_dir
        catalog = read_json(package / "catalog/groups.json")
        events = {
            "AHG-S02": ("mark", "/events/mark/0", "/events/mark/1"),
            "SG-S09": ("enter_start", "/events/enter_start", "/events/enter_end"),
            "SG-S02": ("drop_frame", "/events/drop_frame", "/events/enter_end"),
            "SG-S06": ("upper_start", "/events/upper_start", "/events/enter_end"),
            "BG-S04": ("body_frame", "/events/body_frame", "/events/enter_end"),
        }
        for row, (gid, (name, _, _)) in zip(
            catalog["groups"][1:6], events.items(), strict=True
        ):
            row.update(id=gid, input_template=f"{gid}.json")
            atomic_json(
                package / row["input_template"],
                {
                    **read_json(package / "effect.json"),
                    "group_id": gid,
                    "events": (
                        {"mark": [2, 10]}
                        if gid == "AHG-S02"
                        else {name: 2, "enter_end": 10}
                    ),
                },
            )
        atomic_json(package / "catalog/groups.json", catalog)
        with client.app.state.session_factory() as session:
            stored = session.get(EditingTaskRecord, task["id"])
            artifact = session.scalar(
                select(EditingArtifactRecord).where(
                    EditingArtifactRecord.task_id == stored.id,
                    EditingArtifactRecord.role == "transcript",
                )
            )
            transcript = read_transcript_artifact(
                artifact, stored, settings.video_editing_tasks_dir
            )
            transcript.tokens = [
                TranscriptToken(
                    id=f"v{i}", text=gid, start_ms=i * 500, end_ms=(i + 1) * 500
                )
                for i, gid in enumerate([*events, next(iter(events))])
            ]
            atomic_json(Path(artifact.path), transcript.model_dump(mode="json"))
            artifact.sha256, artifact.bytes = (
                sha256(Path(artifact.path)),
                Path(artifact.path).stat().st_size,
            )
            session.commit()
        semantic = SemanticPlan.model_validate(
            {
                **semantic.model_dump(mode="json"),
                "beats": [
                    {
                        "id": f"beat-{i}",
                        "group_id": token.text,
                        "relation": "explanation",
                        "first_token_id": token.id,
                        "last_token_id": token.id,
                        "reason": "wire fixture",
                        "native_text": [
                            {
                                "path": "/content/text",
                                "first_token_id": token.id,
                                "last_token_id": token.id,
                            }
                        ],
                        "native_events": [
                            {"path": path, "token_id": token.id, "edge": edge}
                            for path, edge in zip(
                                events[token.text][1:], ("start", "end"), strict=True
                            )
                        ][1 if missing_event and i == 0 else 0 :],
                    }
                    for i, token in enumerate(transcript.tokens)
                ],
            }
        )

    def protocol_request(transcript, package, model, cards, choices, template=None):
        # Explicit 132-group wire fixture; not a real Tengli result or library.
        payload = {
            "transcript": {
                "tokens": [{"id": t.id, "text": t.text} for t in transcript.tokens]
            },
            "full_library": read_json(package / "catalog/groups.json")["groups"],
            "available_project_materials": cards,
            "project_library_choices": choices,
            **({"overlay_template": template} if template else {}),
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
    if template:
        response = client.post(
            base(ws) + f"/editing-tasks/{task['id']}/planning-tasks",
            json={"request_id": str(uuid4()), "template_id": "label-compare-v1"},
        )
        assert response.status_code == 200, response.text
        parent = response.json()
        planning_worker.process(
            parent["id"], settings, client.app.state.session_factory
        )
    else:
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


@pytest.mark.parametrize("missing_event", [False, True])
def test_overlay_candidate_endpoint_uses_frozen_words_and_replays_without_model(
    video, tmp_path, monkeypatch, missing_event
):
    client, ws, settings, _, task, semantic, _, job, parent = captured_job(
        video, tmp_path, monkeypatch, template=True, missing_event=missing_event
    )
    settings.video_editing_native_plan_enabled = True
    path = base(ws) + "/editing-planning-tasks/{}/native-candidate"
    assert (
        client.post(path.format(parent)).json()["error"]["code"]
        == "EDITING_PLANNING_RESULT_REQUIRED"
    )
    assert client.post(path.format(uuid4())).status_code == 404
    response = client.post(path.format(job))
    if missing_event:
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "EDITING_TEMPLATE_ANCHORS_REQUIRED"
        return
    assert response.status_code == 200, response.text
    candidate = response.json()
    assert candidate["overlay_template"]["id"] == "label-compare-v1"
    assert candidate["continuous_preview_available"] and len(candidate["beats"]) == 6
    assert candidate["music_edit_available"]
    assert "recipes" not in candidate
    assert client.post(path.format(job)).json()["id"] == candidate["id"]
    with client.app.state.session_factory() as session:
        native = session.get(EditingNativePlanRecord, candidate["id"])
        assert native.semantic == semantic.model_dump(mode="json")
        assert native.recipes["entries"]["beat-0"]["recipe"]["config"]["content"] == {
            "text": None
        }
        assert native.details["planning_provenance"]["base_task_id"] == task["id"]
        assert native.recipes["sound_mode"] == "native_mix"
        sound = native.recipes["sound"]
        assert sound["voice_gain_db"] == 0 and len(sound["music"]) == 1
        assert [cue["beat_id"] for cue in sound["fx"]] == [b.id for b in semantic.beats]
        assert (
            sound["fx"][0]["event_path"]
            == sound["fx"][-1]["event_path"]
            == "/events/mark/0"
        )
        assert sound["fx"][0]["asset_id"] == sound["fx"][-1]["asset_id"]


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
