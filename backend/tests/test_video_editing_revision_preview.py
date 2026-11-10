from copy import deepcopy
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.video_editing_contracts import NativeRenderEdits
from app.video_editing_revision_preview import remap_edits
from app.video_editing_task_models import EditingNativePlanRecord


def plans():
    beats = [
        {
            "id": "before",
            "first_token_id": "t0",
            "last_token_id": "t2",
            "group_id": "AH-S05",
        },
        {
            "id": "text",
            "first_token_id": "t3",
            "last_token_id": "t7",
            "group_id": "BG-S04",
        },
        {
            "id": "image",
            "first_token_id": "t8",
            "last_token_id": "t9",
            "group_id": "HY-A2",
        },
    ]
    previous = EditingNativePlanRecord(
        semantic={"beats": beats},
        recipes={
            "entries": {"text": {"native": "words"}, "image": {"native": "images"}},
            "sound": {"music": [{"asset_id": "original"}]},
        },
    )
    candidate = EditingNativePlanRecord(
        semantic={
            "beats": [
                {**beat, "id": "new-" + beat["id"], "reason": "new"} for beat in beats
            ]
        },
        recipes={
            "entries": {
                "new-text": {"native": "words"},
                "new-image": {"native": "images"},
            },
            "sound": {"music": [{"asset_id": "original"}]},
        },
    )
    return previous, candidate


def choices():
    return NativeRenderEdits.model_validate(
        {
            "music": "lower",
            "source_only_beat_ids": ["before"],
            "highlight_edits": [
                {
                    "beat_id": "text",
                    "path": "/label",
                    "first_token_id": "t4",
                    "last_token_id": "t5",
                }
            ],
            "effect_edits": [{"beat_id": "text", "group_id": "BG-S05"}],
            "image_edits": [
                {
                    "beat_id": "image",
                    "path": "/image",
                    "material_id": str(uuid4()),
                    "sha256": "a" * 64,
                }
            ],
        }
    )


def test_replan_keeps_manual_edits_by_measured_occurrence_and_not_by_beat_id():
    old, next_plan = plans()
    edits = choices()
    saved = edits.model_dump(mode="json")
    next_plan.semantic["beats"][0]["group_id"] = "SG-S06"
    mapped, protected = remap_edits(edits, old, next_plan)
    assert protected == ["new-before", "new-image", "new-text"]
    assert mapped.source_only_beat_ids == ["new-before"]
    assert mapped.music == edits.music
    for field in ("highlight_edits", "effect_edits", "image_edits"):
        orig = getattr(edits, field)[0]
        changed = getattr(mapped, field)[0]
        assert changed.model_dump() == {
            **orig.model_dump(),
            "beat_id": "new-" + orig.beat_id,
        }
    assert edits.model_dump(mode="json") == saved


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("segment", "EDITING_REPLAN_SEGMENT_CHANGED"),
        ("slot", "EDITING_REPLAN_SLOT_CHANGED"),
        ("music", "EDITING_REPLAN_MUSIC_CHANGED"),
    ],
)
def test_conflicting_replan_never_drops_a_manual_edit(change, code):
    old, next_plan = plans()
    if change == "segment":
        next_plan.semantic["beats"][0]["last_token_id"] = "t1"
    elif change == "slot":
        next_plan.recipes["entries"]["new-image"] = {"native": "different"}
    else:
        next_plan.recipes["sound"]["music"][0]["asset_id"] = "different"
    before = deepcopy(old.semantic)
    with pytest.raises(ApiError) as error:
        remap_edits(choices(), old, next_plan)
    assert error.value.code == code and old.semantic == before
