from concurrent.futures import ThreadPoolExecutor

import pytest

from app.video_editing_contracts import Transcript, TranscriptToken
from app.video_editing_tutorial_plan import (
    accept_output,
    content_context,
    legacy_suite_intent,
    load_plan,
    save_plan,
    schedule,
    source_to_output,
    validate_intent,
)


def inputs():
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=len("开场上传产品再选参考结果收尾") * 1000,
        provider="fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=f"w{i}", text=text, start_ms=i * 1000, end_ms=(i + 1) * 1000
            )
            for i, text in enumerate("开场上传产品再选参考结果收尾")
        ],
    )
    cards = [
        {
            "id": "upload",
            "kind": "video",
            "sha256": "c" * 64,
            "duration_ms": 3500,
            "semantic_use": "上传产品",
            "viewed_identity": "上传产品",
        },
        {
            "id": "reference",
            "kind": "video",
            "sha256": "d" * 64,
            "duration_ms": 5000,
            "semantic_use": "选择参考",
            "viewed_identity": "选择参考",
        },
    ]
    context = content_context("owned-source", transcript, cards)
    intent = {
        "steps": [
            {"asset_id": "upload", "first_token_id": "w2", "last_token_id": "w4"},
            {"asset_id": "reference", "first_token_id": "w5", "last_token_id": "w8"},
        ]
    }
    return transcript, context, intent


def test_full_recordings_and_reading_tail_own_handoff_not_template_scene_length(
    tmp_path,
):
    transcript, context, intent = inputs()
    shared = save_plan(tmp_path, context, intent, transcript, {"kind": "fixture"})
    clock = schedule(shared, transcript)
    first, second = clock["steps"]
    assert first["start_ms"] == 2000
    assert first["playback_end_ms"] == 5500
    assert first["end_ms"] == second["start_ms"] == 6000
    assert second["source_in_ms"] == 0 and second["source_out_ms"] == 5000
    assert second["tail_hold_ms"] >= 500
    assert clock["duration_ms"] > transcript.duration_ms
    # The previous word ends before a pause; the next word starts after it.
    assert source_to_output(clock, 5000, end=True) == 5000
    assert source_to_output(clock, 5000) == 6000


def test_content_plan_is_shared_across_templates_and_replayed_without_model_calls(
    tmp_path,
):
    transcript, context, intent = inputs()
    first = save_plan(
        tmp_path, context, intent, transcript, {"planning_task_id": "one"}
    )
    for template in [
        "bihuo-02-v1",
        "bihuo-36-v1",
        "product-explainer-v1",
        "azl-panels-v1",
    ]:
        native, shared = accept_output(
            {"template": template}, context, transcript, tmp_path, {}
        )
        assert shared["sha256"] == first["sha256"]
        assert schedule(shared, transcript) == schedule(first, transcript)
        assert native == {"template": template}


def test_legacy_bindings_keep_instruction_start_and_context_through_next_step():
    transcript, context, _ = inputs()
    raw = {
        "materials": [
            {
                "asset_id": "upload",
                "first_token_id": "w2",
                "last_token_id": "w3",
                "show_at_token_id": "w3",
            },
            {
                "asset_id": "reference",
                "first_token_id": "w5",
                "last_token_id": "w6",
                "show_at_token_id": "w6",
            },
        ],
        "conclusion": {"first": {"first_token_id": "w9"}},
    }
    intent = legacy_suite_intent(raw, transcript, context)
    assert intent["steps"][0]["first_token_id"] == "w2"
    assert intent["steps"][0]["last_token_id"] == "w4"
    assert intent["steps"][1]["last_token_id"] == "w8"
    assert raw["materials"][0]["show_at_token_id"] == "w3"


def test_missing_selected_recording_is_blocked_instead_of_becoming_a_successful_export(
    tmp_path,
):
    transcript, context, intent = inputs()
    with pytest.raises(ValueError, match="missing selected recordings"):
        validate_intent({"steps": intent["steps"][:1]}, transcript, context)
    with pytest.raises(ValueError, match="Missing shared tutorial_steps"):
        accept_output({"materials": []}, context, transcript, tmp_path, {})


def test_concurrent_templates_select_one_complete_shared_plan(tmp_path):
    transcript, context, intent = inputs()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda i: save_plan(tmp_path, context, intent, transcript, {"task": i}),
                range(2),
            )
        )
    assert results[0]["sha256"] == results[1]["sha256"]
    assert load_plan(tmp_path, context, transcript)["sha256"] == results[0]["sha256"]
