"""Frozen plan ownership, idempotence and fail-closed provenance; no real renderer."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.config import Settings
from app.errors import ApiError
from app.motion_library import atomic_json, sha256
from app.video_editing_catalog import choice_snapshot_hash
from app.video_editing_contracts import EditingOptions
from app.video_editing_native_plans import register_operator_plan
from app.video_editing_pipeline import EditingFailure, native_export
from app.video_editing_preview_base import preview_base_attempt
from app.video_editing_task_models import (
    EditingArtifactRecord,
    EditingNativePlanRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from app.video_editing_worker import load_plan_transcript
from tests.test_auth_external import verified_identity
from tests.test_video_editing_transcript_revisions import completed_transcript
from tests.test_video_projects import base, payload

pytest_plugins = ["tests.test_video_projects"]


@pytest.mark.parametrize(
    ("shot", "expected", "beat"),
    [
        (0, "EDITING_EFFECT_LAYOUT_FAILED", "replacement"),
        (1, "EDITING_NATIVE_LAYOUT_FAILED", "first-plan"),
        (2, "EDITING_NATIVE_EXPORT_FAILED", None),
    ],
)
def test_native_export_identifies_layout_failure_on_the_measured_shot(
    tmp_path, monkeypatch, shot, expected, beat
):
    def reject_export(*args):
        if args[-1] == "native_export":
            raise EditingFailure("EDITING_NATIVE_EXPORT_FAILED")

    monkeypatch.setattr("app.video_editing_pipeline.run", reject_export)
    atomic_json(
        tmp_path / "compile-diagnostics.json",
        {
            "applied_effect_edits": [
                {
                    "beat_id": "replacement",
                    "shot_index": 0,
                    "applied_group_id": "BG-S02",
                }
            ],
            "compiled_native_jobs": [
                {"beat_id": "first-plan", "shot_index": 1, "group_id": "BG-S02"}
            ],
        },
    )
    atomic_json(
        tmp_path / "episode.json",
        {"shots": [{"group_id": "BG-S02"}, {"group_id": "BG-S02"}]},
    )
    settings = Settings(_env_file=None)
    atomic_json(
        tmp_path / "layout/review.json",
        {"status": "failed", "errors": [{"shot": shot, "seconds": 3.1833333333}]},
    )
    with pytest.raises(EditingFailure, match=expected) as error:
        native_export(tmp_path, settings, lambda: None)
    if beat is None:
        assert error.value.layout_findings is None
    else:
        (finding,) = error.value.layout_findings
        assert finding.beat_id == beat and finding.first_ms == 3183
        assert finding.group_id == "BG-S02" and finding.finding_count == 1


def test_preview_base_is_bound_to_the_exact_artifact_source_and_plan(video, tmp_path):
    client, _, _, settings, source_id, parent, _, _ = completed_transcript(
        video, tmp_path
    )
    plan_id, artifact_id = str(uuid4()), str(uuid4())
    root = (settings.video_editing_tasks_dir / parent["id"] / "ab12cd34").resolve()
    preview = root / "outputs/preview.mp4"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"fixture for preview identity")
    base = {
        "task_id": parent["id"],
        "preview_artifact_id": artifact_id,
        "preview_sha256": sha256(preview),
    }
    options = {"preview_base": base, "native_plan_id": plan_id}
    with client.app.state.session_factory() as session:
        source = session.get(EditingSourceRecord, source_id)
        task = session.get(EditingTaskRecord, parent["id"])
        task.options = {
            **task.options,
            "native_plan_id": plan_id,
            "delivery": "preview_first",
        }
        session.add(
            EditingArtifactRecord(
                id=artifact_id,
                task_id=task.id,
                role="preview",
                path=str(preview),
                mime="video/mp4",
                sha256=base["preview_sha256"],
                bytes=preview.stat().st_size,
                validation={"decoded": True},
            )
        )
        session.commit()
        assert preview_base_attempt(session, settings, source, options) == root
        assert (
            preview_base_attempt(
                session, settings, source, {**options, "native_plan_id": str(uuid4())}
            )
            is None
        )
        owner = source.owner_user_id
        source.owner_user_id = "foreign-owner"
        assert preview_base_attempt(session, settings, source, options) is None
        source.owner_user_id = owner
        preview.write_bytes(b"X" * preview.stat().st_size)
        assert preview_base_attempt(session, settings, source, options) is None


def saved_plan(video, tmp_path, monkeypatch):
    from tests.test_video_editing_episode_compiler import protocol

    client, auth, ws, settings, source, task, artifact, file = completed_transcript(
        video, tmp_path
    )
    # Exercise the real planner/132-group contract with protocol-only fixture data.
    root, package, prepared, transcript, semantic, recipe, _, _ = protocol(
        tmp_path / "protocol"
    )
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
    with client.app.state.session_factory() as session:
        row = session.get(EditingNativePlanRecord, plan_id)
        original_choices = row.choice_snapshot
        data = {**original_choices, "notes": [{"changed": True}]}
        row.choice_snapshot = {**data, "sha256": choice_snapshot_hash(data)}
        session.commit()
    assert (
        client.post(url, json={**body, "request_id": str(uuid4())}).json()["error"][
            "code"
        ]
        == "EDITING_CHOICES_CHANGED_REPLAN_REQUIRED"
    )
    with client.app.state.session_factory() as session:
        row = session.get(EditingNativePlanRecord, plan_id)
        row.choice_snapshot = original_choices
        row.recipes = {**row.recipes, "overlay_template_id": "retired-combination-v1"}
        session.commit()
    view = (
        client.get(
            base(ws) + f"/projects/{pid}/editing-native-plans",
            params={"include_plan_id": plan_id},
        )
        .raise_for_status()
        .json()[0]
    )
    assert view["id"] == plan_id and not view["render_available"]
    assert any("retired-combination-v1" in text for text in view["warnings"])
    assert (
        client.post(url, json={**body, "request_id": str(uuid4())}).json()["error"][
            "code"
        ]
        == "EDITING_TEMPLATE_CHANGED"
    )


def test_template_sample_uses_latest_intact_confirmed_project_master(
    video, tmp_path, monkeypatch
):
    client, auth, ws, settings, source, task, semantic, recipe = saved_plan(
        video, tmp_path, monkeypatch
    )
    template = "subtitle-story-v1"
    task_url = base(ws) + "/editing-tasks"
    cases = ("intact", "corrupt", "unconfirmed", "too_few", "waiting", "direct")
    task_ids = [
        client.post(task_url, json={"request_id": str(uuid4()), "source_id": source})
        .raise_for_status()
        .json()["id"]
        for _ in cases
    ]
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
        project = plan.project_id
        plan.recipes = {**plan.recipes, "overlay_template_id": template}
        for index, (case, tid) in enumerate(zip(cases, task_ids, strict=True)):
            row = session.get(EditingTaskRecord, tid)
            path = settings.video_editing_tasks_dir / tid / "master.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"master fixture")
            aid, digest = str(uuid4()), sha256(path)
            row.created_at = datetime(2026, 11, 9, 6, index, tzinfo=UTC)
            row.options = {
                **row.options,
                "mode": "native_plan",
                "native_plan_id": plan.id,
                "delivery": "direct" if case == "direct" else "preview_first",
            }
            row.status = "awaiting_review" if case == "waiting" else "completed"
            if case != "unconfirmed":
                row.checkpoint = {
                    "export_confirmation": {"final_id": aid, "final_sha256": digest}
                }
            session.add(
                EditingArtifactRecord(
                    id=aid,
                    task_id=tid,
                    role="final",
                    path=str(path),
                    mime="video/mp4",
                    sha256=digest,
                    bytes=path.stat().st_size,
                    duration_ms=2000,
                    validation={
                        "decoded": True,
                        "motion_counts": {
                            "distinct_groups": 4 if case == "too_few" else 5,
                            "occurrences": 6,
                        },
                    },
                )
            )
            if case == "corrupt":
                path.write_bytes(b"x" * path.stat().st_size)
        session.commit()

    url = base(ws) + f"/projects/{project}/editing-template-samples"
    (sample,) = client.get(url).raise_for_status().json()
    assert (sample["template_id"], sample["task_id"]) == (template, task_ids[0])
    assert sample["motion_counts"] == {"distinct_groups": 5, "occurrences": 6}
    media = client.get(sample["final"]["url"], headers={"Range": "bytes=0-5"})
    assert (media.status_code, media.content) == (206, b"master")
    other_project = base(ws) + f"/projects/{uuid4()}"
    client.put(other_project, json=payload()).raise_for_status()
    assert client.get(other_project + "/editing-template-samples").json() == []
    auth.identity = verified_identity(
        primary_user_id="template-sample-other", email="1474953130@qq.com"
    )
    assert client.get(url).status_code in {403, 404}


def test_hypit_preflight_controls_saved_plan_and_submission(
    video, tmp_path, monkeypatch
):
    from app import video_editing_hypit as hypit

    client, _, ws, settings, source, task, semantic, recipe = saved_plan(
        video, tmp_path, monkeypatch
    )
    settings.video_editing_native_plan_enabled = True
    with client.app.state.session_factory() as session:
        row = register_operator_plan(
            session,
            settings,
            ws,
            task_owner(session, task["id"]),
            task["id"],
            str(uuid4()),
            semantic,
            recipe,
        )
        plan_id, project_id = row.id, row.project_id
        # This protocol fixture only tests admission and never reaches the renderer.
        beats = row.semantic["beats"]
        row.semantic = {
            **row.semantic,
            "beats": [{**beats[0], "group_id": "HY-A2"}, *beats[1:]],
        }
        session.commit()

    def unavailable(*_):
        raise hypit.HypitToolchainError(hypit.HYPIT_RUNTIME_UNAVAILABLE, "changed")

    monkeypatch.setattr(hypit, "hypit_tools", unavailable)
    view = (
        client.get(base(ws) + f"/projects/{project_id}/editing-native-plans")
        .raise_for_status()
        .json()[0]
    )
    assert not view["render_available"]
    assert (
        hypit.HYPIT_BLOCKER_MESSAGES[hypit.HYPIT_RUNTIME_UNAVAILABLE]
        in view["warnings"]
    )
    body = {
        "request_id": str(uuid4()),
        "source_id": source,
        "options": {
            "mode": "native_plan",
            "native_plan_id": plan_id,
            "source_subtitles": "none",
        },
    }
    rejected = client.post(base(ws) + "/editing-tasks", json=body)
    assert rejected.status_code == 503
    assert rejected.json()["error"]["code"] == hypit.HYPIT_RUNTIME_UNAVAILABLE
    body["options"]["native_edits"] = {"source_only_beat_ids": [semantic.beats[0].id]}
    assert client.post(base(ws) + "/editing-tasks", json=body).status_code == 200


def task_owner(session, task_id):
    return session.get(EditingTaskRecord, task_id).owner_user_id


@pytest.mark.parametrize("registered", [False, True])
def test_saved_plan_rechecks_exact_dependencies_and_allows_explicit_source_only(
    video, tmp_path, monkeypatch, registered
):
    client, _, ws, settings, source, task, semantic, recipe = saved_plan(
        video, tmp_path, monkeypatch
    )
    settings.video_editing_native_plan_enabled = True
    font_id = "font-frozen-test"
    original = tmp_path / "original.ttf"
    original.write_bytes(b"original")
    atomic_json(
        settings.video_editing_library_dir / "catalog/external-resources.json",
        {
            "resources": [
                {
                    "id": font_id,
                    "kind": "font",
                    "bytes": original.stat().st_size,
                    "sha256": sha256(original),
                }
            ]
        },
    )
    dependency_recipe = {"dependency_bindings": {font_id: str(original)}}
    if registered:
        manifest = tmp_path / "bindings.json"
        atomic_json(manifest, {"resources": {font_id: str(original)}})
        settings.video_editing_native_bindings_file = manifest
        dependency_recipe = {"dependency_ids": [font_id]}
    beat_id = semantic.beats[0].id
    with client.app.state.session_factory() as session:
        row = register_operator_plan(
            session,
            settings,
            ws,
            task_owner(session, task["id"]),
            task["id"],
            str(uuid4()),
            semantic,
            recipe,
        )
        plan_id, project_id = row.id, row.project_id
        recipes = row.recipes
        previous = recipes["entries"][beat_id]
        entry = {**previous, "recipe": {**previous["recipe"], **dependency_recipe}}
        row.recipes = {**recipes, "entries": {**recipes["entries"], beat_id: entry}}
        session.commit()

    listing = base(ws) + f"/projects/{project_id}/editing-native-plans"
    url = base(ws) + "/editing-tasks"
    body = {
        "request_id": str(uuid4()),
        "source_id": source,
        "options": {
            "mode": "native_plan",
            "native_plan_id": plan_id,
            "source_subtitles": "none",
        },
    }
    assert "dependency_blocker" not in client.get(listing).json()[0]["beats"][0]
    original.write_bytes(b"modified")
    view = client.get(listing).raise_for_status()
    assert str(tmp_path) not in view.text
    assert font_id in view.json()[0]["beats"][0]["dependency_blocker"]
    rejected = client.post(url, json=body)
    assert rejected.status_code == 503, rejected.text
    assert (
        rejected.json()["error"]["code"]
        == "EDITING_ORIGINAL_NATIVE_DEPENDENCY_REQUIRED"
    )
    assert (
        client.post(
            url,
            json={
                **body,
                "options": {
                    **body["options"],
                    "native_edits": {"source_only_beat_ids": [beat_id]},
                },
            },
        ).status_code
        == 200
    )
    original.write_bytes(b"original")
    assert "dependency_blocker" not in client.get(listing).json()[0]["beats"][0]
    assert (
        client.post(url, json={**body, "request_id": str(uuid4())}).status_code == 200
    )


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


def test_continuous_cards_require_the_audited_full_canvas_alpha_export():
    from app.video_editing_browser_clocks import CARD_GROUP
    from app.video_editing_render_edits import continuous_overlay_groups

    semantic = {"beats": [{"id": "card", "group_id": CARD_GROUP}]}
    recipe = {"group_id": CARD_GROUP, "browser_live_background": True}
    placement = {"layer": "overlay", "rect": [0, 0, 1, 1]}
    recipes = {"entries": {"card": {"placement": placement, "recipe": recipe}}}
    assert not continuous_overlay_groups(semantic, recipes, set())
    assert continuous_overlay_groups(
        semantic, recipes, set(), scene_groups={CARD_GROUP}
    ) == {CARD_GROUP}
    recipe.pop("browser_live_background")
    assert not continuous_overlay_groups(
        semantic, recipes, set(), scene_groups={CARD_GROUP}
    )
    placement["layer"] = "scene"
    assert continuous_overlay_groups(
        semantic, recipes, set(), scene_groups={CARD_GROUP}
    ) == {CARD_GROUP}


def test_continuous_azl_panel_requires_its_frozen_website_projection():
    from app.video_editing_azl_panels import AZL_DESIGN_ID, AZL_RECT, AZL_TEMPLATE_ID
    from app.video_editing_render_edits import continuous_overlay_groups

    semantic = {"beats": [{"id": "board", "group_id": "AZL01"}]}
    placement = {"layer": "scene", "rect": list(AZL_RECT)}
    recipe = {"group_id": "AZL01", "design_id": AZL_DESIGN_ID}
    recipes = {
        "overlay_template_id": AZL_TEMPLATE_ID,
        "entries": {"board": {"placement": placement, "recipe": recipe}},
    }
    assert continuous_overlay_groups(
        semantic, recipes, set(), scene_groups={"AZL01"}
    ) == {"AZL01"}
    assert not continuous_overlay_groups(semantic, recipes, set())
    placement["rect"] = [0, 0, 1, 0.8]
    assert not continuous_overlay_groups(
        semantic, recipes, set(), scene_groups={"AZL01"}
    )
    placement["rect"] = list(AZL_RECT)
    recipes["overlay_template_id"] = None
    assert not continuous_overlay_groups(
        semantic, recipes, set(), scene_groups={"AZL01"}
    )


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


def test_question_inset_keeps_the_main_caption_and_aligns_to_the_visible_frame():
    from app.video_editing_question_branch import question_overlay_entry_frame
    from app.video_editing_render_edits import continuous_overlay_groups

    semantic = {"beats": [{"id": "question", "group_id": "W-R18"}]}
    config = {
        "branch": "question",
        "content": {"captions": []},
        "timing": {"events": {"question_in": 0}},
    }
    entry = {
        "placement": {"layer": "overlay", "rect": [0.13, 0.435, 0.74, 0.41]},
        "recipe": {"group_id": "W-R18", "config": config},
    }
    recipes = {
        "entries": {"question": entry},
        "protected_regions": [
            {"id": "centered-portrait", "rect": [0.35, 0.09, 0.34, 0.34]}
        ],
    }
    assert not continuous_overlay_groups(semantic, recipes, set())
    assert continuous_overlay_groups(
        semantic, recipes, set(), allow_question_insets=True
    ) == {"W-R18"}

    config["content"]["captions"].append({"text": "duplicate"})
    assert not continuous_overlay_groups(
        semantic, recipes, set(), allow_question_insets=True
    )
    config["content"]["captions"].clear()
    config["branch"] = "smoke"
    assert not continuous_overlay_groups(
        semantic, recipes, set(), allow_question_insets=True
    )
    config["branch"] = "question"
    shot = {
        "group_id": "W-R18",
        "layer": "overlay",
        "start_seconds": 4.87,
        "config": config,
    }
    assert question_overlay_entry_frame(shot, 30) == 147
    shot["start_seconds"] = 4.9
    assert question_overlay_entry_frame(shot, 30) == 147


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


def test_full_frame_requires_the_audited_moving_backdrop():
    from app.video_editing_render_edits import full_native_canvas_allowed

    entry = {
        "placement": {"layer": "overlay", "rect": [0, 0, 1, 1]},
        "recipe": {"group_id": "HY-A5"},
    }
    assert not full_native_canvas_allowed("HY-A5", entry)
    entry["recipe"]["hypit_live_stage"] = True
    assert full_native_canvas_allowed("HY-A5", entry)
    entry["recipe"] = {
        "group_id": "W-R18",
        "config": {"branch": "question", "content": {"captions": []}, "media": {}},
    }
    assert not full_native_canvas_allowed("W-R18", entry)
    entry["recipe"]["config"]["media"]["question_background"] = {"kind": "video"}
    assert full_native_canvas_allowed("W-R18", entry)


def test_hypit_presenter_labels_accept_only_the_full_audited_canvas():
    from app.video_editing_hypit_strips import PRESENTER_LABEL_GROUP
    from app.video_editing_render_edits import continuous_overlay_groups

    group = PRESENTER_LABEL_GROUP
    semantic = {"beats": [{"id": "labels", "group_id": group}]}
    entry = {
        "placement": {"layer": "overlay", "rect": [0, 0, 1, 1]},
        "recipe": {"group_id": group, "hypit_live_stage": True},
    }
    recipes = {
        "entries": {"labels": entry},
        "protected_regions": [{"id": "centered-portrait", "rect": [0.1, 0, 0.8, 0.4]}],
    }
    assert not continuous_overlay_groups(semantic, recipes, set())
    assert continuous_overlay_groups(
        semantic, recipes, set(), allow_hypit_insets=True
    ) == {group}
    entry["placement"]["rect"] = [0.1, 0.5, 0.8, 0.2]
    assert not continuous_overlay_groups(
        semantic, recipes, set(), allow_hypit_insets=True
    )


def test_continuous_narration_accepts_an_explicit_full_original_scene():
    from app.video_editing_render_edits import continuous_overlay_groups

    semantic = {"beats": [{"id": "question", "group_id": "W-R18"}]}
    entry = {
        "placement": {"layer": "scene", "rect": [0, 0, 1, 1]},
        "recipe": {"group_id": "W-R18"},
    }
    recipes = {"entries": {"question": entry}}
    assert not continuous_overlay_groups(semantic, recipes, set())
    assert continuous_overlay_groups(
        semantic, recipes, set(), scene_groups={"W-R18"}
    ) == {"W-R18"}
    entry["placement"]["rect"] = [0, 0, 0.5, 0.5]
    assert not continuous_overlay_groups(
        semantic, recipes, set(), scene_groups={"W-R18"}
    )
