"""Saved real suite plans that failed in the 2026-11-25 template e2e run.

* bihuo-28 (planning 522b996f): the last point repeats the first closing layer,
  so the point starts at the quote.
* bihuo-33 (planning 80226f8c): every caption keyword came back as
  ``{"Well": "<token id>"}`` instead of a span.
* bihuo-34 (planning 375daaef): every span carried an empty ``"net": null``.
"""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.bihuo_suite import planning
from app.video_editing_contracts import Transcript
from app.video_planner_policy import normalize_suite_output


def load(name):
    data = json.loads((Path(__file__).parent / "fixtures" / name).read_text("utf-8"))
    return data["plan"], Transcript.model_validate(data["transcript"])


def verify(plan, transcript):
    return planning.verify_plan(plan, transcript, [], require_semantic_captions=True)


def test_point_repeating_the_closing_is_omitted_and_closing_kept():
    raw, transcript = load("bihuo28_point_repeats_closing.json")
    with pytest.raises(ValueError, match="before the quote"):
        verify(raw, transcript)
    original = copy.deepcopy(raw)
    changed, repairs = normalize_suite_output(raw, transcript)
    assert raw == original
    assert repairs == [
        {
            "kind": "duplicate_point_omitted",
            "first_token_id": original["points"][2]["first_token_id"],
            "last_token_id": original["points"][2]["last_token_id"],
            "reason": "point_repeats_closing_phrase",
        }
    ]
    plan = verify(changed, transcript)
    assert plan["points"] == original["points"][:2]
    assert plan["conclusion"] == original["conclusion"]
    assert plan["quote_start_token_id"] == original["quote_start_token_id"]
    assert len(plan["captions"]) == len(original["captions"])


def test_point_overlapping_but_not_repeating_still_releases_the_closing():
    raw, transcript = load("bihuo28_point_repeats_closing.json")
    # Extend the duplicate point past the closing phrase: not a pure repeat.
    raw["points"][2]["last_token_id"] = raw["conclusion"]["second"]["first_token_id"]
    changed, repairs = normalize_suite_output(raw, transcript)
    kinds = [row["kind"] for row in repairs]
    assert "optional_closing_omitted" in kinds
    assert "duplicate_point_omitted" not in kinds
    assert changed["conclusion"] is None


def test_single_key_caption_keywords_become_recorded_word_spans():
    raw, transcript = load("bihuo33_keyword_shape.json")
    with pytest.raises(ValidationError):
        verify(raw, transcript)
    changed, repairs = normalize_suite_output(raw, transcript)
    shaped = [r for r in repairs if r["kind"] == "caption_emphasis_shape_repaired"]
    assert len(shaped) == 8
    text = {t.id: t.text for t in transcript.tokens}
    ids = [t.id for t in transcript.tokens]

    def words(span):
        a, b = ids.index(span["first_token_id"]), ids.index(span["last_token_id"])
        return "".join(text[i] for i in ids[a : b + 1])

    # Each bare token grows to the lexical word that holds it, never further.
    assert [words(r["to"]) for r in shaped[:3]] == ["办公桌", "降噪，", "安静"]
    for row in shaped:
        assert ids.index(row["to"]["first_token_id"]) <= ids.index(row["token_id"])
        assert ids.index(row["token_id"]) <= ids.index(row["to"]["last_token_id"])
    plan = verify(changed, transcript)
    assert sum(len(cue["emphasis"]) for cue in plan["captions"]) == 8


def test_unrecognised_keyword_shapes_still_fail_strictly():
    raw, transcript = load("bihuo33_keyword_shape.json")
    raw["captions"][1]["emphasis"] = [{"Well": "not-a-recorded-word"}]
    changed, _ = normalize_suite_output(raw, transcript)
    with pytest.raises(ValidationError):
        verify(changed, transcript)


def test_null_extra_fields_are_removed_but_real_extras_still_fail():
    raw, transcript = load("bihuo34_null_extra_fields.json")
    with pytest.raises(ValidationError):
        verify(raw, transcript)
    changed, repairs = normalize_suite_output(raw, transcript)
    removed = next(r for r in repairs if r["kind"] == "null_extra_fields_removed")
    assert "opening.subtitle.net" in removed["fields"]
    assert "captions.9.emphasis.0.net" in removed["fields"]
    assert len(removed["fields"]) == 26
    plan = verify(changed, transcript)
    assert len(plan["points"]) == 3 and len(plan["features"]) == 2

    raw, transcript = load("bihuo34_null_extra_fields.json")
    raw["points"][0]["net"] = "x"  # A non-empty extra field is not a slip.
    changed, _ = normalize_suite_output(raw, transcript)
    with pytest.raises(ValidationError):
        verify(changed, transcript)
