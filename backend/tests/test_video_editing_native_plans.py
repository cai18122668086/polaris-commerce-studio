"""Frozen plan ownership, idempotence and fail-closed provenance; no real renderer."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.errors import ApiError
from app.motion_library import atomic_json, sha256
from app.video_editing_catalog import choice_snapshot_hash
from app.video_editing_contracts import EditingOptions
from app.video_editing_native_plans import register_operator_plan
from app.video_editing_task_models import EditingTaskRecord
from app.video_editing_worker import load_plan_transcript
from tests.test_video_editing_transcript_revisions import completed_transcript
from tests.test_video_projects import base

pytest_plugins = ["tests.test_video_projects"]


def saved_plan(video, tmp_path, monkeypatch):
    from tests.test_video_editing_episode_compiler import protocol

    client, auth, ws, settings, source, task, artifact, file = completed_transcript(
        video, tmp_path
    )
    # Exercise the real planner/132-group contract with protocol-only fixture data.
    root, package, prepared, transcript, semantic, recipe, _, _ = protocol(
        tmp_path / "protocol"
    )
    from app.video_editing_task_models import EditingArtifactRecord, EditingSourceRecord

    with client.app.state.session_factory() as session:
        src = session.get(EditingSourceRecord, source)
        transcript.source_sha256 = src.media_sha256
        recipe.source_sha256 = src.media_sha256
        atomic_json(file, transcript.model_dump(mode="json"))
        record = session.get(EditingArtifactRecord, artifact)
        record.sha256, record.bytes = sha256(file), file.stat().st_size
        row = session.get(EditingTaskRecord, task["id"])
        row.options = {**row.options, "source_subtitles": "none"}
        session.commit()
        recipe.transcript_sha256 = record.sha256
    settings.video_editing_library_dir = package
    (package / "adapter.py").write_text("# protocol fixture, never executed\n")
    return client, auth, ws, settings, source, task, semantic, recipe


def test_saved_plan_replay_scoping_and_render_option_gates(
    video, tmp_path, monkeypatch
):
    client, auth, ws, settings, source, task, semantic, recipe = saved_plan(
        video, tmp_path, monkeypatch
    )
    request = str(uuid4())
    with client.app.state.session_factory() as session:
        row = register_operator_plan(
            session,
            settings,
            ws,
            task_owner(session, task["id"]),
            task["id"],
            request,
            semantic,
            recipe,
        )
        plan_id, pid = row.id, row.project_id
        assert (
            register_operator_plan(
                session,
                settings,
                ws,
                row.owner_user_id,
                task["id"],
                request,
                semantic,
                recipe,
            ).id
            == plan_id
        )
        changed = semantic.model_copy(update={"audience_question": "changed"})
        with pytest.raises(ApiError) as error:
            register_operator_plan(
                session,
                settings,
                ws,
                row.owner_user_id,
                task["id"],
                request,
                changed,
                recipe,
            )
        assert error.value.code == "EDITING_NATIVE_PLAN_REQUEST_REUSED"
        with pytest.raises(ApiError):
            register_operator_plan(
                session,
                settings,
                ws,
                "another-owner",
                task["id"],
                str(uuid4()),
                semantic,
                recipe,
            )
        with pytest.raises(ApiError) as error:
            register_operator_plan(
                session,
                settings,
                ws,
                row.owner_user_id,
                task["id"],
                str(uuid4()),
                semantic,
                recipe.model_copy(update={"planning_origin": "tengli_gateway"}),
            )
        assert error.value.code == "EDITING_PLANNER_PROVENANCE_REQUIRED"
    view = client.get(base(ws) + f"/projects/{pid}/editing-native-plans")
    assert view.status_code == 200, view.text
    assert view.json()[0]["origin"] == "operator_candidate"
    assert view.json()[0]["semantic_review"] == "unreviewed"
    assert view.json()[0]["beats"][0]["source_only_available"]
    assert not view.json()[0]["music_edit_available"]
    assert str(tmp_path) not in view.text and "recipes" not in view.text
    body = {
        "request_id": str(uuid4()),
        "source_id": source,
        "options": {
            "mode": "native_plan",
            "native_plan_id": plan_id,
            "source_subtitles": "none",
        },
    }
    url = base(ws) + "/editing-tasks"
    assert client.post(url, json=body).status_code == 503
    settings.video_editing_native_plan_enabled = True
    result = client.post(url, json=body)
    assert result.status_code == 200, result.text
    assert client.post(url, json=body).json()["id"] == result.json()["id"]
    assert "native_edits" not in result.json()["options"]
    preview = client.post(
        url,
        json={
            **body,
            "request_id": str(uuid4()),
            "options": {**body["options"], "delivery": "preview_first"},
        },
    )
    assert preview.status_code == 422
    assert preview.json()["error"]["code"] == "EDITING_CONTINUOUS_COMBINATION_REQUIRED"
    edited = {
        **body,
        "request_id": str(uuid4()),
        "options": {
            **body["options"],
            "native_edits": {"source_only_beat_ids": [semantic.beats[0].id]},
        },
    }
    accepted = client.post(url, json=edited)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["options"]["native_edits"]["source_only_beat_ids"] == [
        semantic.beats[0].id
    ]
    assert client.post(url, json=edited).json()["id"] == accepted.json()["id"]
    for change in ({"music": "off"}, {"source_only_beat_ids": ["other-plan-beat"]}):
        invalid = client.post(
            url,
            json={
                **edited,
                "request_id": str(uuid4()),
                "options": {**body["options"], "native_edits": change},
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "EDITING_NATIVE_EDITS_INVALID"
        conflict = client.post(
            url, json={**edited, "options": {**body["options"], "native_edits": change}}
        )
        assert conflict.json()["error"]["code"] == "EDITING_REQUEST_REUSED"
    assert (
        client.post(
            url,
            json={
                **body,
                "request_id": str(uuid4()),
                "options": {**body["options"], "source_subtitles": "present"},
            },
        ).json()["error"]["code"]
        == "EDITING_NATIVE_OPTIONS_CHANGED"
    )
    from app.video_editing_task_models import EditingNativePlanRecord

    with client.app.state.session_factory() as session:
        row = session.get(EditingNativePlanRecord, plan_id)
        data = {**row.choice_snapshot, "notes": [{"changed": True}]}
        row.choice_snapshot = {**data, "sha256": choice_snapshot_hash(data)}
        session.commit()
    assert (
        client.post(url, json={**body, "request_id": str(uuid4())}).json()["error"][
            "code"
        ]
        == "EDITING_CHOICES_CHANGED_REPLAN_REQUIRED"
    )


def task_owner(session, task_id):
    return session.get(EditingTaskRecord, task_id).owner_user_id


def test_continuous_combinations_count_types_allow_repetition_and_reject_scene_layers():
    from app.video_editing_overlay_templates import MIN_OVERLAY_TYPES, overlay_template
    from app.video_editing_render_edits import continuous_overlay_groups

    chosen = overlay_template("roll-compare-v1")
    groups = {slot["group_id"] for slot in chosen["slots"]}
    sampled = sorted(groups)[:MIN_OVERLAY_TYPES]
    sequence = [*sampled, sampled[0], sampled[0], "Z-M00"]
    beats = [{"id": f"beat-{i}", "group_id": group} for i, group in enumerate(sequence)]
    entries = {beat["id"]: {"placement": {"layer": "subtitle"}} for beat in beats[:-1]}
    semantic, recipes = {"beats": beats}, {"entries": entries}
    assert continuous_overlay_groups(semantic, recipes, groups) == set(sampled)
    assert (
        len(continuous_overlay_groups(semantic, recipes, groups, {"beat-1"}))
        == MIN_OVERLAY_TYPES - 1
    )
    entries["beat-2"]["placement"]["layer"] = "scene"
    assert not continuous_overlay_groups(semantic, recipes, groups)


def test_continuous_hypit_inset_needs_internal_access_and_speaker_clearance():
    from app.video_editing_hypit_strips import PRICE_CARD_INSET_TYPE
    from app.video_editing_render_edits import continuous_overlay_groups

    semantic = {"beats": [{"id": "card", "group_id": "HY-A6"}]}
    entry = {
        "placement": {"layer": "overlay", "rect": [0.13, 0.435, 0.74, 0.41]},
        "recipe": {"group_id": "HY-A6", "price_card_layout": PRICE_CARD_INSET_TYPE},
    }
    portrait = {"id": "centered-portrait", "rect": [0.35, 0.09, 0.34, 0.34]}
    recipes = {"entries": {"card": entry}, "protected_regions": [portrait]}
    assert not continuous_overlay_groups(semantic, recipes, set())
    assert continuous_overlay_groups(
        semantic, recipes, set(), allow_hypit_insets=True
    ) == {"HY-A6"}
    portrait["rect"][3] = 0.42
    assert not continuous_overlay_groups(
        semantic, recipes, set(), allow_hypit_insets=True
    )
    portrait["rect"][3] = 0.34
    entry["recipe"].pop("price_card_layout")
    assert not continuous_overlay_groups(
        semantic, recipes, set(), allow_hypit_insets=True
    )


def test_corrupt_frozen_plan_fails_without_asr_or_plain_subtitle_fallback(
    video, tmp_path, monkeypatch
):
    from app import video_editing_worker as worker
    from app.video_editing_task_models import EditingNativePlanRecord

    client, _, ws, settings, source, task, semantic, recipe = saved_plan(
        video, tmp_path, monkeypatch
    )
    settings.video_editing_native_plan_enabled = True
    with client.app.state.session_factory() as session:
        plan = register_operator_plan(
            session,
            settings,
            ws,
            task_owner(session, task["id"]),
            task["id"],
            str(uuid4()),
            semantic,
            recipe,
        )
        plan_id = plan.id
    submitted = client.post(
        base(ws) + "/editing-tasks",
        json={
            "request_id": str(uuid4()),
            "source_id": source,
            "options": {
                "mode": "native_plan",
                "native_plan_id": plan_id,
                "source_subtitles": "none",
            },
        },
    )
    assert submitted.status_code == 200
    with client.app.state.session_factory() as session:
        row = session.get(EditingNativePlanRecord, plan_id)
        row.semantic_sha256 = "0" * 64
        session.commit()
    monkeypatch.setattr(worker, "verify_package", lambda _: None)
    monkeypatch.setattr(worker, "prepare", lambda *args: {})

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid saved plan must not use ASR or baseline fallback")

    monkeypatch.setattr(worker, "load_transcript", forbidden)
    monkeypatch.setattr(worker, "compile_baseline", forbidden)
    worker.process(submitted.json()["id"], settings, client.app.state.session_factory)
    result = client.get(base(ws) + "/editing-tasks/" + submitted.json()["id"]).json()
    assert result["status"] == "failed"
    assert result["error_code"] == "EDITING_NATIVE_PLAN_NOT_FOUND"
    assert result["attempts"] == 1 and result["artifacts"] == []


def test_native_mode_cannot_mix_revision_or_missing_plan():
    for data in (
        {"mode": "native_plan"},
        {"native_plan_id": str(uuid4())},
        {
            "mode": "native_plan",
            "native_plan_id": str(uuid4()),
            "transcript_revision_id": str(uuid4()),
        },
    ):
        with pytest.raises(ValueError):
            EditingOptions.model_validate(data)


def test_plan_transcript_loader_requires_exact_owned_measured_bytes(tmp_path):
    from app.video_editing_pipeline import EditingFailure
    from tests.test_video_editing_episode_compiler import protocol

    parent, _, prepared, transcript, _, _, settings, _ = protocol(tmp_path)
    settings.video_editing_tasks_dir = parent.parent
    target = tmp_path / "attempt"
    target.mkdir()
    frozen = {
        "id": str(uuid4()),
        "origin": "operator_candidate",
        "base_task_id": parent.name,
        "base_transcript_path": str(parent / "transcript.json"),
        "base_transcript_sha256": sha256(parent / "transcript.json"),
        "source_sha256": prepared["source_sha256"],
        "audio_sha256": prepared["audio_sha256"],
    }
    result = load_plan_transcript(target, prepared, frozen, settings)
    assert result == transcript
    assert sha256(target / "transcript.json") == frozen["base_transcript_sha256"]
    with pytest.raises(EditingFailure):
        load_plan_transcript(
            target, prepared, {**frozen, "base_transcript_sha256": "0" * 64}, settings
        )


def test_native_plan_migration_roundtrip(tmp_path):
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261109_0046_editing_native_plans.py"
    )
    spec = importlib.util.spec_from_file_location("native_plan_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'plans.db'}")
    with engine.begin() as connection:
        for table in (
            "users",
            "workspaces",
            "video_projects",
            "video_editing_sources",
            "video_editing_tasks",
            "video_editing_artifacts",
        ):
            connection.execute(
                text(f"CREATE TABLE {table} (id VARCHAR(40) PRIMARY KEY)")
            )
        connection.execute(text("INSERT INTO users VALUES ('preserved')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert (
            len(
                inspect(connection).get_unique_constraints("video_editing_native_plans")
            )
            == 1
        )
        migration.downgrade()
        assert connection.scalar(text("SELECT id FROM users")) == "preserved"
    engine.dispose()
