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
