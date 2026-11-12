import copy
import json

import numpy as np
import pytest
from PIL import ImageFont

from app.apple_minimal.visual import caption_parts
from app.video_editing_apple_contracts import (
    PLAN_VERSION,
    AppleSuitePlan,
    build_request,
    semantic_caption_rows,
    verify_plan,
)
from app.video_editing_contracts import Transcript, TranscriptToken
from tests.test_video_editing_apple_contracts import cards, plan, span, transcript


def semantic_plan():
    value = plan()
    value.update(
        schema_version=PLAN_VERSION,
        captions=[
            {**span(a, b), "emphasis": [span(c, d)]}
            for a, b, c, d in [
                (0, 2, 2, 2),
                (3, 5, 4, 5),
                (6, 8, 7, 8),
                (9, 10, 9, 10),
                (11, 12, 11, 12),
                (13, 15, 14, 15),
                (16, 17, 17, 17),
            ]
        ],
    )
    return value


def test_single_planner_request_requires_all_caption_cues_and_keywords():
    body, _evidence = build_request(transcript(), "fixture", cards())
    payload = json.loads(body["messages"][1]["content"])
    schema = payload["output_schema"]
    assert schema["properties"]["schema_version"] == {"const": PLAN_VERSION}
    assert "captions" in schema["required"]
    assert "emphasis" in schema["$defs"]["AppleCaption"]["required"]
    assert "不能按固定字数或固定秒数截断" in body["messages"][0]["content"]


def test_full_phrase_clock_and_highlights_reach_the_last_sentence():
    value = verify_plan(
        semantic_plan(), transcript(), cards(), require_semantic_captions=True
    )
    rows = semantic_caption_rows(AppleSuitePlan.model_validate(value), transcript())
    assert "".join(r["text"] for r in rows) == "".join(
        t.text for t in transcript().tokens
    )
    assert all(r["lines"][0]["emphasis_spans"] for r in rows)
    assert rows[-1]["text"] == "现在开始"
    assert caption_parts(rows[-1]["lines"][0]) == [("现在", False), ("开始", True)]
    assert rows[0]["time"] == [0, 3] and rows[-1]["time"] == [16, 18]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda p: p["captions"].pop(), "missing the end"),
        (lambda p: p["captions"].pop(1), "every word once"),
        (
            lambda p: p["captions"].insert(1, copy.deepcopy(p["captions"][0])),
            "every word once",
        ),
        (lambda p: p["captions"][-1].update(emphasis=[]), "own planned emphasis"),
        (lambda p: p["captions"][0].update(emphasis=[span(4, 5)]), "inside its phrase"),
        (
            lambda p: p["captions"][1].update(line_break_after_token_id="w4"),
            "cross a planned line",
        ),
    ],
)
def test_incomplete_or_dropped_late_caption_plans_are_rejected(mutation, reason):
    value = semantic_plan()
    mutation(value)
    with pytest.raises(ValueError, match=reason):
        verify_plan(value, transcript(), cards())


def test_legacy_output_cannot_bypass_new_model_caption_requirement():
    with pytest.raises(ValueError, match="full-script semantic"):
        verify_plan(plan(), transcript(), cards(), require_semantic_captions=True)


def make_transcript(words):
    return Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=len(words) * 1000,
        provider="fixture",
        model="clock",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=f"w{i}", text=s, start_ms=i * 1000, end_ms=(i + 1) * 1000
            )
            for i, s in enumerate(words)
        ],
    )


def test_word_split_is_rejected_even_when_asr_has_one_token_per_character():
    value = semantic_plan()
    value["captions"] = [{**span(0, 1), "emphasis": []}, {**span(2, 4), "emphasis": []}]
    with pytest.raises(ValueError, match="splits a lexical word"):
        semantic_caption_rows(
            AppleSuitePlan.model_validate(value),
            make_transcript(["点击", "参", "考", "商", "品"]),
        )


@pytest.mark.parametrize(
    "words", [["上传", "300", "毫升", "包装"], ["试用", "Open", "AI", "工具"]]
)
def test_subtitle_boundary_preserves_complete_number_units_and_english_names(words):
    value = semantic_plan()
    value["captions"] = [
        {**span(0, 1), "emphasis": [span(0, 0)]},
        {**span(2, 3), "emphasis": [span(2, 3)]},
    ]
    with pytest.raises(ValueError, match="splits a lexical word"):
        semantic_caption_rows(
            AppleSuitePlan.model_validate(value), make_transcript(words)
        )


def test_repeated_keyword_targets_the_selected_occurrence_and_preserves_whole_cue():
    value = semantic_plan()
    value["captions"] = [
        {
            **span(0, 4),
            "emphasis": [span(2, 2), span(4, 4)],
            "line_break_after_token_id": "w1",
        }
    ]
    source = make_transcript(["先上传", "产品图，", "产品图", "决定", "效果"])
    rows = semantic_caption_rows(AppleSuitePlan.model_validate(value), source)
    assert rows[0]["time"] == [0, 5]
    assert caption_parts(rows[0]["lines"][0]) == [("先上传产品图，", False)]
    assert caption_parts(rows[0]["lines"][1]) == [
        ("产品图", True),
        ("决定", False),
        ("效果", True),
    ]


@pytest.mark.parametrize("color", ["white", "black"])
def test_late_two_line_caption_retains_blue_keyword_on_both_backgrounds(
    monkeypatch, color
):
    from app.apple_minimal import visual

    monkeypatch.setattr(
        visual, "font", lambda _path, size: ImageFont.load_default(size=round(size))
    )
    cfg = {
        "size": [540, 960],
        "fps": 25,
        "fonts": {"caption": "fixture", "caption_bold": "fixture"},
        "captions": [
            {
                "time": [32, 36],
                "text": "first phrase second phrase",
                "color": color,
                "lines": [
                    {"text": "first phrase", "emphasis_spans": []},
                    {"text": "second phrase", "emphasis_spans": [[0, 6]]},
                ],
            }
        ],
    }
    actual = np.asarray(visual.render_subtitle("T05", 34 * 25, cfg)["caption"])
    blue = (actual[:, :, :3] == [0, 151, 233]).all(axis=2) & (actual[:, :, 3] > 200)
    assert blue.sum() > 20
    assert np.where(blue)[0].min() > (800 if color == "white" else 838)


def test_scene_color_change_keeps_the_same_complete_caption_and_keywords(monkeypatch):
    from app.apple_minimal import visual

    monkeypatch.setattr(
        visual, "font", lambda _p, size: ImageFont.load_default(size=round(size))
    )
    row = {
        "time": [30, 36],
        "text": "complete sentence",
        "lines": [{"text": "complete sentence", "emphasis_spans": [[0, 8]]}],
    }
    cfg = {
        "size": [540, 960],
        "fps": 25,
        "fonts": {"caption": "fixture", "caption_bold": "fixture"},
        "captions": [row],
        "caption_color_events": [
            {"time": 0, "color": "black"},
            {"time": 33, "color": "white"},
        ],
    }
    for second, body in [(32, [12, 12, 12]), (34, [255, 255, 255])]:
        im = np.asarray(visual.render_subtitle("T05", second * 25, cfg)["caption"])
        assert (
            (im[:, :, :3] == [0, 151, 233]).all(axis=2) & (im[:, :, 3] > 200)
        ).sum() > 20
        assert ((im[:, :, :3] == body).all(axis=2) & (im[:, :, 3] > 200)).sum() > 20
    assert cfg["captions"] == [row]
