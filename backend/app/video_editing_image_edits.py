"""Replace only explicitly exposed project image slots in a native render."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from .config import Settings
from .video_editing_browser_clocks import (
    CARD_GROUP,
    NUMBERED_GROUP,
    NUMBERED_IMAGES,
    NUMBERED_LABELS,
)
from .video_editing_browser_rotation import (
    CIRCULAR_MEDIA_GROUP,
    ROTATION_GROUP,
    ROTATION_IMAGES,
    STRIP_CARD_DESIGN,
    STRIP_CARD_GROUP,
    THREE_ITEM_SCENE_DESIGN,
)
from .video_editing_contracts import (
    EditingImageTarget,
    NativeImageEdit,
    SemanticPlan,
    Transcript,
)
from .video_editing_judgment import JUDGMENT_GROUP, JUDGMENT_IMAGES
from .video_editing_materials import PREFIX, material_changed, project_material_files
from .video_editing_task_models import EditingSourceRecord
from .video_editing_template_materials import has_transparent_pixels
from .video_editing_word_bindings import emphasis_text

_PROFILES = {
    CARD_GROUP: (
        "tengli-picture-compare-v2",
        tuple((f"/cards/{i}/city/image", f"/cards/{i}/food/image") for i in range(3)),
    ),
    ROTATION_GROUP: (
        "tengli-rotation-cards-v1",
        tuple((path,) for path in ROTATION_IMAGES),
    ),
    STRIP_CARD_GROUP: (
        STRIP_CARD_DESIGN,
        tuple((path,) for path in ROTATION_IMAGES),
    ),
    CIRCULAR_MEDIA_GROUP: (
        THREE_ITEM_SCENE_DESIGN,
        tuple((path,) for path in ROTATION_IMAGES),
    ),
    NUMBERED_GROUP: (
        "tengli-numbered-pictures-v1",
        tuple((path,) for path in NUMBERED_IMAGES),
    ),
    JUDGMENT_GROUP: (
        "tengli-evidence-judgment-v1",
        tuple((path,) for path in JUDGMENT_IMAGES),
    ),
}
_TRANSPARENT_PATH = JUDGMENT_IMAGES[0]


def editable_image_roles(beat: dict, recipes: dict) -> tuple[tuple[str, ...], ...]:
    profile = _PROFILES.get(beat["group_id"])
    entry = recipes["entries"].get(beat["id"], {})
    recipe = entry.get("recipe", {})
    if (
        profile is None
        or recipe.get("design_id") != profile[0]
        or recipe.get("group_id") != beat["group_id"]
        or entry.get("carrier") != "picture"
    ):
        return ()
    return profile[1]


def image_edit_targets(
    plan: SemanticPlan, recipes: dict, assets: dict, transcript: Transcript
) -> list[EditingImageTarget]:
    positions = {word.id: i for i, word in enumerate(transcript.tokens)}
    targets = []
    for beat in plan.beats:
        media = {anchor.path: anchor.asset_id for anchor in beat.native_media}
        text = {anchor.path: anchor for anchor in beat.native_text}
        for paths in editable_image_roles(beat.model_dump(mode="json"), recipes):
            key = paths[0]
            aid = media.get(key, "")
            item = next(
                (
                    item
                    for item in beat.relation_items
                    if set(item.native_media_paths) == set(paths)
                ),
                None,
            )
            if (
                not aid.startswith(PREFIX)
                or assets.get(aid, {}).get("kind") != "image"
                or item is None
                or item.asset_ids != [aid]
                or any(media.get(path) != aid for path in paths)
            ):
                continue
            # Both original three-card branches carry the same visible label.
            if not item.native_text_paths:
                continue
            label_path = (
                NUMBERED_LABELS[NUMBERED_IMAGES.index(key)]
                if beat.group_id == NUMBERED_GROUP
                else item.native_text_paths[0]
            )
            label_anchor = text.get(label_path)
            if (
                label_anchor is None
                or label_anchor.first_token_id not in positions
                or label_anchor.last_token_id not in positions
            ):
                continue
            first, last = (
                positions[label_anchor.first_token_id],
                positions[label_anchor.last_token_id],
            )
            label = emphasis_text(
                "".join(word.text for word in transcript.tokens[first : last + 1]),
                label_anchor.punctuation,
            )
            targets.append(
                EditingImageTarget(
                    beat_id=beat.id,
                    path=key,
                    label=label,
                    current_material_id=UUID(aid.removeprefix(PREFIX)),
                    requires_transparency=key == _TRANSPARENT_PATH,
                )
            )
    return targets


def resolve_image_edits(
    session: Session,
    settings: Settings,
    source: EditingSourceRecord,
    edits: list[NativeImageEdit],
    frozen: dict,
) -> dict:
    replacements = project_material_files(
        session,
        settings,
        source,
        {PREFIX + str(edit.material_id) for edit in edits},
        verify_bytes=True,
    )
    if any(
        aid in frozen and frozen[aid] != asset for aid, asset in replacements.items()
    ):
        raise material_changed()
    return {**frozen, **replacements}


def apply_image_edits(
    edits: list[NativeImageEdit],
    plan: SemanticPlan,
    recipes: dict,
    assets: dict,
    transcript: Transcript,
) -> tuple[SemanticPlan, list[dict[str, Any]]]:
    if not edits:
        return plan, []
    targets = {
        (target.beat_id, target.path): target
        for target in image_edit_targets(plan, recipes, assets, transcript)
    }
    mapped: dict[str, dict[str, str]] = {}
    receipts = []
    beats_by_id = {beat.id: beat for beat in plan.beats}
    for edit in edits:
        target = targets.get((edit.beat_id, edit.path))
        new_id = PREFIX + str(edit.material_id)
        new = assets.get(new_id, {})
        if (
            target is None
            or new.get("kind") != "image"
            or new.get("sha256") != edit.sha256
        ):
            raise ValueError("Replacement must match the scoped image and native slot")
        old_id = PREFIX + str(target.current_material_id)
        old = assets[old_id]
        if old["sha256"] == edit.sha256:
            raise ValueError(
                "Replacement image bytes must differ from the current image"
            )
        if target.requires_transparency and not has_transparent_pixels(new["path"]):
            raise ValueError(
                "The original upper judgment image requires real transparency"
            )
        beat = beats_by_id[edit.beat_id]
        paths = next(
            role
            for role in editable_image_roles(beat.model_dump(mode="json"), recipes)
            if role[0] == edit.path
        )
        mapped.setdefault(edit.beat_id, {}).update(dict.fromkeys(paths, new_id))
        receipts.append(
            {
                "beat_id": edit.beat_id,
                "group_id": beat.group_id,
                "label": target.label,
                "native_media_paths": list(paths),
                "original_asset_id": old_id,
                "original_sha256": old["sha256"],
                "applied_asset_id": new_id,
                "applied_sha256": edit.sha256,
                "locked_by_user": True,
            }
        )

    beats = []
    for beat in plan.beats:
        by_path = mapped.get(beat.id)
        if not by_path:
            beats.append(beat)
            continue
        media = [
            anchor.model_copy(update={"asset_id": by_path[anchor.path]})
            if anchor.path in by_path
            else anchor
            for anchor in beat.native_media
        ]
        ids = {anchor.path: anchor.asset_id for anchor in media}
        roles = editable_image_roles(beat.model_dump(mode="json"), recipes)
        if len({assets[ids[paths[0]]]["sha256"] for paths in roles}) != len(roles):
            raise ValueError("The native card items require distinct image bytes")
        items = []
        for item in beat.relation_items:
            replacement_id = next(
                (by_path[path] for path in item.native_media_paths if path in by_path),
                None,
            )
            items.append(
                item.model_copy(update={"asset_ids": [replacement_id]})
                if replacement_id
                else item
            )
        original_media_ids = {anchor.asset_id for anchor in beat.native_media}
        other_asset_ids = [
            aid for aid in beat.asset_ids if aid not in original_media_ids
        ]
        beats.append(
            beat.model_copy(
                update={
                    "asset_ids": list(dict.fromkeys([*ids.values(), *other_asset_ids])),
                    "native_media": media,
                    "relation_items": items,
                }
            )
        )
    return plan.model_copy(update={"beats": beats}), receipts
