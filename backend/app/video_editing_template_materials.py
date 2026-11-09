"""Check project image availability for current automatic Motion templates."""

from typing import Any

from .video_editing_browser_clocks import CARD_GROUP
from .video_editing_browser_rotation import ROTATION_GROUP
from .video_editing_contracts import SemanticPlan
from .video_editing_materials import project_image_digests
from .video_editing_overlay_templates import PICTURE_TEMPLATE_ID, ROTATION_TEMPLATE_ID

_IMAGE_GROUPS = {PICTURE_TEMPLATE_ID: CARD_GROUP, ROTATION_TEMPLATE_ID: ROTATION_GROUP}
_IMAGE_COUNT = 3


def template_image_requirements(
    template: dict | None, cards: list[dict]
) -> list[dict[str, Any]]:
    group_id = _IMAGE_GROUPS.get(template["id"]) if template else None
    if not group_id:
        return []
    return [
        {
            "group_id": group_id,
            "required_distinct_images": _IMAGE_COUNT,
            "selected_distinct_images": len(set(project_image_digests(cards).values())),
        }
    ]


def runtime_payload(runtime: dict) -> dict[str, Any]:
    payload = {
        "version": runtime["version"],
        "unavailable_groups": runtime["unavailable_template_groups"],
    }
    if "project_image_requirements" in runtime:
        payload["project_image_requirements"] = runtime["project_image_requirements"]
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
