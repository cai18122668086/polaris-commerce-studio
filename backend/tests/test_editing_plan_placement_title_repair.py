"""Saved real responses: one misplaced material / mid-word opening title.

bihuo-03 and apple-minimal (2026-11-25 e2e) anchored the first image inside
the opening, which rejected the whole paid plan. Most templates showed the
opening title cut inside a word (「这款白色头」).
"""

import copy
import json
from pathlib import Path

import pytest

from app import video_editing_apple_contracts as contracts
from app.bihuo_suite import planning
from app.video_editing_contracts import Transcript
from app.video_planner_policy import normalize_suite_output


def load(name):
    data = json.loads((Path(__file__).parent / "fixtures" / name).read_text("utf-8"))
    return data["plan"], Transcript.model_validate(data["transcript"]), data["cards"]


def text(transcript, span):
    ids = [t.id for t in transcript.tokens]
    a, b = ids.index(span["first_token_id"]), ids.index(span["last_token_id"])
    return "".join(t.text for t in transcript.tokens[a : b + 1])


def test_bihuo03_saved_plan_fails_strictly_without_repair():
    raw, transcript, cards = load("bihuo03_material_in_opening.json")
    with pytest.raises(ValueError, match="after opening and before quote"):
        planning.verify_plan(raw, transcript, cards, require_semantic_captions=True)


def test_bihuo03_material_moved_out_of_opening_and_after_quote_dropped():
    raw, transcript, cards = load("bihuo03_material_in_opening.json")
    original = copy.deepcopy(raw)
    changed, repairs = normalize_suite_output(raw, transcript)
    assert raw == original
    kinds = [(r["kind"], r["asset_id"]) for r in repairs if "asset_id" in r]
    assert kinds == [
        ("material_placement_moved", "material-ebaaf505-2ebd-4bba-a8f3-23b7288c6b5d"),
        ("material_placement_dropped", "material-40a41eec-cd17-4afc-bbe6-0fa7a8f509a9"),
    ]
    # Moved to the opening's last word, still inside its matched phrase.
    assert (
        changed["materials"][0]["show_at_token_id"]
        == (original["opening"]["intro_last_token_id"])
    )
    assert changed["materials"][1] == original["materials"][1]
    verified = planning.verify_plan(
        changed, transcript, cards, require_semantic_captions=True
    )
    assert len(verified["materials"]) == 2


def test_apple_saved_plan_keeps_materials_and_omits_early_features():
    raw, transcript, cards = load("apple_material_in_opening.json")
    with pytest.raises(ValueError, match="after opening and before quote"):
        contracts.verify_plan(raw, transcript, cards, require_semantic_captions=True)
    changed, repairs = normalize_suite_output(
        raw, transcript, features_follow_materials=True
    )
    assert [r["kind"] for r in repairs if r["kind"].endswith(("moved", "omitted"))] == [
        "material_placement_moved",
        "optional_feature_omitted",
        "optional_feature_omitted",
    ]
    verified = contracts.verify_plan(
        changed, transcript, cards, require_semantic_captions=True
    )
    assert len(verified["materials"]) == 3 and verified["features"] == []


def test_no_valid_material_left_keeps_strict_failure():
    raw, transcript, cards = load("bihuo03_material_in_opening.json")
    raw["materials"] = [raw["materials"][2]]  # Only the one after the quote.
    changed, repairs = normalize_suite_output(raw, transcript)
    assert changed["materials"] == raw["materials"]
    assert not [r for r in repairs if r.get("kind", "").startswith("material_")]


def test_mid_word_title_completes_the_clause_and_subtitle_follows():
    raw, transcript, cards = load("bihuo08_title_mid_word.json")
    assert text(transcript, raw["opening"]["title"]) == "这款白色头"
    changed, repairs = normalize_suite_output(raw, transcript)
    assert text(transcript, changed["opening"]["title"]) == "这款白色头戴耳机，"
    assert (
        text(transcript, changed["opening"]["subtitle"]) == "我在办公桌上用了一个月。"
    )
    assert any(r["kind"] == "opening_title_word_boundary" for r in repairs)
    planning.verify_plan(changed, transcript, cards, require_semantic_captions=True)


def test_mid_word_title_without_room_ends_at_previous_word():
    raw, transcript, cards = load("azl_title_mid_word.json")
    changed, _ = normalize_suite_output(raw, transcript)
    assert text(transcript, changed["opening"]["title"]) == "这款白色"
    assert text(transcript, changed["opening"]["subtitle"]) == "头戴耳机，"
    contracts.verify_plan(
        changed,
        transcript,
        cards,
        require_semantic_captions=True,
        allow_mixed_body=True,
    )


def test_whole_word_title_is_untouched():
    raw, transcript, _ = load("bihuo08_title_mid_word.json")
    ids = [t.id for t in transcript.tokens]
    raw["opening"]["title"]["last_token_id"] = ids[7]
    raw["opening"]["subtitle"] = {"first_token_id": ids[8], "last_token_id": ids[18]}
    changed, repairs = normalize_suite_output(raw, transcript)
    assert changed["opening"] == raw["opening"]
    assert not [r for r in repairs if r["kind"] == "opening_title_word_boundary"]
