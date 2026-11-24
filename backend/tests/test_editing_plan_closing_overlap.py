"""Saved real response whose optional closing repeats the body (F-15)."""

import copy
import json
from pathlib import Path

import pytest

from app.bihuo_suite import planning
from app.video_editing_contracts import Transcript
from app.video_planner_policy import normalize_suite_output


def load(name):
    data = json.loads((Path(__file__).parent / "fixtures" / name).read_text("utf-8"))
    return data["plan"], Transcript.model_validate(data["transcript"])


def test_saved_response_fails_strictly_without_the_closing_adaptation():
    raw, transcript = load("bihuo_closing_overlap.json")
    with pytest.raises(ValueError, match="before the quote"):
        planning.verify_plan(raw, transcript, [], require_semantic_captions=True)


def test_overlapping_optional_closing_is_omitted_and_body_is_kept():
    raw, transcript = load("bihuo_closing_overlap.json")
    original = copy.deepcopy(raw)
    changed, repairs = normalize_suite_output(raw, transcript)
    assert raw == original
    assert repairs == [
        {
            "kind": "optional_closing_omitted",
            "quote_start_token_id": original["quote_start_token_id"],
            "reason": "body_phrase_overlaps_closing",
        }
    ]
    assert changed["conclusion"] is None and changed["quote_start_token_id"] is None
    verified = planning.verify_plan(
        changed, transcript, [], require_semantic_captions=True
    )
    assert verified["points"] == original["points"]
    assert verified["features"] == original["features"]
    assert len(verified["captions"]) == len(original["captions"])
    result = planning.compile_render_input(
        changed,
        transcript,
        {},
        "same-source.mp4",
        {},
        recipe_compiler=lambda resolved, **_: resolved,
    )
    assert len(result["tokens"]) == len(transcript.tokens)
    assert len(result["features"]) == 1


def test_distinct_closing_and_duplicate_only_overlap_are_untouched():
    for name in ("bihuo_conclusion_feature.json", "bihuo_interleaved_body.json"):
        raw, transcript = load(name)
        changed, repairs = normalize_suite_output(raw, transcript)
        assert changed.get("conclusion") == raw.get("conclusion")
        assert not [r for r in repairs if r.get("kind") == "optional_closing_omitted"]
