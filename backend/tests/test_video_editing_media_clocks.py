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


def test_audited_reference_matches_presenter_without_a_second_clock(
    tmp_path, monkeypatch
):
    package, transcript, _, _, assets, _ = media_inputs(tmp_path, monkeypatch)
    manifest = read_json(clocks.MANIFEST)
    presenter = "/media/presenter/path"
    manifest["profiles"]["YYP01"]["source_reference_aliases"] = {
        "/reference": presenter
    }
    atomic_json(clocks.MANIFEST, manifest)
    config = read_json(package / "template.json")
    config["reference"] = "input://fixture-reference"
    atomic_json(package / "template.json", config)
    group = read_json(package / "catalog/groups.json")["groups"][0]
    contract = input_contract(package, group)
    reference_slot = next(
        r for r in contract["resource_paths"] if r["path"] == "/reference"
    )
    assert reference_slot["same_asset_as"] == presenter
    native = {
        "clock": {"start_ms": 1000, "end_ms": 2000},
        "media": [
            {"path": presenter, "asset_id": "current-raw"},
            {"path": "/reference", "asset_id": "current-raw"},
        ],
    }
    declarations = [{"media_path": presenter, "policy": "transcript_source_window"}]
    _, proof = clocks.compile_media_clocks(
        package, group, contract, native, declarations, assets, transcript, config
    )
    assert [row["media_path"] for row in proof] == [presenter]
    assets["unrelated"] = assets["current-raw"].copy()
    native["media"][1]["asset_id"] = "unrelated"
    with pytest.raises(ValueError, match="source reference must match"):
        clocks.compile_media_clocks(
            package, group, contract, native, declarations, assets, transcript, config
        )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "historical_offset",
        "different_source",
        "different_kind",
        "guessed_clock",
        "holding",
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
    elif change == "holding":
        manifest = read_json(clocks.MANIFEST)
        manifest["profiles"]["YYP01"]["require_source_end_error"] = True
        atomic_json(clocks.MANIFEST, manifest)
        recipe["config"]["media"]["presenter"]["end_policy"] = "hold"
    else:
        engine.write_text("# changed source expression\n")
    with pytest.raises(ValueError):
        compile_native_job(
            package, tmp_path / "rejected", beat, transcript, recipe, assets
        )
    assert not (tmp_path / "rejected/job.json").exists()


def test_independent_video_clock_requires_the_uploaded_clip_length(
    tmp_path, monkeypatch
):
    package, transcript, _, _, _, engine = media_inputs(tmp_path, monkeypatch)
    slot = "/media/broll1/path"
    manifest = read_json(clocks.MANIFEST)
    profile = manifest["profiles"].pop("YYP01")
    profile["project_clip_event_frames"] = {slot: 32}
    profile["project_clip_settle_frame"] = 47
    manifest["profiles"]["YYP05"] = profile
    atomic_json(clocks.MANIFEST, manifest)
    group = {"id": "YYP05", "backend": "scene"}
    contract = {"native_fps": 30, "fields": [{"path": slot, "category": "resource"}]}
    native = {
        "media": [{"path": slot, "asset_id": "clip"}],
        "clock": {"start_ms": 1000, "end_ms": 4000},
    }
    declarations = [{"media_path": slot, "policy": "project_clip_from_start"}]
    assets = {
        "clip": {
            "kind": "video",
            "source": "project_upload",
            "duration_ms": 2000,
            "sha256": "a" * 64,
        }
    }
    config = {"events": {"shift_frames": 0}}
    assigned, proof = clocks.compile_media_clocks(
        package, group, contract, native, declarations, assets, transcript, config
    )
    assert not assigned and proof[0]["source_start_ms"] == 0
    assert proof[0]["source_end_ms"] == 1934
    assets["clip"]["duration_ms"] = 1933
    with pytest.raises(ValueError, match="shorter than its native window"):
        clocks.compile_media_clocks(
            package, group, contract, native, declarations, assets, transcript, config
        )


@pytest.mark.parametrize("delayed", [False, True])
def test_scene_clip_clock_binds_native_window_without_using_presenter_offset(
    tmp_path, monkeypatch, delayed
):
    package, transcript, _, _, _, _ = media_inputs(tmp_path, monkeypatch)
    slot = "/media/broll/path"
    event = "/timing/broll_in"
    manifest = read_json(clocks.MANIFEST)
    profile = manifest["profiles"]["YYP01"]
    profile["project_scene_clip_start_events"] = {slot: event if delayed else None}
    atomic_json(clocks.MANIFEST, manifest)
    fields = ["offset_seconds", "duration_seconds"]
    if delayed:
        fields.append("start_seconds")
    contract = {
        "native_fps": 30,
        "fields": [
            {"path": f"/media/broll/{name}", "category": "clock_owned_by_compiler"}
            for name in fields
        ],
    }
    group = {"id": "YYP01", "backend": "scene"}
    native = {
        "media": [{"path": slot, "asset_id": "uploaded"}],
        "clock": {"start_ms": 8600, "end_ms": 11600},
        "events": [{"path": event, "unit": "frames", "value": 24}] if delayed else [],
    }
    assets = {
        "uploaded": {
            "kind": "video",
            "source": "project_upload",
            "duration_ms": 4000,
            "sha256": "a" * 64,
        }
    }
    config = {"media": {"broll": {"end_policy": "error"}}}
    declarations = [{"media_path": slot, "policy": "project_scene_clip_window"}]
    assigned, proof = clocks.compile_media_clocks(
        package, group, contract, native, declarations, assets, transcript, config
    )
    assert assigned == {
        "/media/broll/offset_seconds": 0,
        "/media/broll/duration_seconds": 2.2 if delayed else 3,
        **({"/media/broll/start_seconds": 0.8} if delayed else {}),
    }
    assert proof[0]["source_start_ms"] == 0
    assert proof[0]["source_end_ms"] == (2200 if delayed else 3000)
    assert proof[0]["asset_id"] == "uploaded"
    config["media"]["broll"]["end_policy"] = "hold"
    with pytest.raises(ValueError, match="without looping or holding"):
        clocks.compile_media_clocks(
            package, group, contract, native, declarations, assets, transcript, config
        )
    config["media"]["broll"]["end_policy"] = "error"
    if delayed:
        native["events"].clear()
        with pytest.raises(ValueError, match="measured native frame event"):
            clocks.compile_media_clocks(
                package,
                group,
                contract,
                native,
                declarations,
                assets,
                transcript,
                config,
            )
    else:
        assets["uploaded"]["duration_ms"] = 2999
        with pytest.raises(ValueError, match="cover its native window"):
            clocks.compile_media_clocks(
                package,
                group,
                contract,
                native,
                declarations,
                assets,
                transcript,
                config,
            )


def test_implicit_scene_extents_bind_video_and_still_without_inventing_fields(
    tmp_path, monkeypatch
):
    package, transcript, _, _, _, _ = media_inputs(tmp_path, monkeypatch)
    main, lower = "/media/main/path", "/media/lower/path"
    manifest = read_json(clocks.MANIFEST)
    profile = manifest["profiles"]["YYP01"]
    profile["project_scene_clip_start_events"] = {main: None, lower: None}
    profile["project_scene_implicit_extent_paths"] = [main, lower]
    atomic_json(clocks.MANIFEST, manifest)
    group = {"id": "YYP01", "backend": "scene"}
    offset = "/media/main/offset_seconds"
    contract = {
        "native_fps": 30,
        "fields": [{"path": offset, "category": "clock_owned_by_compiler"}],
    }
    native = {
        "media": [
            {"path": main, "asset_id": "registered-video"},
            {"path": lower, "asset_id": "registered-image"},
        ],
        "clock": {"start_ms": 8600, "end_ms": 11600},
    }
    assets = {
        "registered-video": {
            "kind": "video",
            "source": "project_upload",
            "duration_ms": 3000,
            "sha256": "a" * 64,
        },
        "registered-image": {
            "kind": "image",
            "source": "project_upload",
            "duration_ms": None,
            "sha256": "b" * 64,
        },
    }
    config = {"media": {slot: {"end_policy": "error"} for slot in ("main", "lower")}}
    declarations = [
        {"media_path": path, "policy": "project_scene_clip_window"}
        for path in (main, lower)
    ]

    def compile_clocks(rows):
        return clocks.compile_media_clocks(
            package, group, contract, native, rows, assets, transcript, config
        )

    assigned, (video, still) = compile_clocks(declarations)
    assert assigned == {offset: 0.0}
    assert video["source_end_ms"] == 3000 and video["start_frame"] == 0
    assert still["source_end_ms"] is None and still["asset_duration_ms"] is None
    with pytest.raises(ValueError, match="own audited source clock"):
        compile_clocks(declarations[:1])
    assets["registered-video"]["duration_ms"] = 2999
    with pytest.raises(ValueError, match="cover its native window"):
        compile_clocks(declarations)


def test_audited_source_cut_uses_both_measured_edges(tmp_path, monkeypatch):
    package, transcript, _, _, assets, _ = media_inputs(tmp_path, monkeypatch)
    slot = "/media/shots/0/path"
    first, second = "/timing/events/cuts/0", "/timing/events/cuts/1"
    manifest = read_json(clocks.MANIFEST)
    manifest["profiles"]["YYP01"]["transcript_cut_media"] = {slot: [first, second]}
    atomic_json(clocks.MANIFEST, manifest)
    group = {"id": "YYP01", "backend": "scene"}
    contract = {
        "native_fps": 30,
        "fields": [
            {"path": "/media/shots/0/" + name, "category": "clock_owned_by_compiler"}
            for name in ("offset_seconds", "duration_seconds")
        ],
    }
    native = {
        "media": [{"path": slot, "asset_id": "current-raw"}],
        "clock": {"start_ms": 1000, "end_ms": 4000},
        "events": [
            {
                "path": first,
                "unit": "seconds",
                "value": 0.25,
                "measured_anchor_ms": 1250,
            },
            {
                "path": second,
                "unit": "seconds",
                "value": 1.8,
                "measured_anchor_ms": 2800,
            },
        ],
    }
    declaration = [{"media_path": slot, "policy": "transcript_cut_window"}]
    assigned, proof = clocks.compile_media_clocks(
        package, group, contract, native, declaration, assets, transcript, {}
    )
    assert assigned == {
        "/media/shots/0/offset_seconds": 1.25,
        "/media/shots/0/duration_seconds": 1.55,
    }
    assert proof[0]["cut_event_paths"] == [first, second]
    native["events"][1]["value"] = 0.9
    with pytest.raises(ValueError, match="measured local seconds"):
        clocks.compile_media_clocks(
            package, group, contract, native, declaration, assets, transcript, {}
        )
