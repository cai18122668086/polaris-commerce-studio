"""Regression from a saved real response; no inference or billed request."""

import copy
import json
from pathlib import Path

import pytest

from app import video_editing_apple_contracts as apple
from app.bihuo_suite import planning
from app.video_editing_contracts import Transcript


def case():
    data = json.loads(
        (Path(__file__).parent / "fixtures/bihuo_interleaved_body.json").read_text(
            "utf-8"
        )
    )
    return data["plan"], Transcript.model_validate(data["transcript"])


def test_actual_interleaved_response_keeps_original_words_and_times():
    raw, transcript = case()
    with pytest.raises(ValueError, match="Body phrases must follow source order"):
        apple.verify_plan(raw, transcript, [], allow_mixed_body=True)
    verified = planning.verify_plan(raw, transcript, [], require_semantic_captions=True)
    assert verified == apple.AppleSuitePlan.model_validate(raw).model_dump(mode="json")
    captured = {}

    def recipe(resolved, **_options):
        captured.update(resolved)
        return resolved

    planning.compile_render_input(
        raw, transcript, {}, "unchanged-source.mp4", {}, recipe_compiler=recipe
    )
    assert captured["points"][2]["start"] == 12.809
    assert captured["features"][0]["start"] == 5.79
    assert captured["features"][2]["start"] == 13.83
    assert captured["tokens"] == [
        word.model_dump(mode="json") for word in transcript.tokens
    ]
    assert len(captured["captions"]) == 14


@pytest.mark.parametrize(
    "bad", ["reorder_points", "reorder_features", "opening_feature", "missing_caption"]
)
def test_independent_roles_still_reject_invalid_source_bindings(bad):
    raw, transcript = case()
    raw = copy.deepcopy(raw)
    if bad == "reorder_points":
        raw["points"].reverse()
    elif bad == "reorder_features":
        raw["features"].reverse()
    elif bad == "opening_feature":
        raw["features"][0] = raw["opening"]["title"]
    else:
        raw["captions"].pop()
    with pytest.raises(ValueError):
        planning.verify_plan(raw, transcript, [], require_semantic_captions=True)


def test_previously_valid_plan_compiles_identically():
    raw, transcript = case()
    raw["features"] = []

    def recipe(resolved, **options):
        return {"resolved": resolved, "options": options}

    args = (raw, transcript, {}, "unchanged-source.mp4", {})
    assert planning.compile_render_input(
        *args, recipe_compiler=recipe
    ) == apple.compile_render_input(*args, recipe_compiler=recipe)


def conclusion_case():
    data = json.loads(
        (Path(__file__).parent / "fixtures/bihuo_conclusion_feature.json").read_text(
            "utf-8"
        )
    )
    return data["plan"], Transcript.model_validate(data["transcript"])


def test_actual_conclusion_duplicate_is_optional_and_keeps_spoken_content():
    raw, transcript = conclusion_case()
    original = copy.deepcopy(raw)
    verified = planning.verify_plan(raw, transcript, [], require_semantic_captions=True)
    assert raw == original
    assert verified["features"] == raw["features"][:2]
    assert verified["conclusion"] == raw["conclusion"]
    assert (
        verified["captions"]
        == apple.AppleSuitePlan.model_validate(raw).model_dump()["captions"]
    )
    assert "原话保留" in verified["warnings"][-1]
    result = planning.compile_render_input(
        raw,
        transcript,
        {},
        "same-source.mp4",
        {},
        recipe_compiler=lambda resolved, **_: resolved,
    )
    assert len(result["tokens"]) == 101
    assert len(result["captions"]) == len(raw["captions"])
    assert len(result["features"]) == 2


@pytest.mark.parametrize(
    "bad",
    ["unknown", "reverse", "too_long", "cross_quote", "outside_conclusion", "reorder"],
)
def test_conclusion_duplicate_never_hides_invalid_bindings(bad):
    raw, transcript = conclusion_case()
    ids = [token.id for token in transcript.tokens]
    row = raw["features"][-1]
    if bad == "unknown":
        row["first_token_id"] = "unknown"
    elif bad == "reverse":
        row["first_token_id"], row["last_token_id"] = (
            row["last_token_id"],
            row["first_token_id"],
        )
    elif bad == "too_long":
        row["first_token_id"], row["last_token_id"] = ids[74], ids[100]
    elif bad == "cross_quote":
        row["first_token_id"], row["last_token_id"] = ids[82], ids[84]
    elif bad == "outside_conclusion":
        raw["conclusion"]["second"]["last_token_id"] = ids[94]
    else:
        raw["features"].reverse()
    with pytest.raises(ValueError):
        planning.verify_plan(raw, transcript, [], require_semantic_captions=True)
