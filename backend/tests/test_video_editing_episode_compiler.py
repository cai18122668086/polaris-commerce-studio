"""Protocol/negative fixtures; real media evidence is recorded separately."""

import copy

import pytest

from app.config import Settings
from app.motion_browser_originals import (
    BROWSER_ORIGINALS_REQUIRED,
    BrowserOriginalsMissing,
)
from app.motion_library import MOTION_SHA256, atomic_json, read_json, sha256
from app.motion_parameter_contracts import input_contract
from app.video_editing_contracts import (
    NativeRenderEdits,
    SemanticPlan,
    Transcript,
    TranscriptToken,
)
from app.video_editing_episode_compiler import EpisodeRecipeBundle, compile_episode
from app.video_editing_native_sound import (
    NativeSoundDesign,
    compile_sound,
    music_replacement_options,
)
from app.video_editing_pipeline import (
    EditingFailure,
    baseline_documents,
    validate_result,
)
from app.video_editing_planner import validate_plan


def protocol(tmp_path):
    from PIL import ImageFont

    package = tmp_path / "library"
    groups = [
        {
            "id": "Z-M00" if i == 0 else f"T{i:03}",
            "kind": "visual" if i == 0 else "subtitle",
            "backend": "unified" if i == 0 else "subtitle",
            "input_template": "catalog/inputs/Z-M00.json" if i == 0 else "effect.json",
            "input_schema": "effect.schema.json",
        }
        for i in range(132)
    ]
    atomic_json(package / "catalog/groups.json", {"groups": groups})
    font = package / "fixture-font.ttf"
    font.write_bytes(ImageFont.load_default().path.getvalue())
    atomic_json(
        package / "asset-manifest.json",
        {
            "assets": [
                {
                    "id": "font-d1961be1161ea1be",
                    "kind": "font",
                    "path": font.name,
                    "sha256": sha256(font),
                }
            ]
        },
    )
    atomic_json(package / "catalog/external-resources.json", {"resources": []})
    atomic_json(package / "catalog/relationship-capabilities.json", {"groups": []})
    atomic_json(
        package / "catalog/inputs/Z-M00.json",
        {
            "content": {"captions": []},
            "media": {"presenter": {}},
            "timing": {},
            "output": {},
        },
    )
    effect = {
        "group_id": "T001",
        "frames": 100,
        "fps": 30,
        "content": {"text": "history"},
        "events": {"enter_start": 2, "enter_end": 10},
        "style": {"fill": "#ffffff"},
        "output": "input://history-output",
    }
    atomic_json(package / "effect.json", effect)
    atomic_json(
        package / "effect.schema.json",
        {
            "type": "object",
            "properties": {
                "content": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "maxLength": 30}},
                },
            },
        },
    )
    atomic_json(
        package / "params.schema.json",
        {
            "type": "object",
            "properties": {
                "production": {
                    "properties": {
                        "beats": {
                            "items": {
                                "properties": {
                                    "relation": {
                                        "properties": {
                                            "type": {
                                                "enum": [
                                                    "parallel",
                                                    "contrast",
                                                    "cause",
                                                    "sequence",
                                                    "transformation",
                                                    "amount",
                                                ]
                                            }
                                        },
                                    }
                                }
                            }
                        }
                    }
                },
            },
        },
    )
    root = tmp_path / "instance"
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=4000,
        provider="annotated fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(id=f"t{i}", text=w, start_ms=a, end_ms=b)
            for i, (w, a, b) in enumerate(
                [
                    ("不是", 100, 600),
                    ("越贵", 600, 1400),
                    ("越好", 1400, 2900),
                    ("现在", 3100, 3900),
                ]
            )
        ],
    )
    atomic_json(root / "transcript.json", transcript.model_dump(mode="json"))
    prepared = {
        "source_sha256": "b" * 64,
        "audio_sha256": "a" * 64,
        "duration_ms": 4000,
        "probe": {"streams": [{"codec_type": "video", "width": 720, "height": 1280}]},
    }
    semantic = SemanticPlan.model_validate(
        {
            "audience_question": "fixture",
            "argument_outline": ["完整否定"],
            "style_reason": "fixture",
            "beats": [
                {
                    "id": "effect",
                    "first_token_id": "t0",
                    "last_token_id": "t2",
                    "group_id": "T001",
                    "relation": "negation",
                    "reason": "保留完整否定",
                    "emphasis_token_ids": ["t0", "t1", "t2"],
                    "native_text": [
                        {
                            "path": "/content/text",
                            "first_token_id": "t0",
                            "last_token_id": "t2",
                        }
                    ],
                    "native_events": [
                        {
                            "path": "/events/enter_start",
                            "token_id": "t0",
                            "edge": "start",
                        },
                        {"path": "/events/enter_end", "token_id": "t2", "edge": "end"},
                    ],
                },
                {
                    "id": "rest",
                    "first_token_id": "t3",
                    "last_token_id": "t3",
                    "group_id": "Z-M00",
                    "relation": "explanation",
                    "reason": "保留原景",
                },
            ],
        }
    )
    contract = input_contract(package, groups[1])
    fresh = copy.deepcopy(effect)
    fresh["content"]["text"] = None
    fresh["events"] = {"enter_start": None, "enter_end": None}
    recipe = {
        "version": "tengli.native-recipe/1",
        "release": MOTION_SHA256,
        "group_id": "T001",
        "template_sha256": contract["template_sha256"],
        "schema_sha256": contract["schema_sha256"],
        "design_id": "current",
        "design_reason": "fixture current design",
        "parameter_decisions": {
            "group_id": "original identity",
            "style": "explicit current white text",
        },
        "placeholders": ["/content/text", "/events/enter_start", "/events/enter_end"],
        "config": fresh,
    }
    authoring = EpisodeRecipeBundle.model_validate(
        {
            "version": "tengli.episode-recipes/1",
            "library_release": MOTION_SHA256,
            "source_sha256": transcript.source_sha256,
            "transcript_sha256": sha256(root / "transcript.json"),
            "planning_origin": "operator_candidate",
            "source_review": "protocol fixture, no media acceptance",
            "design": {"caption_font_id": "font-d1961be1161ea1be"},
            "typography": {
                "caption": {
                    "font_id": "font-d1961be1161ea1be",
                    "size_px": 48,
                    "max_width_px": 604,
                    "max_lines": 2,
                }
            },
            "layout_policy": {},
            "sound_mode": "original_voice_only",
            "entries": {
                "effect": {
                    "recipe": recipe,
                    "placement": {
                        "layer": "subtitle",
                        "rect": [0.1, 0.5, 0.8, 0.2],
                        "reason": "fixture",
                    },
                    "carrier": "text",
                }
            },
        }
    )
    settings = Settings(_env_file=None, video_editing_library_dir=package)
    options = {"caption_font_id": "font-d1961be1161ea1be", "source_subtitles": "none"}
    return root, package, prepared, transcript, semantic, authoring, settings, options


def test_replacement_music_keeps_native_mix_boundaries_and_checks_stock(tmp_path):
    _, package, _, transcript, *_ = protocol(tmp_path)
    original, valid, short, avoided = [f"bgm-{i:016x}" for i in range(4)]
    assets = []
    for aid, length in ((original, 4), (valid, 4), (short, 1), (avoided, 4)):
        audio = package / f"{aid}.mp3"
        audio.write_bytes(aid.encode())
        assets.append(
            {
                "id": aid,
                "kind": "music",
                "bundled": True,
                "rights": {"local_use": "user-authorized"},
                "name": aid,
                "path": audio.name,
                "sha256": sha256(audio),
                "duration_seconds": length,
            }
        )
    atomic_json(package / "asset-manifest.json", {"assets": assets})
    atomic_json(package / "assets/sfx/runtime-assets.json", {"assets": []})
    sound = NativeSoundDesign.model_validate(
        {
            "music": [
                {
                    "asset_id": original,
                    "start": {"token_id": "t1", "edge": "start"},
                    "end": "episode_end",
                    "source_start_seconds": 0.2,
                    "gain_db": -15,
                    "fade_seconds": 0.2,
                    "reason": "original music",
                }
            ]
        }
    )
    notes = {
        "notes": [
            {"target_id": avoided, "target_kind": "bundled_asset", "choice": "avoid"}
        ]
    }
    options = music_replacement_options(
        package, sound.model_dump(mode="json"), transcript, notes
    )
    assert options and options.original.asset_id == original
    assert [row.asset_id for row in options.choices] == [valid]
    episode = {"source": {"duration_seconds": 4.0}}
    result = compile_sound(
        package,
        transcript,
        episode,
        sound,
        {},
        notes,
        NativeRenderEdits(music="lower", music_track_id=valid),
    )
    (music,) = episode["music"]
    assert music["asset_id"] == valid and music["gain_db"] == -21
    assert music["source_start_seconds"] == 0
    assert (music["start_seconds"], music["end_seconds"], music["fade_seconds"]) == (
        0.6,
        4.0,
        0.2,
    )
    assert result["music_edit"] == {
        "mode": "replace",
        "original_track_ids": [original],
        "replacement_track_id": valid,
        "gain_mode": "lower",
    }
    assert sound.music[0].asset_id == original
    with pytest.raises(ValueError, match="requires background music to be on"):
        NativeRenderEdits(music="off", music_track_id=valid)
    (package / f"{valid}.mp3").write_bytes(b"changed")
    options = music_replacement_options(
        package, sound.model_dump(mode="json"), transcript, notes
    )
    assert options and not options.choices
    with pytest.raises(ValueError, match="does not match the current selection"):
        compile_sound(
            package,
            transcript,
            episode,
            sound,
            {},
            notes,
            NativeRenderEdits(music_track_id=valid),
        )


@pytest.mark.parametrize(
    ("duration_ms", "boundaries"),
    [(30000, [0, 15, 30]), (30470, [0, 15, 29.5, 30.47]), (30500, [0, 15, 30, 30.5])],
)
def test_subtitle_source_pages_fit_original_duration_bounds(
    tmp_path, monkeypatch, duration_ms, boundaries
):
    root, _, prepared, transcript, _, _, settings, options = protocol(tmp_path)
    prepared["duration_ms"] = duration_ms
    transcript.duration_ms = duration_ms
    monkeypatch.setattr("app.video_editing_pipeline.layout_captions", lambda *_: None)
    episode, selection, _ = baseline_documents(
        root, prepared, transcript, options, settings
    )
    for shot, (start, end) in zip(
        episode["shots"], zip(boundaries, boundaries[1:], strict=False), strict=True
    ):
        assert (shot["start_seconds"], shot["end_seconds"]) == (start, end)
        assert 0.5 <= shot["config"]["timing"]["duration_seconds"] <= 15
        assert shot["config"]["media"]["presenter"]["offset_seconds"] == start
    assert len(selection["decisions"]) == len(episode["shots"])


@pytest.mark.parametrize(
    ("source", "master"),
    [
        ((720, 1280), (720, 1280)),
        ((768, 1366), (768, 1366)),
        ((1080, 1920), (1080, 1920)),
        ((2160, 3840), (1080, 1920)),
        ((1100, 1920), (1080, 1886)),
    ],
)
def test_portrait_master_keeps_source_size_within_delivery_bounds(
    tmp_path, monkeypatch, source, master
):
    root, _, prepared, transcript, _, _, settings, options = protocol(tmp_path)
    prepared["probe"]["streams"][0].update(width=source[0], height=source[1])
    monkeypatch.setattr("app.video_editing_pipeline.layout_captions", lambda *_: None)
    episode, _, _ = baseline_documents(root, prepared, transcript, options, settings)
    output = episode["output"]
    assert (output["width"], output["height"]) == master
    assert episode["source"]["start_seconds"] == 0
    assert episode["source"]["duration_seconds"] == 4
    caption = episode["typography"]["caption"]
    assert caption["size_px"] == round(master[1] * 0.0375)
    assert caption["outline_px"] == 2 * max(1, master[1] / 1280)


def test_master_validation_rejects_a_render_with_different_dimensions(
    tmp_path, monkeypatch
):
    atomic_json(tmp_path / "episode.json", {"output": {"width": 1080, "height": 1920}})
    monkeypatch.setattr(
        "app.video_editing_pipeline.probe",
        lambda *_: {
            "streams": [
                {"codec_type": "video", "width": 720, "height": 1280},
                {"codec_type": "audio"},
            ]
        },
    )
    with pytest.raises(EditingFailure, match="EDITING_OUTPUT_DIMENSIONS_INVALID"):
        validate_result(
            tmp_path / "wrong-size.mp4",
            {},
            tmp_path,
            Settings(_env_file=None),
            lambda: None,
        )


def test_episode_uses_actual_word_bounds_and_original_selection_protocol(tmp_path):
    root, package, prepared, transcript, plan, authoring, settings, options = protocol(
        tmp_path
    )
    source = sha256(package / "effect.json")
    episode = compile_episode(
        root, prepared, transcript, plan, authoring, {}, options, settings
    )
    assert episode["source"]["start_seconds"] == 0
    assert episode["source"]["duration_seconds"] == 4
    assert [s["group_id"] for s in episode["shots"]] == ["T001", "Z-M00"]
    effect = episode["shots"][0]
    assert (effect["start_seconds"], effect["end_seconds"]) == (0.1, 2.9)
    assert effect["layer"] == "subtitle"
    assert effect["config"]["content"]["text"] == "不是越贵越好"
    assert effect["config"]["frames"] == 84
    rest = episode["shots"][1]
    assert rest["config"]["media"]["presenter"]["offset_seconds"] == 3.1
    selection = read_json(root / "selection.json")
    assert [d["selected_group_id"] for d in selection["decisions"]] == ["T001", "Z-M00"]
    report = read_json(root / "compile-diagnostics.json")
    assert report["issues"] == [] and report["catalog_groups_preserved"] == 132
    assert report["native_execution"] == "not_performed"
    assert report["planning_origin"] == "operator_candidate"
    assert sha256(package / "effect.json") == source


@pytest.mark.parametrize("music_edit", [None, "lower", "off"])
def test_native_mix_uses_measured_action_and_preserves_legacy_recipe_bytes(
    tmp_path, music_edit
):
    root, package, prepared, transcript, plan, authoring, settings, options = protocol(
        tmp_path
    )
    old_recipe = authoring.model_dump(mode="json")
    assert "sound" not in old_recipe
    assets = read_json(package / "asset-manifest.json")
    (package / "assets/sfx").mkdir(parents=True)
    for asset_id, kind, relative in (
        ("original-click", "sfx", "assets/sfx/click.wav"),
        ("original-track", "music", "music.wav"),
    ):
        file = package / relative
        file.write_bytes(b"protocol fixture for asset binding, never rendered")
        assets["assets"].append(
            {
                "id": asset_id,
                "kind": kind,
                "path": relative,
                "duration_seconds": 4,
                "sha256": sha256(file),
            }
        )
    click = assets["assets"][-2]
    atomic_json(package / "asset-manifest.json", assets)
    atomic_json(
        package / "assets/sfx/runtime-assets.json",
        {"assets": [{**click, "path": "click.wav"}]},
    )
    plan.beats[0].native_events[0].token_id = "t1"
    mixed = EpisodeRecipeBundle.model_validate(
        {
            **old_recipe,
            "sound_mode": "native_mix",
            "sound": {
                "fx": [
                    {
                        "asset_id": "original-click",
                        "beat_id": "effect",
                        "event_path": "/events/enter_start",
                        "phase": "entry",
                        "purpose": "actual cue fixture",
                        "trim_duration_seconds": 0.15,
                        "target_peak_dbfs": -26,
                    }
                ],
                "music": [
                    {
                        "asset_id": "original-track",
                        "start": {"token_id": "t0", "edge": "start"},
                        "end": {"token_id": "t3", "edge": "end"},
                        "gain_db": -30,
                        "fade_seconds": 0.2,
                        "reason": "current track fixture",
                        "envelope": [
                            {"at": {"token_id": "t1", "edge": "start"}, "gain_db": -4}
                        ],
                    }
                ],
            },
        }
    )
    if music_edit:
        options["native_edits"] = {
            "music": music_edit,
            "source_only_beat_ids": ["effect"] if music_edit == "off" else [],
        }
    frozen_mix = mixed.model_dump(mode="json")
    frozen_semantic = plan.model_dump(mode="json")
    episode = compile_episode(
        root, prepared, transcript, plan, mixed, {}, options, settings
    )
    assert mixed.model_dump(mode="json") == frozen_mix
    assert read_json(root / "episode-recipes.json") == frozen_mix
    assert read_json(root / "semantic-plan.json") == frozen_semantic
    evidence = read_json(root / "audio-plan.json")
    if music_edit == "off":
        assert not episode["music"] and not episode["fx"]
        assert evidence["removed_segment_cues"] == [
            {
                "beat_id": "effect",
                "asset_id": "original-click",
                "event_path": "/events/enter_start",
            }
        ]
        assert episode["shots"][0]["group_id"] == "Z-M00"
        assert (
            episode["shots"][0]["config"]["media"]["presenter"]["offset_seconds"] == 0.1
        )
        (applied,) = read_json(root / "compile-diagnostics.json")[
            "applied_source_only_segments"
        ]
        assert applied["original_group_id"] == "T001" and applied["locked_by_user"]
        assert (applied["start_ms"], applied["end_ms"]) == (100, 2900)
        return
    assert episode["fx"][0]["anchor_seconds"] == 0.6
    assert episode["fx"][0]["anchor_ref"] == {
        "shot_index": 0,
        "config_path": ["events", "enter_start"],
        "unit": "frames",
    }
    assert episode["music"][0]["start_seconds"] == 0.1
    assert episode["music"][0]["envelope"] == [{"seconds": 0.5, "gain_db": -4}]
    assert episode["music"][0]["gain_db"] == (-36 if music_edit else -30)
    assert evidence["fx"][0]["asset_sha256"] == click["sha256"]


@pytest.mark.parametrize(
    "problem", ["missing_recipe", "missing_relation", "wrong_layer"]
)
def test_missing_native_inputs_are_not_silently_replaced_with_plain_speech(
    tmp_path, problem
):
    root, _, prepared, transcript, plan, authoring, settings, options = protocol(
        tmp_path
    )
    if problem == "missing_recipe":
        authoring.entries = {}
    elif problem == "missing_relation":
        plan.beats[0].relation = "parallel"
    else:
        authoring.entries["effect"].placement.layer = "scene"
    with pytest.raises(EditingFailure) as error:
        compile_episode(
            root, prepared, transcript, plan, authoring, {}, options, settings
        )
    assert error.value.code == "EDITING_NATIVE_INPUTS_REQUIRED"
    assert not (root / "episode.json").exists()
    assert (
        read_json(root / "compile-diagnostics.json")["issues"][0]["group_id"] == "T001"
    )


def test_missing_original_browser_images_stop_the_episode_with_a_specific_diagnostic(
    tmp_path, monkeypatch
):
    root, _, prepared, transcript, plan, authoring, settings, options = protocol(
        tmp_path
    )
    missing = {"g05-assets/base-{i:03d}.jpg": 69}

    def missing_originals(*args, **kwargs):
        raise BrowserOriginalsMissing(plan.beats[0].group_id, missing)

    monkeypatch.setattr(
        "app.video_editing_episode_compiler.compile_native_job", missing_originals
    )
    with pytest.raises(EditingFailure) as error:
        compile_episode(
            root, prepared, transcript, plan, authoring, {}, options, settings
        )
    assert error.value.code == BROWSER_ORIGINALS_REQUIRED
    assert not (root / "episode.json").exists()
    assert read_json(root / "compile-diagnostics.json")["issues"] == [
        {
            "beat_id": plan.beats[0].id,
            "group_id": plan.beats[0].group_id,
            "code": BROWSER_ORIGINALS_REQUIRED,
            "missing_original_images": missing,
        }
    ]


def test_operator_cannot_be_presented_as_gateway_and_stale_transcript_is_rejected(
    tmp_path,
):
    root, _, prepared, transcript, plan, authoring, settings, options = protocol(
        tmp_path
    )
    authoring.planning_origin = "tengli_gateway"
    with pytest.raises(EditingFailure) as error:
        compile_episode(
            root, prepared, transcript, plan, authoring, {}, options, settings
        )
    assert error.value.code == "EDITING_PLANNER_PROVENANCE_REQUIRED"
    authoring.planning_origin = "operator_candidate"
    authoring.transcript_sha256 = "0" * 64
    with pytest.raises(EditingFailure) as error:
        compile_episode(
            root, prepared, transcript, plan, authoring, {}, options, settings
        )
    assert error.value.code == "EDITING_PLAN_SOURCE_CHANGED"
    assert not (root / "episode.json").exists()


def test_multiple_relation_items_cannot_claim_the_same_native_field(tmp_path):
    _, package, _, transcript, plan, _, _, _ = protocol(tmp_path)
    data = plan.model_dump()
    data["beats"][0]["relation_items"] = [
        {
            "id": item,
            "first_token_id": "t0",
            "last_token_id": "t2",
            "native_text_paths": ["/content/text"],
        }
        for item in ("one", "two")
    ]
    with pytest.raises(ValueError, match="share one native"):
        validate_plan(SemanticPlan.model_validate(data), transcript, package, set())
