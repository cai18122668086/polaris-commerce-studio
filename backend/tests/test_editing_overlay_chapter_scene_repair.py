"""unified-chapter and knowledge-talk failures from the e2e run (2026-11-25)."""

import json
from pathlib import Path

import pytest

from app import video_editing_overlay_recipes as recipes
from app.errors import ApiError
from app.video_editing_contracts import SemanticPlan
from app.video_editing_overlay_templates import (
    overlay_template,
    validate_template_plan,
)
from app.video_editing_unified_repair import repair_unified_beats
from app.video_planner_policy import normalize_chapter_starts


def fixture(name):
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text("utf-8"))["plan"]


def semantic(raw):
    return SemanticPlan.model_validate(
        {k: v for k, v in raw.items() if k != "tutorial_steps"}
    )


def test_unified_chapter_saved_plan_fails_without_repair():
    raw = fixture("unified_chapter_short_starts.json")
    assert len(raw["chapter_start_token_ids"]) == 1
    assert len(raw["argument_outline"]) == len(raw["beats"]) == 5
    with pytest.raises(ValueError, match="Chapters must map in order"):
        validate_template_plan(
            semantic(raw), overlay_template("unified-chapter-v1"), complete=False
        )


def test_unified_chapter_starts_completed_from_one_beat_per_outline_item():
    raw = fixture("unified_chapter_short_starts.json")
    template = overlay_template("unified-chapter-v1")
    changed, repairs = normalize_chapter_starts(raw, template)
    assert changed["chapter_start_token_ids"] == [
        beat["first_token_id"] for beat in raw["beats"]
    ]
    assert repairs[0]["kind"] == "chapter_starts_completed"
    assert raw["chapter_start_token_ids"] != changed["chapter_start_token_ids"]
    validate_template_plan(semantic(changed), template, complete=False)


def test_chapter_repair_leaves_ambiguous_or_other_templates_alone():
    raw = fixture("unified_chapter_short_starts.json")
    assert normalize_chapter_starts(raw, overlay_template("knowledge-talk-v1")) == (
        raw,
        [],
    )
    extra = {**raw, "argument_outline": raw["argument_outline"][:4]}
    assert (
        normalize_chapter_starts(extra, overlay_template("unified-chapter-v1"))[1] == []
    )


REQUIRED_TEXT = {"Z-M03": 3, "Z-M14": 3}


def fake_entry(package, group, beat, transcript, asset_cards, **_):
    bound = {a.asset_id for a in beat.native_media}
    texts = [t for t in beat.native_text if "/labels/" in t.path or "/words/" in t.path]
    if set(beat.asset_ids) != bound or len(texts) < REQUIRED_TEXT.get(beat.group_id, 0):
        raise ApiError(422, "EDITING_TEMPLATE_UNIFIED_INPUTS_REQUIRED", "x")
    return None, {}


@pytest.fixture
def knowledge(monkeypatch, tmp_path):
    monkeypatch.setattr(recipes, "_unified_entry", fake_entry)
    (tmp_path / "catalog").mkdir()
    groups = [{"id": g} for g in ("Z-M01", "Z-M02", "Z-M03", "Z-M14")]
    (tmp_path / "catalog/groups.json").write_text(json.dumps({"groups": groups}))
    return fixture("knowledge_talk_unbound_scene_assets.json"), tmp_path


def test_knowledge_talk_unbound_images_released_and_partial_scene_plain(knowledge):
    raw, package = knowledge
    plan = semantic(raw)
    changed, repairs = repair_unified_beats(raw, plan, package, None, [])
    kinds = {(r["kind"], r["group_id"]) for r in repairs}
    assert kinds == {
        ("unbound_scene_assets_released", "Z-M01"),
        ("incomplete_scene_to_plain_presenter", "Z-M03"),
        ("incomplete_scene_to_plain_presenter", "Z-M14"),
    }
    by_id = {beat["id"]: beat for beat in changed["beats"]}
    assert by_id["beat-04"]["asset_ids"] == [
        a for a in raw["beats"][3]["asset_ids"] if a.startswith("source-")
    ]
    plain = by_id["beat-02"]
    assert plain["group_id"] == "Z-M00" and plain["relation_items"] == []
    assert (
        plain["native_text"][0]["first_token_id"] == raw["beats"][1]["first_token_id"]
    )
    semantic(changed)  # Still a valid plan.


def test_knowledge_talk_incomplete_signature_fails_at_planning(knowledge):
    raw, package = knowledge
    with pytest.raises(ApiError) as caught:
        repair_unified_beats(raw, semantic(raw), package, None, [], {"Z-M03", "Z-M13"})
    assert caught.value.code == "EDITING_TEMPLATE_UNIFIED_INPUTS_REQUIRED"
