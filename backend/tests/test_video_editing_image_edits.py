"""Keep local picture swaps scoped to real native cards and original clocks."""

from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image

from app.video_editing_contracts import (
    NativeImageEdit,
    NativeRenderEdits,
    SemanticPlan,
    Transcript,
    TranscriptToken,
)
from app.video_editing_image_edits import apply_image_edits, image_edit_targets
from app.video_editing_judgment import JUDGMENT_IMAGES
from app.video_editing_materials import PREFIX


def material(n: int) -> str:
    return PREFIX + str(UUID(int=n))


def picture_plan(group_id: str, design_id: str, slots: list[list[str]]):
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=3000,
        provider="test_annotation",
        model="actual-word-fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=str(i), text=text, start_ms=i * 900, end_ms=(i + 1) * 900
            )
            for i, text in enumerate(("洗碗", "刷锅", "洗水果"))
        ],
    )
    items, texts = [], []
    media = [{"path": "/presenter", "asset_id": "source-test"}]
    for i, paths in enumerate(slots):
        aid = material(i + 1)
        label = f"/label/{i}"
        texts.append({"path": label, "first_token_id": str(i), "last_token_id": str(i)})
        items.append(
            {
                "id": f"item-{i}",
                "first_token_id": str(i),
                "last_token_id": str(i),
                "asset_ids": [aid],
                "native_text_paths": [label],
                "native_media_paths": paths,
            }
        )
        media.extend({"path": path, "asset_id": aid} for path in paths)
    beat = {
        "id": "cards",
        "first_token_id": "0",
        "last_token_id": "2",
        "group_id": group_id,
        "relation": "parallel",
        "reason": "三种实际用途",
        "native_text": texts,
        "native_media": media,
        "native_events": [{"path": "/events/third", "token_id": "2", "edge": "start"}],
        "relation_items": items,
        "asset_ids": [
            "source-test",
            "unused-context",
            *(material(i + 1) for i in range(len(slots))),
        ],
    }
    plan = SemanticPlan.model_validate(
        {
            "audience_question": "如何使用",
            "argument_outline": ["用途"],
            "style_reason": "原生图片",
            "beats": [
                beat,
                {
                    "id": "other",
                    "first_token_id": "0",
                    "last_token_id": "2",
                    "group_id": "BG-S06",
                    "reason": "其他段",
                    "relation": "explanation",
                },
            ],
        }
    )
    recipes = {
        "entries": {
            "cards": {
                "carrier": "picture",
                "recipe": {"design_id": design_id, "group_id": group_id},
            }
        }
    }
    assets = {
        material(i): {"kind": "image", "sha256": str(i) * 64} for i in range(1, 6)
    }
    return plan, recipes, assets, transcript


def change(path: str, n: int) -> NativeImageEdit:
    return NativeImageEdit(
        beat_id="cards", path=path, material_id=UUID(int=n), sha256=str(n) * 64
    )


def test_swap_image_replaces_both_original_branches_only():
    slots = [
        [f"/cards/{i}/{branch}/image" for branch in ("city", "food")] for i in range(3)
    ]
    plan, recipes, assets, transcript = picture_plan(
        "CX-G07", "tengli-picture-compare-v2", slots
    )
    targets = image_edit_targets(plan, recipes, assets, transcript)
    assert [(t.label, t.path) for t in targets] == list(
        zip(("洗碗", "刷锅", "洗水果"), (role[0] for role in slots), strict=True)
    )
    before = plan.model_dump_json()
    edited, receipts = apply_image_edits(
        [change(slots[2][0], 4)], plan, recipes, assets, transcript
    )
    assert plan.model_dump_json() == before
    old, new = plan.beats[0], edited.beats[0]
    assert new.native_media[:-2] == old.native_media[:-2]
    assert {m.asset_id for m in new.native_media[-2:]} == {material(4)}
    assert new.native_text == old.native_text and new.native_events == old.native_events
    assert new.relation_items[:2] == old.relation_items[:2]
    assert new.relation_items[2].asset_ids == [material(4)]
    assert set(new.asset_ids) == {
        "source-test",
        "unused-context",
        material(1),
        material(2),
        material(4),
    }
    assert edited.beats[1] == plan.beats[1]
    (receipt,) = receipts
    assert (
        receipt["original_sha256"] == "3" * 64 and receipt["applied_sha256"] == "4" * 64
    )
    assert receipt["native_media_paths"] == slots[2] and receipt["locked_by_user"]


def test_rotation_rejects_hidden_or_duplicate_slots_and_allows_two_image_swap():
    slots = [[f"/items/{i}/image"] for i in range(3)]
    plan, recipes, assets, transcript = picture_plan(
        "CX-G04", "tengli-rotation-cards-v1", slots
    )
    for edit in [
        change("/presenter", 4),
        change(slots[0][0], 1),
        change(slots[0][0], 2),
        change(slots[0][0], 4).model_copy(update={"sha256": "5" * 64}),
    ]:
        with pytest.raises(ValueError):
            apply_image_edits([edit], plan, recipes, assets, transcript)
    first, second = change(slots[0][0], 2), change(slots[1][0], 1)
    edited, _ = apply_image_edits([first, second], plan, recipes, assets, transcript)
    assert [item.asset_ids for item in edited.beats[0].relation_items] == [
        [material(2)],
        [material(1)],
        [material(3)],
    ]
    with pytest.raises(ValueError, match="active segment"):
        NativeRenderEdits(source_only_beat_ids=["cards"], image_edits=[first])
    with pytest.raises(ValueError, match="each image once"):
        NativeRenderEdits(image_edits=[first, first])
    assert NativeRenderEdits(image_edits=[second, first]).image_edits == [first, second]
    assert "image_edits" not in NativeRenderEdits(music="off").model_dump(mode="json")


def test_judgment_upper_slot_requires_nonempty_transparency(tmp_path: Path):
    plan, recipes, assets, transcript = picture_plan(
        "W-R14", "tengli-evidence-judgment-v1", [[path] for path in JUDGMENT_IMAGES]
    )
    targets = image_edit_targets(plan, recipes, assets, transcript)
    assert [t.requires_transparency for t in targets] == [True, False]
    path = tmp_path / "picture.png"
    img = Image.new("RGBA", (6, 6), (1, 2, 3, 255))
    img.save(path)
    assets[material(4)]["path"] = str(path)
    replacement = change(JUDGMENT_IMAGES[0], 4)
    with pytest.raises(ValueError, match="real transparency"):
        apply_image_edits([replacement], plan, recipes, assets, transcript)
    img.putpixel((0, 0), (0, 0, 0, 0))
    img.save(path)
    edited, _ = apply_image_edits([replacement], plan, recipes, assets, transcript)
    assert edited.beats[0].native_media[1].asset_id == material(4)
    assert edited.beats[0].native_media[2] == plan.beats[0].native_media[2]
