"""Sampling contracts only: fixture bytes are never passed to a renderer."""

import copy

import pytest

from app import video_editing_media_clocks as clocks
from app.motion_library import MOTION_SHA256, atomic_json, read_json, sha256
from app.motion_parameter_contracts import input_contract
from app.video_editing_contracts import NativeMediaAnchor
from app.video_editing_native_compiler import compile_native_job
from tests.test_video_editing_native_compiler import inputs


def media_inputs(tmp_path, monkeypatch):
    package, transcript, beat, recipe = inputs(tmp_path)
    group = read_json(package / "catalog/groups.json")["groups"][0]
    group.update(id="YYP01", backend="scene")
    atomic_json(package / "catalog/groups.json", {"groups": [group]})
    template = read_json(package / "template.json")
    template["media"] = {
        "presenter": {
            "path": "input://fixture-raw",
            "offset_seconds": 0,
            "duration_seconds": 2,
            "end_policy": "error",
        }
    }
    atomic_json(package / "template.json", template)
    schema = read_json(package / "schema.json")
    schema["properties"]["media"] = {"type": "object"}
    atomic_json(package / "schema.json", schema)
    engine = package / "fixture-engine.py"
    engine.write_text("# Sampling profile fixture, never executed\n")
    manifest = tmp_path / "profiles.json"
    atomic_json(
        manifest,
        {
            "library_release": MOTION_SHA256,
            "profiles": {
                "YYP01": {
                    "id": "fixture-direct/1",
                    "native_fps": 30,
                    "scope": "unit fixture, not runtime approval",
                    "local_sample_seconds": "frame / 30",
                    "backend": "scene",
                    "media_paths": ["/media/presenter/path"],
                    "source_files": {engine.name: sha256(engine)},
                }
            },
        },
    )
    monkeypatch.setattr(clocks, "MANIFEST", manifest)
    contract = input_contract(package, group)
    recipe.update(
        group_id="YYP01",
        template_sha256=contract["template_sha256"],
        schema_sha256=contract["schema_sha256"],
    )
    recipe["config"]["media"] = copy.deepcopy(template["media"])
    for key in ("path", "offset_seconds", "duration_seconds"):
        recipe["config"]["media"]["presenter"][key] = None
        recipe["placeholders"].append("/media/presenter/" + key)
    recipe["parameter_decisions"]["media"] = (
        "explicit current original presenter, no holding or stretch"
    )
    recipe["media_clocks"] = [
        {"media_path": "/media/presenter/path", "policy": "transcript_source_window"}
    ]
    raw = tmp_path / "fixture-not-a-video.bin"
    raw.write_bytes(b"boundary-only fixture")
    transcript.source_sha256 = sha256(raw)
    beat.group_id = "YYP01"
    beat.asset_ids = ["current-raw"]
    beat.native_media = [
        NativeMediaAnchor(path="/media/presenter/path", asset_id="current-raw")
    ]
    assets = {
        "current-raw": {
            "path": str(raw),
            "sha256": sha256(raw),
            "kind": "original_video",
        }
    }
    return package, transcript, beat, recipe, assets, engine


def test_native_presenter_uses_measured_nonzero_source_window(tmp_path, monkeypatch):
    package, transcript, beat, recipe, assets, _ = media_inputs(tmp_path, monkeypatch)
    job = compile_native_job(
        package, tmp_path / "bound", beat, transcript, recipe, assets
    )
    presenter = job["config"]["media"]["presenter"]
    assert presenter["offset_seconds"] == 1
    assert presenter["duration_seconds"] == 1
    assert job["config"]["frames"] == 30
    assert presenter["end_policy"] == "error"
    receipt = read_json(tmp_path / "bound/compile-receipt.json")["media_clocks"][0]
    assert (receipt["source_start_ms"], receipt["source_end_ms"]) == (1000, 2000)
    assert receipt["timing_review"] == "unreviewed"
    assert (
        read_json(package / "template.json")["media"]["presenter"]["offset_seconds"]
        == 0
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "historical_offset",
        "different_source",
        "different_kind",
        "guessed_clock",
        "tampered_engine",
    ],
)
def test_media_clock_rejects_history_wrong_source_and_unaudited_sampling(
    tmp_path, monkeypatch, change
):
    package, transcript, beat, recipe, assets, engine = media_inputs(
        tmp_path, monkeypatch
    )
    if change == "missing":
        recipe.pop("media_clocks")
    elif change == "historical_offset":
        recipe["config"]["media"]["presenter"]["offset_seconds"] = 5
    elif change == "different_source":
        transcript.source_sha256 = "0" * 64
    elif change == "different_kind":
        assets["current-raw"]["kind"] = "image"
    elif change == "guessed_clock":
        recipe["media_clocks"][0]["offset_seconds"] = 1
    else:
        engine.write_text("# changed source expression\n")
    with pytest.raises(ValueError):
        compile_native_job(
            package, tmp_path / "rejected", beat, transcript, recipe, assets
        )
    assert not (tmp_path / "rejected/job.json").exists()
