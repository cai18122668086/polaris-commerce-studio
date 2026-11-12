import copy

import pytest

from app.video_editing_apple_contracts import AppleSuitePlan, semantic_caption_rows
from app.video_editing_caption_emphasis import (
    emphasis_budget,
    readable,
    sparse_caption_emphasis,
)
from tests.test_video_editing_apple_contracts import cards, transcript, verify_plan
from tests.test_video_editing_semantic_captions import semantic_plan


@pytest.mark.parametrize(
    "text,expected",
    [
        ("产品是否清楚，", ["产品"]),
        ("先看主图，", ["主图"]),
        ("再看详情，", ["详情"]),
        ("规格和使用场景有没有讲完整。", ["规格", "场景"]),
        ("逐张核对。", ["核对"]),
    ],
)
def test_whole_blue_caption_becomes_sparse_content_words_without_changing_text_or_clock(
    text, expected
):
    row = {
        "text": text,
        "time": [12, 15],
        "lines": [{"text": text, "emphasis_spans": [[0, len(text)]]}],
    }
    original = copy.deepcopy(row)
    result = sparse_caption_emphasis([row])[0]
    accents = [text[a:b] for a, b in result["lines"][0]["emphasis_spans"]]
    assert accents == expected
    assert result["text"] == text and result["time"] == [12, 15]
    assert result["emphasis_characters"] <= emphasis_budget(text)
    assert result["body_characters"] >= result["emphasis_characters"]
    assert row == original


def test_adjacent_model_highlights_cannot_color_almost_the_entire_line():
    text = "核心卖点能不能一眼看懂。"
    result = sparse_caption_emphasis(
        [
            {
                "text": text,
                "time": [5, 8],
                "lines": [{"text": text, "emphasis_spans": [[0, 4], [7, 11]]}],
            }
        ]
    )[0]
    assert result["emphasis"] == "核心卖点"
    assert result["emphasis_characters"] == 4 and result["body_characters"] == 7
    assert result["lines"][0]["emphasis_spans"] == [[0, 4]]


def test_transition_can_stay_plain_and_unselected_words_are_not_promoted():
    rows = [
        {
            "text": "你看，",
            "time": [1, 2],
            "lines": [{"text": "你看，", "emphasis_spans": []}],
        }
    ]
    result = sparse_caption_emphasis(rows)
    assert result[0]["lines"][0]["emphasis_spans"] == []
    value = semantic_plan()
    value["captions"][-1]["emphasis"] = []
    verify_plan(value, transcript(), cards(), require_semantic_captions=True)
    rendered = semantic_caption_rows(AppleSuitePlan.model_validate(value), transcript())
    assert rendered[-1]["lines"][0]["emphasis_spans"] == []


def test_two_line_cue_keeps_body_text_dominant_and_never_rewrites_lines():
    row = {
        "text": "颜色和排版是不是统一规格和使用场景有没有讲完整",
        "time": [9, 14],
        "lines": [
            {"text": "颜色和排版是不是统一", "emphasis_spans": [[0, 10]]},
            {"text": "规格和使用场景有没有讲完整", "emphasis_spans": [[0, 13]]},
        ],
    }
    result = sparse_caption_emphasis([row])[0]
    assert [line["text"] for line in result["lines"]] == [
        line["text"] for line in row["lines"]
    ]
    assert sum(len(line["emphasis_spans"]) for line in result["lines"]) <= 2
    assert result["emphasis_characters"] <= emphasis_budget(row["text"])
    assert all(
        sum(readable(line["text"][a:b]) for a, b in line["emphasis_spans"])
        <= emphasis_budget(line["text"])
        for line in result["lines"]
    )
