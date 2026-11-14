"""Regression from a saved real response; no inference or billed request."""

import copy
import json
from pathlib import Path

import pytest

from app import video_editing_apple_contracts as apple
from app.bihuo_suite import planning, registry
from app.video_editing_contracts import Transcript


def case():
    data = json.loads(
        (Path(__file__).parent / "fixtures/bihuo_interleaved_body.json").read_text(
            "utf-8"
        )
    )
    return data["plan"], Transcript.model_validate(data["transcript"])


def test_saved_real_display_capacity_recovers_without_rewriting_provider_content():
    data = json.loads(
        (Path(__file__).parent / "fixtures/bihuo_display_capacity.json").read_text(
            "utf-8"
        )
    )
    raw = data["plan"]
    original = copy.deepcopy(raw)
    transcript = Transcript.model_validate(data["transcript"])
    with pytest.raises(ValueError, match="reading capacity"):
        apple.verify_plan(
            raw,
            transcript,
            data["asset_cards"],
            require_semantic_captions=True,
            allow_mixed_body=True,
        )
    fitted = planning.verify_plan(
        raw, transcript, data["asset_cards"], require_semantic_captions=True
    )
    assert raw == original
    assert fitted["captions"][0]["line_break_after_token_id"] == "t000002"
    assert fitted["materials"] == raw["materials"]
    assert fitted["opening"] == raw["opening"]
    assert fitted["features"] == raw["features"]
    assert fitted["conclusion"] == raw["conclusion"]
    before = [
        (c["first_token_id"], c["last_token_id"], c.get("emphasis", []))
        for c in raw["captions"]
    ]
    assert before == [
        (c["first_token_id"], c["last_token_id"], c.get("emphasis", []))
        for c in fitted["captions"]
    ]
    assert planning.fit_recorded_display_spans(fitted, transcript) is fitted
    rows = apple.semantic_caption_rows(
        apple.AppleSuitePlan.model_validate(fitted), transcript
    )
    resolved = {
        "captions": rows,
        "tokens": [t.model_dump(mode="json") for t in transcript.tokens],
    }
    native = planning.native_caption_text(resolved, fitted, transcript)
    assert native["captions"][0]["text"] == "droppingingto还在一张一张找参考，"
    assert native["captions"][0]["lines"][0]["text"] == "droppingingto"
    assert native["tokens"] == resolved["tokens"]
    for before_row, after_row in zip(rows, native["captions"], strict=True):
        assert before_row["time"] == after_row["time"]
        assert "".join(line["text"] for line in after_row["lines"]) == after_row["text"]
    assert planning.native_caption_text(native, fitted, transcript) is native
    rows = apple.semantic_caption_rows(
        apple.AppleSuitePlan.model_validate(fitted), transcript
    )
    assert "".join(row["text"].replace(" ", "") for row in rows) == "".join(
        token.text for token in transcript.tokens
    ).replace(" ", "")


@pytest.mark.parametrize(
    "bad", ["missing_word", "unknown_word", "unsafe_explicit_break", "cross_emphasis"]
)
def test_display_fit_preserves_strict_caption_checks(bad):
    data = json.loads(
        (Path(__file__).parent / "fixtures/bihuo_display_capacity.json").read_text(
            "utf-8"
        )
    )
    raw = data["plan"]
    if bad == "missing_word":
        raw["captions"][0]["first_token_id"] = "t000001"
    elif bad == "unknown_word":
        raw["captions"][0]["first_token_id"] = "missing"
    elif bad == "unsafe_explicit_break":
        raw["captions"][0]["line_break_after_token_id"] = "t000000"
    else:
        raw["captions"][0]["emphasis"] = [
            {"first_token_id": "t000000", "last_token_id": "t000011"}
        ]
    with pytest.raises(ValueError):
        planning.verify_plan(
            raw,
            Transcript.model_validate(data["transcript"]),
            data["asset_cards"],
            require_semantic_captions=True,
        )


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


def capsule_payload(raw, transcript):
    captions = apple.semantic_caption_rows(
        apple.AppleSuitePlan.model_validate(raw), transcript
    )
    return {
        "template_id": "bihuo-02-v1",
        "config": {
            "size": [1080, 1920],
            "fonts": registry.fonts("bihuo-02-v1"),
            "captions": captions,
        },
    }


def test_actual_b_caption_fits_at_comma_without_changing_spoken_content():
    raw, transcript = conclusion_case()
    original = copy.deepcopy(raw)
    before = capsule_payload(raw, transcript)
    untouched = copy.deepcopy(before)
    native = registry.runtime("bihuo-02-v1").capsule
    with pytest.raises(ValueError, match="Caption exceeds measured capacity"):
        native.caption(before["config"], 1)
    fitted = planning._fit_capsule_captions(before, transcript)
    first = fitted["config"]["captions"][0]
    assert [line["text"] for line in first["lines"]] == [
        "新品上架前，",
        "商品图先检查这三件事。",
    ]
    assert first["lines"][0]["emphasis_spans"] == [[0, 2]]
    assert first["lines"][1]["emphasis_spans"] == [[7, 10]]
    assert {k: v for k, v in first.items() if k != "lines"} == {
        k: v for k, v in before["config"]["captions"][0].items() if k != "lines"
    }
    assert fitted["config"]["captions"][1:] == before["config"]["captions"][1:]
    assert raw == original
    assert before == untouched
    assert planning._fit_capsule_captions(fitted, transcript) is fitted
    compiled = planning.compile_render_input(
        raw,
        transcript,
        {},
        "unchanged-source.mp4",
        {},
        recipe_compiler=lambda resolved, **_: {
            **before,
            "config": {**before["config"], "captions": resolved["captions"]},
        },
    )
    assert compiled == fitted


def test_actual_a_c_d_caption_layouts_are_unchanged():
    raw, transcript = case()
    saved = json.loads(
        (
            Path(__file__).parent / "fixtures/bihuo_material_caption_cases.json"
        ).read_text("utf8")
    )
    for captions in [raw["captions"], *[row["captions"] for row in saved]]:
        payload = capsule_payload({**raw, "captions": captions}, transcript)
        before = copy.deepcopy(payload)
        assert planning._fit_capsule_captions(payload, transcript) is payload
        assert payload == before


def test_legacy_caption_without_lines_keeps_native_fallback():
    raw, transcript = case()
    payload = capsule_payload(raw, transcript)
    cue = {"text": "商品图", "time": [0.09, 3.03]}
    payload["config"]["captions"] = [cue]
    original = copy.deepcopy(payload)
    assert planning._fit_capsule_captions(payload, transcript) is payload
    assert payload == original
    cue["text"] = "商品图" * 20
    with pytest.raises(ValueError, match="capacity without recorded token bounds"):
        planning._fit_capsule_captions(payload, transcript)


def test_caption_fit_is_only_for_selected_capsule_and_rejects_unsafe_layout():
    raw, transcript = conclusion_case()
    payload = capsule_payload(raw, transcript)
    other = {**payload, "template_id": "bihuo-01-v1"}
    assert planning._fit_capsule_captions(other, transcript) is other
    # One original ASR token cannot be split, even if its rendered text has
    # lexical boundaries. The entire long opening remains one recorded token.
    words = transcript.model_copy(deep=True)
    token = words.tokens[0].model_copy(
        update={"text": payload["config"]["captions"][0]["text"]}
    )
    words.tokens = [token]
    payload["config"]["captions"] = [payload["config"]["captions"][0]]
    payload["config"]["captions"][0]["last_token_id"] = token.id
    payload["config"]["captions"][0]["emphasis_token_spans"] = []
    with pytest.raises(ValueError, match="no safe two-line"):
        planning._fit_capsule_captions(payload, words)


@pytest.mark.parametrize("protected", ["emphasis", "number"])
def test_caption_fit_never_splits_emphasis_or_number(protected):
    raw, transcript = conclusion_case()
    payload = capsule_payload(raw, transcript)
    cue = payload["config"]["captions"][0]
    payload["config"]["captions"] = [cue]
    if protected == "emphasis":
        cue["emphasis_token_spans"] = [
            {k: cue[k] for k in ["first_token_id", "last_token_id"]}
        ]
    else:
        transcript = transcript.model_copy(deep=True)
        transcript.tokens = [
            token.model_copy(update={"text": "一"}) for token in transcript.tokens[:20]
        ]
        cue.update(
            text="一" * 20,
            last_token_id=transcript.tokens[-1].id,
            emphasis_token_spans=[],
            lines=[{"text": "一" * 20, "emphasis_spans": []}],
        )
    with pytest.raises(ValueError, match="no safe two-line"):
        planning._fit_capsule_captions(payload, transcript)
