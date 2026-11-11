"""API/ownership fixtures below are metadata, not native render evidence."""

import importlib.util
import wave
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.motion_library import MOTION_SHA256, atomic_json, read_json, sha256
from app.motion_local_dependencies import NONCOMMERCIAL_FONT
from app.video_editing_catalog import choice_snapshot_hash, validate_choice_snapshot
from app.video_editing_contracts import SemanticPlan, Transcript, TranscriptToken
from app.video_editing_planner import validate_plan
from tests.test_video_editing_tasks import setup_source
from tests.test_video_projects import base, payload

pytest_plugins = ["tests.test_video_projects"]


def full_metadata(video, tmp_path):
    client, auth, ws, user, settings, project, source = setup_source(video, tmp_path)
    package = settings.video_editing_library_dir
    atomic_json(
        package / "catalog/groups.json",
        {
            "groups": [
                {
                    "id": f"G{i:03}",
                    "name": f"Boundary fixture {i}",
                    "kind": "visual" if i < 89 else "subtitle",
                    "backend": "unified",
                    "primary_function": "fixture",
                    "purpose": "fixture",
                    "branch": "unit fixture",
                    "input_schema": "schema.json",
                    "input_template": "template.json",
                    "contract": None,
                }
                for i in range(132)
            ]
        },
    )
    atomic_json(package / "schema.json", {"type": "object"})
    atomic_json(
        package / "template.json",
        {
            "media": {"picture": {"path": "input://external-0"}},
            "font": "input://external-1",
            "output": {"path": "input://historical-output"},
        },
    )
    atomic_json(
        package / "catalog/external-resources.json",
        {
            "resources": [
                {
                    "id": f"external-{i}",
                    "kind": "font" if i == 1 else "media",
                    "label": f"original-reference-{i}",
                }
                for i in range(699)
            ]
        },
    )
    audio = package / "assets/stock.wav"
    audio.parent.mkdir(parents=True)
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 1600)
    assets = [
        {
            "id": f"asset-{i}",
            "kind": "sfx" if i == 0 else "font",
            "path": "assets/stock.wav",
            "sha256": sha256(audio),
            "name": f"stock-{i}",
        }
        for i in range(197)
    ]
    atomic_json(package / "asset-manifest.json", {"assets": assets})
    return client, auth, ws, settings, project, source, audio


def test_all_groups_and_resources_remain_with_explicit_unverified_states(
    video, tmp_path
):
    client, _, ws, _, _, _, _ = full_metadata(video, tmp_path)
    url = base(ws) + "/editing-library"
    response = client.get(url, params={"limit": 132})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == len(data["groups"]) == 132
    assert data["groups"][-1]["id"] == "G131"
    assert data["summary"]["runtime"] == {"unverified": 132}
    assert data["summary"]["bundled_assets"] == 197
    assert data["summary"]["external_references"] == 699
    assert data["summary"]["visual_accepted"] == 0
    detail = client.get(url + "/groups/G131").json()
    assert {r["id"] for r in detail["template_dependencies"]} == {
        "external-0",
        "external-1",
    }
    assert "historical-output" not in str(detail["template_dependencies"])
    external = client.get(
        url + "/resources",
        params={"source": "external", "search": "original-reference-698"},
    ).json()
    assert external["total"] == 1 and external["resources"][0]["id"] == "external-698"
    assert external["resources"][0]["availability"] == "requires_explicit_task_binding"


def test_scene_details_include_external_font_referenced_by_original_engine(
    video, tmp_path
):
    client, _, ws, settings, _, _, _ = full_metadata(video, tmp_path)
    package = settings.video_editing_library_dir
    groups = read_json(package / "catalog/groups.json")
    groups["groups"][0].update(id="CXBR01", backend="scene")
    atomic_json(package / "catalog/groups.json", groups)
    resources = read_json(package / "catalog/external-resources.json")
    resources["resources"][-1] = {"id": "font-43a890795ad133d7", "kind": "font"}
    atomic_json(package / "catalog/external-resources.json", resources)
    response = client.get(base(ws) + "/editing-library/groups/CXBR01")
    assert response.status_code == 200, response.text
    detail = response.json()
    item = next(
        row
        for row in detail["template_dependencies"]
        if row["id"] == "font-43a890795ad133d7"
    )
    assert item["input_fields"] == []
    assert item["binding_scope"] == "exact_native_dependency"
    assert detail["runtime_validation"] == "unverified"


def test_local_font_state_checks_current_bytes_without_exposing_path(video, tmp_path):
    client, _, ws, settings, _, _, _ = full_metadata(video, tmp_path)
    package = settings.video_editing_library_dir
    font = tmp_path / "private-original-font.ttf"
    font.write_bytes(b"local exact font fixture")
    resources = read_json(package / "catalog/external-resources.json")
    resources["resources"][1].update(
        bytes=font.stat().st_size, sha256=sha256(font), rights=NONCOMMERCIAL_FONT
    )
    atomic_json(package / "catalog/external-resources.json", resources)
    manifest = tmp_path / "bindings.json"
    atomic_json(
        manifest,
        {"resources": {"external-1": str(font), "external-0": str(font)}, "tools": {}},
    )
    settings.video_editing_native_bindings_file = manifest
    url = base(ws) + "/editing-library"

    def read_state():
        detail = client.get(url + "/groups/G131")
        listed = client.get(
            url + "/resources",
            params={"source": "external", "search": "external-1", "kind": "font"},
        )
        assert detail.status_code == listed.status_code == 200
        for private in ("private-original-font.ttf", "private-component-approval"):
            assert private not in detail.text + listed.text
        rows = {row["id"]: row for row in detail.json()["template_dependencies"]}
        assert "local_dependency_state" not in rows["external-0"]
        font_row = listed.json()["resources"][0]
        assert (
            font_row["local_dependency_state"]
            == rows["external-1"]["local_dependency_state"]
        )
        assert (
            font_row["component_use_state"] == rows["external-1"]["component_use_state"]
        )
        return (
            font_row["local_dependency_state"],
            font_row["component_use_state"],
            listed.json()["external_files_available"],
        )

    assert read_state() == ("verified", "reference_required", True)
    document = read_json(manifest)
    document["resource_intake"] = {
        "external-1": {
            "library_release": MOTION_SHA256,
            "sha256": sha256(font),
            "component_use_reference": "private-component-approval",
        }
    }
    atomic_json(manifest, document)
    assert read_state() == ("verified", "reference_recorded", True)
    font.write_bytes(b"X" * font.stat().st_size)
    assert read_state() == ("identity_mismatch", "reference_recorded", False)
    font.unlink()
    assert read_state() == ("file_missing", "reference_recorded", False)
    atomic_json(manifest, {"resources": {"external-1": "relative.ttf"}})
    assert read_state() == ("not_registered", "reference_required", False)


def test_audio_is_authenticated_range_served_and_changed_bytes_are_rejected(
    video, tmp_path
):
    client, auth, ws, settings, _, _, audio = full_metadata(video, tmp_path)
    url = base(ws) + "/editing-library/assets/asset-0/audio"
    response = client.get(url)
    assert response.status_code == 200 and response.content == audio.read_bytes()
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "private, no-store"
    part = client.get(url, headers={"Range": "bytes=0-31"})
    assert part.status_code == 206 and part.content == audio.read_bytes()[:32]
    assert (
        client.get(base(ws) + "/editing-library/assets/asset-1/audio").status_code
        == 404
    )
    assert (
        client.get(base(ws) + "/editing-library/assets/external-1/audio").status_code
        == 404
    )
    audio.write_bytes(audio.read_bytes() + b"changed")
    assert client.get(url).status_code == 409
    manifest = read_json(settings.video_editing_library_dir / "asset-manifest.json")
    manifest["assets"][0]["path"] = "../outside.wav"
    atomic_json(settings.video_editing_library_dir / "asset-manifest.json", manifest)
    assert client.get(url).status_code == 409
    from tests.test_auth_external import verified_identity

    auth.identity = verified_identity(
        primary_user_id="foreign-user", email="1474953130@qq.com"
    )
    assert client.get(url).status_code in (403, 404)


def test_selection_memo_versions_replay_stale_writes_and_latest_pagination(
    video, tmp_path
):
    client, _, ws, _, project, _, _ = full_metadata(video, tmp_path)
    url = base(ws) + f"/projects/{project}/editing-library-notes"
    first_body = {
        "request_id": str(uuid4()),
        "target_kind": "group",
        "target_id": "G131",
        "choice": "consider",
        "reason": "boundary test only; no render approval",
    }
    first = client.post(url, json=first_body)
    assert first.status_code == 200, first.text
    first = first.json()
    second = client.post(
        url,
        json={
            **first_body,
            "request_id": str(uuid4()),
            "parent_note_id": first["id"],
            "choice": "avoid",
            "reason": "changed preference",
        },
    )
    assert second.status_code == 200, second.text
    second = second.json()
    assert second["sequence"] == 2 and second["parent_note_id"] == first["id"]
    assert client.post(url, json=first_body).json() == first
    assert (
        client.post(url, json={**first_body, "request_id": str(uuid4())}).status_code
        == 409
    )
    assert (
        client.post(url, json={**first_body, "reason": "different input"}).status_code
        == 409
    )
    assert (
        client.post(
            url, json={**first_body, "request_id": str(uuid4()), "target_id": "missing"}
        ).status_code
        == 404
    )
    asset = client.post(
        url,
        json={
            "request_id": str(uuid4()),
            "target_kind": "bundled_asset",
            "target_id": "asset-0",
            "choice": "consider",
            "reason": "audition not approved",
        },
    )
    assert asset.status_code == 200, asset.text
    page = client.get(url, params={"limit": 1}).json()
    assert page["total"] == 2 and page["next_offset"] == 1
    next_page = client.get(url, params={"limit": 1, "offset": 1}).json()
    latest_ids = {page["items"][0]["id"], next_page["items"][0]["id"]}
    assert latest_ids == {second["id"], asset.json()["id"]}
    history = client.get(
        url, params={"latest_only": False, "target_kind": "group", "target_id": "G131"}
    ).json()
    assert [r["sequence"] for r in history["items"]] == [2, 1]
    assert (
        client.get(base(ws) + "/editing-library", params={"limit": 132}).json()["total"]
        == 132
    )
    cleared = client.post(
        url,
        json={
            **first_body,
            "request_id": str(uuid4()),
            "parent_note_id": second["id"],
            "choice": "clear",
            "reason": "clear for this project",
        },
    )
    assert cleared.status_code == 200 and cleared.json()["sequence"] == 3


def test_memos_are_scoped_to_project_and_owner(video, tmp_path):
    from tests.test_auth_external import verified_identity

    client, auth, ws, _, project, _, _ = full_metadata(video, tmp_path)
    url = base(ws) + f"/projects/{project}/editing-library-notes"
    body = {
        "request_id": str(uuid4()),
        "target_kind": "group",
        "target_id": "G131",
        "choice": "consider",
        "reason": "fixture",
    }
    saved = client.post(url, json=body).json()
    other = str(uuid4())
    assert (
        client.put(base(ws) + "/projects/" + other, json=payload()).status_code == 200
    )
    other_url = base(ws) + f"/projects/{other}/editing-library-notes"
    assert client.get(other_url).json()["items"] == []
    assert (
        client.post(
            other_url,
            json={**body, "request_id": str(uuid4()), "parent_note_id": saved["id"]},
        ).status_code
        == 409
    )
    auth.identity = verified_identity(
        primary_user_id="foreign-user", email="1474953130@qq.com"
    )
    assert client.get(url).status_code in (403, 404)
    assert client.post(url, json=body).status_code in (403, 404)


def test_choice_snapshot_is_consistent_and_avoid_is_enforced_without_catalog_pruning(
    video, tmp_path
):
    client, _, ws, settings, project, _, _ = full_metadata(video, tmp_path)
    url = base(ws) + f"/projects/{project}/editing-library-notes"
    saved = client.post(
        url,
        json={
            "request_id": str(uuid4()),
            "target_kind": "group",
            "target_id": "G131",
            "choice": "avoid",
            "reason": "current project constraint fixture",
        },
    ).json()
    endpoint = base(ws) + f"/projects/{project}/editing-library-choice-snapshot"
    response = client.get(endpoint)
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot["sha256"] == choice_snapshot_hash(snapshot)
    assert (
        validate_choice_snapshot(settings.video_editing_library_dir, snapshot)
        == snapshot
    )
    damaged = deepcopy(snapshot)
    damaged["notes"][0]["choice"] = "consider"
    with pytest.raises(ValueError):
        validate_choice_snapshot(settings.video_editing_library_dir, damaged)
    damaged["notes"][0]["target_id"] = "unregistered-group"
    damaged["sha256"] = choice_snapshot_hash(damaged)
    with pytest.raises(ValueError):
        validate_choice_snapshot(settings.video_editing_library_dir, damaged)
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=1000,
        provider="annotated fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[TranscriptToken(id="t0", text="当前口播", start_ms=100, end_ms=700)],
    )
    plan = SemanticPlan.model_validate(
        {
            "audience_question": "fixture",
            "argument_outline": ["fixture"],
            "style_reason": "fixture",
            "beats": [
                {
                    "id": "b",
                    "first_token_id": "t0",
                    "last_token_id": "t0",
                    "group_id": "G131",
                    "relation": "explanation",
                    "reason": "fixture",
                }
            ],
        }
    )
    with pytest.raises(ValueError, match="avoid"):
        validate_plan(
            plan, transcript, settings.video_editing_library_dir, set(), snapshot
        )
    plan.beats[0].group_id = "G000"
    validate_plan(plan, transcript, settings.video_editing_library_dir, set(), snapshot)
    client.post(
        url,
        json={
            "request_id": str(uuid4()),
            "target_kind": "group",
            "target_id": "G131",
            "choice": "clear",
            "reason": "clear fixture",
            "parent_note_id": saved["id"],
        },
    ).raise_for_status()
    cleared = client.get(endpoint).json()
    plan.beats[0].group_id = "G131"
    validate_plan(plan, transcript, settings.video_editing_library_dir, set(), cleared)
    assert (
        client.get(base(ws) + "/editing-library", params={"limit": 132}).json()["total"]
        == 132
    )


def test_library_notes_migration_preserves_existing_data(tmp_path):
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261109_0045_editing_library_notes.py"
    )
    spec = importlib.util.spec_from_file_location("library_notes_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'notes.db'}")
    with engine.begin() as connection:
        for table in ("users", "workspaces", "video_projects"):
            connection.execute(
                text(f"CREATE TABLE {table} (id VARCHAR(40) PRIMARY KEY)")
            )
        connection.execute(text("INSERT INTO users VALUES ('preserved')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert (
            len(
                inspect(connection).get_unique_constraints(
                    "video_editing_library_notes"
                )
            )
            == 2
        )
        migration.downgrade()
        assert (
            "video_editing_library_notes" not in inspect(connection).get_table_names()
        )
        assert connection.scalar(text("SELECT id FROM users")) == "preserved"
    engine.dispose()
