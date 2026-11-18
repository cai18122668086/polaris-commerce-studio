"""Transport declaration for the existing cross-border planning validator."""
from typing import Any


def response_format(page_count: int) -> dict[str, Any]:
    text = {"type": "string", "minLength": 1}

    def authored_object(fields: tuple[str, ...]) -> dict[str, Any]:
        return {"type": "object", "required": list(fields),
                "properties": {key: dict(text) for key in fields}}

    screen = authored_object((
        "role", "title", "label", "composition", "device", "difference",
        "structure", "subject_scale", "buyer_question", "layout_family",
        "camera_angle", "product_position", "background_system", "prop_strategy",
        "copy_density",
    ))
    screen["properties"]["subject_scale"]["enum"] = [
        "hero", "medium", "scene", "macro", "cutaway", "information", "overhead",
    ]
    analysis = authored_object(("category_key", "category_reason"))
    for key in ("product_image_analysis", "product_consistency_anchors",
                "product_master_description", "buyer_objections"):
        analysis["required"].append(key)
        analysis["properties"][key] = (
            {"type": "array", "minItems": 1, "items": {}}
            if key == "buyer_objections" else {"type": "object"}
        )
    design = authored_object(("category_visual_motif", "composition_contrast",
                              "color_contrast", "template_ban"))
    for key, minimum in (("signature_devices", min(2, page_count)),
                         ("rhythm_map", page_count)):
        design["required"].append(key)
        design["properties"][key] = {
            "type": "array", "minItems": minimum, "items": dict(text),
        }
    design["properties"]["rhythm_map"]["maxItems"] = page_count
    properties = {
        "campaign_style_lock": authored_object((
            "palette", "typography", "background", "lighting", "icon_style",
            "whitespace", "product_scale",
        )),
        "design_strength_lock": design,
        "product_consistency_lock": {"type": "object", "minProperties": 1},
        "layout_diversity_lock": {
            "type": "object", "required": ["max_same_layout_family"],
            "properties": {"max_same_layout_family": {
                "type": "integer", "minimum": 1, "maximum": 3,
            }},
        },
        "screens": {"type": "array", "minItems": page_count,
                    "maxItems": page_count, "items": screen},
    }
    analysis["properties"]["product_master_description"]["minProperties"] = 1
    return {"type": "json_schema", "json_schema": {
        "name": "crossborder_detail_plan", "strict": False,
        "schema": {"type": "object", "required": ["analysis", "plan"],
                   "properties": {"analysis": analysis, "plan": {
                       "type": "object", "required": list(properties),
                       "properties": properties,
                   }}},
    }}
