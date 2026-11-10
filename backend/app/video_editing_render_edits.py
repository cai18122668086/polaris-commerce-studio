"""Apply explicit per-render decisions against a frozen native candidate."""

import math
from typing import Any

from .video_editing_azl_panels import (
    AZL_DESIGN_ID,
    AZL_GROUPS,
    AZL_RECT,
    AZL_TEMPLATE_ID,
)
from .video_editing_browser_clocks import LIVE_BROWSER_SOURCE_FIELDS
from .video_editing_contracts import NativeRenderEdits, SemanticBeat
from .video_editing_hypit_strips import (
    LIVE_STAGE_GROUPS,
    PRICE_CARD_GROUP,
    PRICE_CARD_INSET_TYPE,
)
from .video_editing_question_branch import (
    QUESTION_BACKGROUND,
    QUESTION_BRANCH,
    QUESTION_GROUP,
)

SOURCE_GROUP = "Z-M00"
MUSIC_REDUCTION_DB = 6
HY_PORTRAIT_INSETS = frozenset(("HY-A5", PRICE_CARD_GROUP))
NATIVE_PORTRAIT_INSETS = HY_PORTRAIT_INSETS | {QUESTION_GROUP}
FULL_FRAME = [0, 0, 1, 1]


def _rect(value: Any) -> tuple[float, float, float, float] | None:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(type(n) not in {int, float} or not math.isfinite(n) for n in value)
    ):
        return None
    x, y, w, h = value
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1 or y + h > 1:
        return None
    return x, y, x + w, y + h


def boxes_intersect(first: tuple, second: tuple) -> bool:
    return max(first[0], second[0]) < min(first[2], second[2]) and max(
        first[1], second[1]
    ) < min(first[3], second[3])


def portrait_inset_allowed(group_id: str, entry: dict, regions: list[dict]) -> bool:
    placement = entry.get("placement", {})
    rect = _rect(placement.get("rect"))
    recipe = entry.get("recipe", {})
    config = recipe.get("config", {})
    if (
        group_id not in NATIVE_PORTRAIT_INSETS
        or placement.get("layer") != "overlay"
        or rect is None
        or not 0.43 <= rect[1] < rect[3] <= 0.86
        or recipe.get("group_id") != group_id
        or (
            group_id == PRICE_CARD_GROUP
            and recipe.get("price_card_layout") != PRICE_CARD_INSET_TYPE
        )
        or (
            group_id == QUESTION_GROUP
            and (
                config.get("branch") != QUESTION_BRANCH
                or config.get("content", {}).get("captions") != []
            )
        )
        or not any(r.get("id") == "centered-portrait" for r in regions)
    ):
        return False
    boxes = [_rect(r.get("rect")) for r in regions]
    return all(box is not None and not boxes_intersect(rect, box) for box in boxes)


def full_native_canvas_allowed(group_id: str, entry: dict) -> bool:
    placement = entry.get("placement", {})
    recipe = entry.get("recipe", {})
    if (
        placement.get("layer") != "overlay"
        or placement.get("rect") != FULL_FRAME
        or recipe.get("group_id") != group_id
    ):
        return False
    if group_id in LIVE_STAGE_GROUPS:
        return recipe.get("hypit_live_stage") is True
    config = recipe.get("config", {})
    return (
        group_id == QUESTION_GROUP
        and config.get("branch") == QUESTION_BRANCH
        and QUESTION_BACKGROUND in config.get("media", {})
        and config.get("content", {}).get("captions") == []
    )


def available_render_edits(
    semantic: dict, recipes: dict, choices: dict | None
) -> tuple[set[str], bool]:
    avoid_original = any(
        row["target_kind"] == "group"
        and row["target_id"] == SOURCE_GROUP
        and row["choice"] == "avoid"
        for row in (choices or {}).get("notes", [])
    )
    editable = {
        beat["id"]
        for beat in semantic["beats"]
        if beat["group_id"] != SOURCE_GROUP and beat["id"] in recipes["entries"]
    }
    return (set() if avoid_original else editable), bool(
        (recipes.get("sound") or {}).get("music")
    )


def validate_render_edits(
    edits: NativeRenderEdits, semantic: dict, recipes: dict, choices: dict | None
) -> None:
    editable, has_music = available_render_edits(semantic, recipes, choices)
    if not set(edits.source_only_beat_ids).issubset(editable) or (
        edits.music is not None and not has_music
    ):
        raise ValueError("Native edits must address this candidate's editable inputs")


def continuous_overlay_groups(
    semantic: dict,
    recipes: dict,
    transparent_groups: set[str],
    excluded: set[str] | None = None,
    *,
    allow_hypit_insets: bool = False,
    allow_question_insets: bool = False,
    scene_groups: set[str] | None = None,
) -> set[str]:
    """Admit typed picture changes while the original narration continues."""
    active = set()
    for beat in semantic["beats"]:
        gid = beat["group_id"]
        if gid == SOURCE_GROUP or (excluded and beat["id"] in excluded):
            continue
        entry = recipes["entries"].get(beat["id"], {})
        placement = entry.get("placement", {})
        recipe = entry.get("recipe", {})
        layer = placement.get("layer")
        azl_panel = (
            gid in AZL_GROUPS
            and recipes.get("overlay_template_id") == AZL_TEMPLATE_ID
            and recipe.get("design_id") == AZL_DESIGN_ID
            and layer == "scene"
            and placement.get("rect") == list(AZL_RECT)
        )
        native_canvas = (
            gid in (scene_groups or ())
            and (placement.get("rect") == FULL_FRAME or azl_panel)
            and recipe.get("group_id") == gid
            and (
                layer == "scene"
                or (
                    layer == "overlay"
                    and gid in LIVE_BROWSER_SOURCE_FIELDS
                    and recipe.get("browser_live_background") is True
                )
            )
        )
        transparent = gid in transparent_groups and (
            entry.get("placement", {}).get("layer") == "subtitle"
        )
        allow_native_overlay = (
            allow_hypit_insets and gid in HY_PORTRAIT_INSETS | LIVE_STAGE_GROUPS
        ) or (allow_question_insets and gid == QUESTION_GROUP)
        if not (transparent or native_canvas) and not (
            allow_native_overlay
            and (
                full_native_canvas_allowed(gid, entry)
                or portrait_inset_allowed(
                    gid, entry, recipes.get("protected_regions", [])
                )
            )
        ):
            return set()
        active.add(gid)
    return active


def source_only(beat: SemanticBeat) -> SemanticBeat:
    return beat.model_copy(
        update={
            "group_id": SOURCE_GROUP,
            "asset_ids": [],
            "native_text": [],
            "native_events": [],
            "native_media": [],
            "relation_items": [],
            "reason": "用户指定本次成片该段保留本期原景和主字幕。",
            "locked_by_user": True,
        }
    )


def edited_segment_receipt(beat: SemanticBeat, start: int, end: int) -> dict[str, Any]:
    return {
        "beat_id": beat.id,
        "original_group_id": beat.group_id,
        "applied_group_id": SOURCE_GROUP,
        "first_token_id": beat.first_token_id,
        "last_token_id": beat.last_token_id,
        "start_ms": start,
        "end_ms": end,
        "locked_by_user": True,
    }
