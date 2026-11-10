"""Check project image availability for current automatic Motion templates."""

from typing import Any

from PIL import Image

from .video_editing_browser_clocks import CARD_GROUP, NUMBERED_GROUP
from .video_editing_browser_rotation import ROTATION_GROUP
from .video_editing_contracts import SemanticPlan
from .video_editing_judgment import JUDGMENT_GROUP, JUDGMENT_IMAGES
from .video_editing_line_branch import (
    LINE_DIRECTOR_PATH,
    LINE_GROUP,
    LINE_HAND_PATH,
    LINE_PREVIOUS_PATH,
    line_sheet_frames,
    line_sheet_shape,
)
from .video_editing_materials import project_image_digests
from .video_editing_native_content import PACKAGE_GROUP
from .video_editing_overlay_templates import (
    JUDGMENT_TEMPLATE_ID,
    LINE_TEMPLATE_ID,
    NUMBERED_TEMPLATE_ID,
    PACKAGE_TEMPLATE_ID,
    PICTURE_TEMPLATE_ID,
    ROTATION_TEMPLATE_ID,
)

_IMAGE_GROUPS = {
    PICTURE_TEMPLATE_ID: ((CARD_GROUP, 3),),
    ROTATION_TEMPLATE_ID: ((ROTATION_GROUP, 3),),
    JUDGMENT_TEMPLATE_ID: ((JUDGMENT_GROUP, 2),),
    PACKAGE_TEMPLATE_ID: ((PACKAGE_GROUP, 4),),
    LINE_TEMPLATE_ID: ((LINE_GROUP, 3), (PACKAGE_GROUP, 4)),
    NUMBERED_TEMPLATE_ID: ((NUMBERED_GROUP, 3),),
}


def has_transparent_pixels(path: str) -> bool:
    try:
        with Image.open(path) as image:
            if "A" not in image.getbands() and "transparency" not in image.info:
                return False
            low, high = image.convert("RGBA").getchannel("A").getextrema()
            return (
                isinstance(low, int)
                and isinstance(high, int)
                and low < 255
                and high > 0
            )
    except (OSError, ValueError):
        return False


def template_image_requirements(
    template: dict | None,
    cards: list[dict],
    material_files: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if template is None:
        return []
    specs = _IMAGE_GROUPS.get(template["id"], ())
    if not specs:
        return []
    images = project_image_digests(cards)
    files = {
        key: value for key, value in (material_files or {}).items() if key in images
    }
    result = []
    for group_id, count in specs:
        row: dict[str, Any] = {
            "group_id": group_id,
            "required_distinct_images": count,
            "selected_distinct_images": len(set(images.values())),
        }
        if group_id == JUDGMENT_GROUP:
            row["transparent_image_ids"] = [
                image_id
                for image_id, asset in sorted(files.items())
                if has_transparent_pixels(asset["path"])
            ]
        elif group_id == LINE_GROUP:
            row["native_image_slot_ids"] = line_image_slots(files)
        result.append(row)
    return result


def line_image_slots(files: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    slots: dict[str, list[str]] = {
        LINE_PREVIOUS_PATH: [],
        LINE_DIRECTOR_PATH: [],
        LINE_HAND_PATH: [],
    }
    for asset_id, asset in sorted(files.items()):
        try:
            with Image.open(asset["path"]) as image:
                if line_sheet_shape(image):
                    for _ in line_sheet_frames(image):
                        pass
                    slots[LINE_HAND_PATH].append(asset_id)
                    continue
                low, high = image.convert("RGBA").getchannel("A").getextrema()
                if low == 255:
                    slots[LINE_PREVIOUS_PATH].append(asset_id)
                elif isinstance(high, int) and high > 0:
                    slots[LINE_DIRECTOR_PATH].append(asset_id)
        except (OSError, ValueError):
            continue
    return slots


def runtime_payload(runtime: dict) -> dict[str, Any]:
    payload = {
        "version": runtime["version"],
        "unavailable_groups": runtime["unavailable_template_groups"],
    }
    if "project_image_requirements" in runtime:
        payload["project_image_requirements"] = runtime["project_image_requirements"]
    if "presenter_motion_windows" in runtime:
        payload["presenter_motion_windows"] = runtime["presenter_motion_windows"]
    if "azl_panel_windows" in runtime:
        payload["azl_panel_windows"] = runtime["azl_panel_windows"]
    if "chenxi_broll_windows" in runtime:
        payload["chenxi_broll_windows"] = runtime["chenxi_broll_windows"]
    return payload


def validate_template_images(
    plan: SemanticPlan, runtime: dict | None, cards: list[dict]
) -> None:
    requirements = {
        row["group_id"]: row
        for row in (runtime or {}).get("project_image_requirements", [])
    }
    if not requirements:
        return
    images = project_image_digests(cards)
    for beat in plan.beats:
        requirement = requirements.get(beat.group_id)
        if requirement is None:
            continue
        required = requirement["required_distinct_images"]
        if requirement["selected_distinct_images"] < required:
            raise ValueError("Selected template group lacks distinct project images")
        if beat.group_id == LINE_GROUP:
            media = {anchor.path: anchor.asset_id for anchor in beat.native_media}
            slots = requirement["native_image_slot_ids"]
            if any(
                media.get(path) not in candidates for path, candidates in slots.items()
            ):
                raise ValueError(
                    "Line scene needs its selected art, frame sheet and previous still"
                )
            continue
        bound = [
            images.get(item.asset_ids[0])
            for item in beat.relation_items
            if len(item.asset_ids) == 1
        ]
        if (
            len(beat.relation_items) != required
            or len(bound) != required
            or None in bound
            or len(set(bound)) != required
        ):
            raise ValueError("Each spoken card item needs its own project image")
        if "transparent_image_ids" in requirement:
            media = {anchor.path: anchor.asset_id for anchor in beat.native_media}
            if (
                media.get(JUDGMENT_IMAGES[0])
                not in requirement["transparent_image_ids"]
            ):
                raise ValueError("The upper judgment image needs real transparency")
