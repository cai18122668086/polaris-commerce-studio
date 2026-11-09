import copy

import pytest

from app.motion_library import MOTION_SHA256, atomic_json, read_json
from app.motion_parameter_contracts import input_contract
from app.video_editing_contracts import SemanticBeat, Transcript, TranscriptToken
from app.video_editing_native_compiler import compile_native_job


def inputs(tmp_path):
    package = tmp_path / "library"
    group = {
        "id": "G1",
        "backend": "subtitle",
        "input_template": "template.json",
        "input_schema": "schema.json",
    }
    atomic_json(package / "catalog/groups.json", {"groups": [group]})
    atomic_json(package / "catalog/external-resources.json", {"resources": []})
    atomic_json(
        package / "template.json",
        {
            "content": {"text": "历史示例"},
            "frames": 60,
            "fps": 30,
            "events": {"start_frame": 5},
            "output": "input://historical-output",
            "style": {"fill": "#ffffff"},
        },
    )
    atomic_json(
        package / "schema.json",
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "content": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "maxLength": 8}},
                },
                "frames": {"type": "number"},
                "fps": {"type": "number"},
                "events": {"type": "object"},
                "output": {"type": "string"},
                "style": {"type": "object"},
            },
        },
    )
    contract = input_contract(package, group)
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=5000,
        provider="fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(id="t0", text="不是", start_ms=1000, end_ms=1300),
            TranscriptToken(id="t1", text="越贵越好", start_ms=1300, end_ms=2000),
        ],
    )
    beat = SemanticBeat(
        id="b",
        first_token_id="t0",
        last_token_id="t1",
        group_id="G1",
        relation="negation",
        reason="保留完整否定",
        native_text=[
            {"path": "/content/text", "first_token_id": "t0", "last_token_id": "t1"}
        ],
        native_events=[
            {"path": "/events/start_frame", "token_id": "t1", "edge": "start"}
        ],
    )
    config = read_json(package / "template.json")
    config["content"]["text"] = None
    config["events"]["start_frame"] = None
    recipe = {
        "version": "tengli.native-recipe/1",
        "release": MOTION_SHA256,
        "group_id": "G1",
        "template_sha256": contract["template_sha256"],
        "schema_sha256": contract["schema_sha256"],
        "design_id": "current-design",
        "design_reason": "本期判断的文字层",
        "parameter_decisions": {"style": "本期明确选择白字"},
        "placeholders": ["/content/text", "/events/start_frame"],
        "config": config,
    }
    return package, transcript, beat, recipe


def test_current_bound_content_and_clock_replace_history_without_mutating_library(
    tmp_path,
):
    package, transcript, beat, recipe = inputs(tmp_path)
    original = read_json(package / "template.json")
    root = tmp_path / "current-instance"
    job = compile_native_job(package, root, beat, transcript, recipe, {})
    assert job["config"]["content"]["text"] == "不是越贵越好"
    assert job["config"]["events"]["start_frame"] == 9
    assert job["config"]["frames"] == 30
    assert job["config"]["output"] == str(root / "renders/component.mp4")
    assert read_json(package / "template.json") == original
    receipt = read_json(root / "compile-receipt.json")
    assert receipt["schema_validation"] == "passed"
    assert receipt["native_execution"] == "not_performed"
    assert receipt["semantic_review"] == "unreviewed"


def test_incomplete_or_old_recipe_cannot_silently_fill_native_inputs(tmp_path):
    package, transcript, beat, recipe = inputs(tmp_path)
    variants = []
    old_content = copy.deepcopy(recipe)
    old_content["config"]["content"]["text"] = "历史示例"
    variants.append(old_content)
    old_timing = copy.deepcopy(recipe)
    old_timing["config"]["events"]["start_frame"] = 5
    variants.append(old_timing)
    no_design = copy.deepcopy(recipe)
    no_design["parameter_decisions"] = {}
    variants.append(no_design)
    other_release = copy.deepcopy(recipe)
    other_release["release"] = "0" * 64
    variants.append(other_release)
    for index, candidate in enumerate(variants):
        with pytest.raises(ValueError):
            compile_native_job(
                package, tmp_path / f"rejected-{index}", beat, transcript, candidate, {}
            )
        assert not (tmp_path / f"rejected-{index}" / "job.json").exists()


def test_scene_camera_events_are_measured_on_the_unshifted_local_clock(tmp_path):
    package, transcript, beat, recipe = inputs(tmp_path)
    group = read_json(package / "catalog/groups.json")["groups"][0]
    group.update(id="YYP06", backend="scene")
    atomic_json(package / "catalog/groups.json", {"groups": [group]})
    template = read_json(package / "template.json")
    template["events"] = {"shift_frames": -5}
    template["style"]["geometry"] = {"camera_start_frame": 15}
    atomic_json(package / "template.json", template)
    contract = input_contract(package, group)
    path = "/style/geometry/camera_start_frame"
    assert contract["event_paths"] == [{"path": path, "unit": "frames"}]
    beat.group_id = "YYP06"
    beat.native_events[0].path = path
    template["content"]["text"] = None
    template["style"]["geometry"]["camera_start_frame"] = None
    recipe.update(
        group_id="YYP06",
        template_sha256=contract["template_sha256"],
        config=template,
        placeholders=["/content/text", path],
    )
    recipe["parameter_decisions"]["events"] = "Scene choreography shift selected"
    with pytest.raises(ValueError, match="zero native shift_frames"):
        compile_native_job(package, tmp_path / "shifted", beat, transcript, recipe, {})
    template["events"]["shift_frames"] = 0
    job = compile_native_job(
        package, tmp_path / "measured", beat, transcript, recipe, {}
    )
    assert job["config"]["style"]["geometry"]["camera_start_frame"] == 9


def test_original_photo_slots_are_internal_keys_not_spoken_text(tmp_path):
    package, transcript, beat, recipe = inputs(tmp_path)
    group = read_json(package / "catalog/groups.json")["groups"][0]
    group.update(id="Z-M08", backend="unified")
    atomic_json(package / "catalog/groups.json", {"groups": [group]})
    template = read_json(package / "template.json")
    template["content"]["items"] = [{"image": "first_original_slot"}]
    atomic_json(package / "template.json", template)
    contract = input_contract(package, group)
    assert "/content/items/0/image" not in contract["text_paths"]
    assert (
        next(f for f in contract["fields"] if f["path"] == "/content/items/0/image")[
            "category"
        ]
        == "native_media_key"
    )
    beat.group_id = "Z-M08"
    recipe.update(group_id="Z-M08", template_sha256=contract["template_sha256"])
    recipe["parameter_decisions"]["content"] = (
        "Use the original slot while replacing the media"
    )
    recipe["config"]["content"]["items"] = [{"image": "relabelled"}]
    with pytest.raises(ValueError, match="original named media slot mapping"):
        compile_native_job(
            package, tmp_path / "rejected-slot", beat, transcript, recipe, {}
        )
