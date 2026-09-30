"""Shared wire contract for the Inspiration planner and its consumer."""

from typing import Any

CREATIVE_FIELDS = (
    "product_identity_lock",
    "hard_composition_skeleton",
    "normalized_anchors",
    "product_role_map",
    "typography_zones",
    "commercial_intent",
    "forbidden_transfer",
    "original_execution_prompt",
)
CREATIVE_PLANNER_PROMPT = (
    "Inspect the attached product pixels and plan exactly one original ecommerce "
    "creative image. Product references alone define identity; competitor references "
    "are composition guidance only. Return JSON with exactly these fields: "
    + ", ".join(CREATIVE_FIELDS)
    + ". Each field is a concise nonempty string; normalized_anchors describes "
    "labelled positions with x/y coordinates in 0..1. Preserve the user's brief "
    "verbatim in original_execution_prompt; include canvas, scale, text zones and "
    "negative constraints. Do not return detail-page analysis/plan/screens. "
    "Keep the combined UTF-8 content below 16000 bytes, without dropping identity "
    "or user constraints. Do not copy reference branding or unsupported claims."
)


def creative_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "creative_image_plan",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": list(CREATIVE_FIELDS),
                "properties": {
                    name: {"type": "string", "minLength": 1} for name in CREATIVE_FIELDS
                },
            },
        },
    }
