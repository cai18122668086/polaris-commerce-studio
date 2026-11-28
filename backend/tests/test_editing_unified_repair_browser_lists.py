"""Browser list scenes compile through their own entries, not _unified_entry."""

from pathlib import Path

from app import video_editing_overlay_recipes as recipes
from app.video_editing_contracts import SemanticPlan, Transcript
from app.video_editing_unified_repair import repair_unified_beats
from app.video_editing_unified_scenes import BROWSER_LIST_SCENES, UNIFIED_SCENE_GROUPS


def _transcript() -> Transcript:
    # The skipped path never reads words.
    return Transcript.model_construct(tokens=[])


def _plan(group: str) -> tuple[dict, SemanticPlan]:
    raw = {
        "schema_version": "tengli.semantic-plan/1",
        "audience_question": "三项怎么查？",
        "argument_outline": ["三项检查"],
        "style_reason": "测试",
        "beats": [
            {
                "id": "b0",
                "first_token_id": "t000000",
                "last_token_id": "t000011",
                "emphasis_token_ids": [],
                "relation": "parallel",
                "group_id": group,
                "reason": "测试",
                "asset_ids": [],
                "native_text": [],
                "native_events": [],
                "native_media": [],
                "relation_items": [],
            }
        ],
    }
    return raw, SemanticPlan.model_validate(raw)


def test_split_scenes_are_part_of_the_unified_catalog():
    assert {"CX-G01", "CX-G02"} <= BROWSER_LIST_SCENES <= UNIFIED_SCENE_GROUPS


def test_signature_split_is_left_to_its_own_compiler_entry(monkeypatch):
    calls = []

    def unified_entry(*args, **kwargs):
        calls.append(args)
        raise AssertionError("unified entry used for a browser list scene")

    monkeypatch.setattr(recipes, "_unified_entry", unified_entry)
    for group in sorted(BROWSER_LIST_SCENES):
        raw, plan = _plan(group)
        changed, repairs = repair_unified_beats(
            raw, plan, Path("/unused"), _transcript(), [], signature_group_ids={group}
        )
        assert changed == raw and repairs == []
    assert calls == []
