from concurrent.futures import ThreadPoolExecutor

import pytest

from app.video_editing_contracts import Transcript, TranscriptToken
from app.video_editing_tutorial_plan import (
    RecordingActivity,
    accept_output,
    content_context,
    legacy_suite_intent,
    load_plan,
    planning_hint,
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


def test_unfittable_recordings_show_large_view_through_the_voice_gap(
    tmp_path,
):
    transcript, context, intent = inputs()
    shared = save_plan(tmp_path, context, intent, transcript, {"kind": "fixture"})
    clock = schedule(shared, transcript)
    first, second = clock["steps"]
    assert first["start_ms"] == 2000
    assert first["playback_end_ms"] == 5500
    assert first["end_ms"] == second["start_ms"] == 5500
    assert second["source_in_ms"] == 0 and second["source_out_ms"] == 5000
    assert first["large_start_ms"] == 5000
    assert second["large_start_ms"] == 9500
    assert first["tail_hold_ms"] == second["tail_hold_ms"] == 0
    assert clock["duration_ms"] > transcript.duration_ms
    # The previous word ends before a pause; the next word starts after it.
    assert source_to_output(clock, 5000, end=True) == 5000
    assert source_to_output(clock, 5000) == 5500
    assert all(
        any(
            step["large_start_ms"] is not None
            and step["large_start_ms"] <= hold["output_start_ms"]
            and step["end_ms"] >= hold["output_start_ms"] + hold["duration_ms"]
            for step in clock["steps"]
        )
        for hold in clock["holds"]
    )


def test_steady_recording_sections_fit_without_interrupting_narration(tmp_path):
    transcript, context, intent = inputs()
    shared = save_plan(tmp_path, context, intent, transcript, {})
    clock = schedule(
        shared,
        transcript,
        {
            "upload": RecordingActivity(steady=((0, 1600),)),
            "reference": RecordingActivity(steady=((2000, 5000),)),
        },
    )
    assert clock["duration_ms"] == transcript.duration_ms
    assert clock["holds"] == []
    for step, native in zip(clock["steps"], (3500, 5000), strict=True):
        segments = step["playback_segments"]
        assert segments[0]["source_in_ms"] == 0
        assert segments[-1]["source_out_ms"] == native
        assert all(
            a["source_out_ms"] == b["source_in_ms"]
            for a, b in zip(segments, segments[1:], strict=False)
        )
        assert any(
            seg["source_out_ms"] - seg["source_in_ms"] > seg["output_ms"]
            for seg in segments
        )
        assert step["playback_end_ms"] <= step["end_ms"]


def test_saved_planning_requests_keep_original_prompt_after_playback_change():
    _, context, _ = inputs()
    assert "不截短、不加速" in planning_hint(context)["policy"]
    assert "倍速、单个大录屏" in planning_hint(context, adaptive=True)["policy"]


def test_long_detailed_recording_can_continue_between_spoken_clauses(tmp_path):
    transcript, context, intent = inputs()
    transcript.tokens[6] = transcript.tokens[6].model_copy(update={"text": "图，"})
    cards = [
        {**card, "duration_ms": 11500} if card["id"] == "reference" else card
        for card in context["recordings"]
    ]
    context = content_context("owned-source", transcript, cards)
    shared = save_plan(tmp_path, context, intent, transcript, {})

    clock = schedule(shared, transcript, quiet={7000: 7100})

    second = clock["steps"][1]
    clause_gap, final_gap = clock["holds"][1:]
    assert second["large_start_ms"] == second["start_ms"]
    assert clause_gap["source_ms"] == 7100 and clause_gap["word_boundary_ms"] == 7000
    assert final_gap["source_ms"] == 9000 and final_gap["duration_ms"] == 750
    assert second["playback_end_ms"] == second["end_ms"]


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


def test_all_installed_website_styles_have_a_distinct_readable_recording_surface():
    from app.bihuo_suite.registry import definitions
    from app.video_editing_apple_pipeline import TEMPLATE_ID
    from app.video_editing_template_styles import PUBLIC_TEMPLATE_IDS
    from app.video_editing_tutorial_surfaces import SIZE, chrome, large_chrome, surface

    ids = [
        TEMPLATE_ID,
        *PUBLIC_TEMPLATE_IDS,
        *(tid for tid, meta in definitions().items() if meta.get("enabled", True)),
    ]
    names = set()
    for template_id in ids:
        layout = surface(template_id)
        assert layout.name != "inset" and layout.name not in names
        names.add(layout.name)
        x, y, width, height = layout.viewport
        assert x >= 0 and y >= 0 and x + width <= SIZE[0] and y + height <= SIZE[1]
        assert width >= SIZE[0] * 0.75
        full = large_chrome(layout, template_id, {"label": "01_上传产品图"})
        assert full.size == SIZE and full.getchannel("A").getextrema() == (255, 255)
        if layout.native_box:
            nx, ny, nw, nh = layout.native_box
            assert nx >= 0 and ny >= 0 and nx + nw <= SIZE[0] and ny + nh <= SIZE[1]
            assert ny + nh <= y or ny >= y + height
            assert chrome(layout, template_id, {}, []).size == SIZE


def test_tutorial_caption_wraps_long_chinese_at_the_larger_size(tmp_path):
    from app.video_editing_tutorial_render import caption_file
    from app.video_editing_tutorial_surfaces import fonts_for, surface

    text = "按顺序选择参考图片确认生成结果并检查排版"
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=2500,
        provider="fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=f"w{i}", text=char, start_ms=100 * i, end_ms=100 * (i + 1)
            )
            for i, char in enumerate(text)
        ],
    )
    template = "azl-panels-v1"
    clock = {"steps": [{"start_ms": 0, "end_ms": 2500}], "holds": []}
    path = caption_file(
        tmp_path, transcript, clock, surface(template), fonts_for(template)[1]
    )
    script = path.read_text(encoding="utf-8")
    assert ",62," in script and ",68,68,318,1" in script
    [cue] = [
        line.split(",,", 2)[-1]
        for line in script.splitlines()
        if line.startswith("Dialogue:")
    ]
    assert len(cue.split(r"\N")) == 2
    assert cue.replace(r"\N", "") == text


def test_single_unplaced_recording_plays_through_the_body(tmp_path):
    transcript, context, _ = inputs()
    one = {**context, "recordings": context["recordings"][:1]}
    raw = {
        "opening": {"intro_last_token_id": "w1"},
        "materials": [],
        "conclusion": {"first": {"first_token_id": "w10"}},
    }
    native, shared = accept_output(raw, one, transcript, tmp_path, {"task": "t"})
    assert native == raw
    assert shared["intent"]["steps"] == [
        {"asset_id": "reference", "first_token_id": "w2", "last_token_id": "w9"}
    ]
    assert shared["origin"]["fallback"] == "single_recording_whole_body"


def test_single_recording_fallback_needs_an_opening(tmp_path):
    transcript, context, _ = inputs()
    one = {**context, "recordings": context["recordings"][:1]}
    with pytest.raises(ValueError, match="Missing shared tutorial_steps"):
        accept_output({"materials": []}, one, transcript, tmp_path, {})
