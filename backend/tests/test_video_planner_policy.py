import json

import pytest

from app.errors import ApiError
from app.video_planner_policy import (
    EMPTY_RESPONSE,
    bind_selected_native_assets,
    json_planning_options,
    normalize_azl_windows,
    normalize_material_anchors,
    normalize_suite_output,
    require_planning_content,
    saved_response_empty,
)


def test_json_planning_uses_a_model_specific_thinking_control():
    assert json_planning_options("deepseek-v4.1-flash-1017") == {
        "thinking": {"type": "disabled"}
    }
    assert json_planning_options("gpt-6.1-sol") == {}


@pytest.mark.parametrize("value", ["", "  \n", None])
def test_saved_empty_response_requires_a_new_explicitly_billed_request(tmp_path, value):
    response = {"content": value, "usage": {"completion_tokens": 8192}}
    (tmp_path / "semantic-response.json").write_text(json.dumps(response))
    assert saved_response_empty(tmp_path)
    with pytest.raises(ApiError) as error:
        require_planning_content(response)
    assert error.value.code == EMPTY_RESPONSE
    assert "新的模型费用" in error.value.message


def test_nonempty_saved_response_still_supports_free_contract_revalidation(tmp_path):
    response = {"content": '{"plan": true}'}
    (tmp_path / "semantic-response.json").write_text(json.dumps(response))
    assert not saved_response_empty(tmp_path)
    assert require_planning_content(response) == response["content"]


def test_missing_or_damaged_saved_envelope_is_not_misreported_as_empty(tmp_path):
    assert not saved_response_empty(tmp_path)
    (tmp_path / "semantic-response.json").write_text("{broken")
    assert not saved_response_empty(tmp_path)
    assert json_planning_options("gpt-6.1-sol") == {}


def test_material_anchor_bounds_preserve_raw_response_and_unknown_words():
    from tests.test_video_editing_apple_contracts import transcript

    raw = {
        "materials": [
            {
                "asset_id": "clip",
                "first_token_id": "w3",
                "last_token_id": "w5",
                "show_at_token_id": "w6",
                "edge": "end",
            },
            {
                "asset_id": "invalid",
                "first_token_id": "w3",
                "last_token_id": "w5",
                "show_at_token_id": "invented",
            },
        ]
    }
    normalized, repairs = normalize_material_anchors(raw, transcript())
    assert raw["materials"][0]["show_at_token_id"] == "w6"
    assert normalized["materials"][0]["show_at_token_id"] == "w5"
    assert normalized["materials"][1]["show_at_token_id"] == "invented"
    assert len(repairs) == 1


def test_suite_prefix_and_optional_heading_adaptations_preserve_raw_data():
    from tests.test_video_editing_apple_contracts import transcript

    t = transcript()
    raw = {
        "captions": [{"first_token_id": "w2", "last_token_id": "w5", "emphasis": []}],
        "chapters": [
            {"first_token_id": "w0", "last_token_id": "w17", "at_token_id": "w0"}
        ],
    }
    changed, repairs = normalize_suite_output(raw, t)
    assert changed["captions"][0]["first_token_id"] == "w0"
    assert changed["chapters"] == []
    assert raw["captions"][0]["first_token_id"] == "w2"
    assert {r["kind"] for r in repairs} == {
        "caption_prefix",
        "optional_chapter_omitted",
    }


def test_native_asset_bindings_only_add_already_selected_ids():
    raw = {
        "beats": [
            {"id": "b0", "asset_ids": [], "native_media": [{"asset_id": "selected"}]},
            {"id": "b1", "asset_ids": [], "native_media": [{"asset_id": "invented"}]},
        ]
    }
    changed, repairs = bind_selected_native_assets(raw, [{"id": "selected"}])
    assert changed["beats"][0]["asset_ids"] == ["selected"]
    assert changed["beats"][1]["asset_ids"] == []
    assert raw["beats"][0]["asset_ids"] == []
    assert repairs == [{"beat_id": "b0", "added_selected_assets": ["selected"]}]


def test_editorial_caption_reflow_keeps_the_recorded_span_and_saved_response():
    from app.video_editing_contracts import TranscriptToken
    from tests.test_video_editing_apple_contracts import transcript

    text = "按顺序选择参考图片确认生成结果并检查排版"
    source = transcript()
    source.tokens = [
        TranscriptToken(id=f"w{i}", text=char, start_ms=i * 100, end_ms=(i + 1) * 100)
        for i, char in enumerate(text)
    ]
    cue = {
        "first_token_id": "w0",
        "last_token_id": f"w{len(text) - 1}",
        "line_break_after_token_id": None,
        "emphasis": [],
    }
    raw = {"captions": [cue]}
    changed, repairs = normalize_suite_output(raw, source, repair_caption_lines=True)
    [row] = changed["captions"]
    assert row["line_break_after_token_id"] is not None
    assert {**row, "line_break_after_token_id": None} == cue
    assert cue["line_break_after_token_id"] is None
    assert repairs[0]["kind"] == "editorial_caption_line"
    assert normalize_suite_output(raw, source)[0] == raw


@pytest.mark.parametrize("unsafe", [False, True])
def test_measured_azl_window_only_absorbs_plain_contiguous_source(unsafe):
    from tests.test_video_editing_apple_contracts import transcript

    events = [{"path": "/panel/out", "token_id": "w5", "edge": "end"}]
    raw = {
        "beats": [
            {
                "id": "panel",
                "group_id": "AZL04",
                "first_token_id": "w0",
                "last_token_id": "w2",
                "native_events": events,
                "native_media": [{"path": "/media/left/path", "asset_id": "selected"}],
            },
            {
                "id": "plain",
                "group_id": "Z-M00",
                "first_token_id": "w3",
                "last_token_id": "w5",
                "native_text": [{"text": "preserve"}]
                if unsafe
                else [
                    {
                        "path": "/content/captions/0/text",
                        "first_token_id": "w3",
                        "last_token_id": "w5",
                    }
                ],
            },
        ]
    }
    runtime = {
        "azl_panel_windows": [
            {
                "first_token_id": "w0",
                "last_token_id": "w5",
                "group_ids": ["AZL04"],
                "native_events": events,
                "material_ids": ["selected"],
            }
        ]
    }
    changed, repairs = normalize_azl_windows(raw, transcript(), runtime)
    assert raw["beats"][0]["last_token_id"] == "w2"
    assert len(changed["beats"]) == (2 if unsafe else 1)
    assert bool(repairs) is not unsafe
    if not unsafe:
        assert changed["beats"][0]["last_token_id"] == "w5"
