"""Native field inventory for every original group, without executable model data.

This describes concrete original input paths, not universal capacity claims.
Schema admission, rendering, meaning and visual acceptance remain separate.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .motion_library import MOTION_SHA256, read_json, sha256
from .video_editing_browser_clocks import CARD_GROUP, CARD_LANDMARKS
from .video_editing_hypit import (
    PICTURE_FPS,
    PICTURE_GROUP,
    PICTURE_PROFILE,
    picture_fields,
)
from .video_editing_hypit_strips import (
    FLOW_GROUP,
    STAGGER_GROUPS,
    stagger_profile,
    strip_fields,
)
from .video_editing_media_clocks import clock_profile
from .video_editing_native_content import (
    PACKAGE_GROUP,
    ROLE_CHAIN_GROUP,
    live_package_template,
    role_scene_contract,
)
from .video_editing_question_branch import (
    QUESTION_BACKGROUND,
    QUESTION_BRANCH,
    QUESTION_FONT,
    QUESTION_GROUP,
    question_variant_template,
)

SILHOUETTE_GROUPS = frozenset(("W-R04", "W-R09"))
SILHOUETTE_PATHS = tuple(f"/media/silhouettes/{i}/path" for i in range(7))
JUDGMENT_GROUP = "W-R14"
JUDGMENT_BRUSH_FONT = "font-06b2048c592b1dae"

TEXT_NAMES = {
    "text",
    "label",
    "title",
    "subtitle",
    "caption",
    "spoken",
    "english",
    "intro",
}
STYLE_NAMES = {
    "color",
    "fill",
    "kind",
    "role",
    "font",
    "path",
    "align",
    "mode",
    "fit",
    "theme",
}

# These branches evaluate geometry at local frame minus events.shift_frames.
SHIFTED_GEOMETRY_EVENTS = {
    "YYP01": {"start_frame", "end_frame"},
    "YYP02": {"start_frame", "end_frame"},
    "YYP06": {
        "camera_start_frame",
        "camera_end_frame",
        "reveal_start_frame",
        "reveal_end_frame",
    },
    "LYO02": {"mask_start_frame", "mask_end_frame"},
}


def clock_category(backend: str, names: list[str]) -> str | None:
    """Distinguish native offsets/rates/lengths from absolute event positions.

    In the original browser engine progress=(time-item.at)/item.enter;
    scene shift_frames is subtracted from the current frame. Neither is an
    absolute audio anchor. The original stagger/cell knobs are also lengths.
    """
    key = names[-1]
    if key == "shift_frames":
        return "native_clock_offset"
    if key == "hand_speeds":
        return "native_rate"
    if (backend == "browser" and key == "enter") or re.search(
        r"(?:^|_)(duration|interval|stagger|spread|step)(?:_|$)", key
    ):
        return "native_clock_length"
    return None


def pointer(parts: list[str | int]) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def input_contract(
    package: Path,
    group: dict[str, Any],
    *,
    branch: str | None = None,
    embedded_question_caption: bool = True,
    live_question_background: bool = False,
    live_package_presenter: bool = True,
) -> dict[str, Any]:
    template = read_json(package / group["input_template"])
    question_group = group["id"] == QUESTION_GROUP
    if question_group and branch not in (None, QUESTION_BRANCH, "smoke"):
        raise ValueError("Select an original W-R18 branch")
    if question_group and branch == QUESTION_BRANCH:
        template = question_variant_template(
            template,
            embedded_caption=embedded_question_caption,
            live_background=live_question_background,
        )
    if group["id"] == PACKAGE_GROUP and live_package_presenter:
        template = live_package_template(template)
    schema = read_json(package / group["input_schema"])
    Draft202012Validator.check_schema(schema)
    external = {
        r["id"]: r
        for r in read_json(package / "catalog/external-resources.json")["resources"]
    }
    fields = []
    backend = group["backend"]
    fps = template.get(
        "fps", template.get("frame_format", template.get("format", {})).get("fps", 30)
    )

    def describe(parts: list[str | int], value: Any) -> None:
        if not parts:
            return
        names = [p for p in parts if isinstance(p, str)]
        key = names[-1]
        first = names[0]
        category, unit = "native_parameter", None
        resource_kind = None
        if first == "output":
            category = "output_owned_by_compiler"
        elif isinstance(value, str) and value.startswith("input://"):
            record = external.get(value[8:], {})
            category, resource_kind = "resource", record.get("kind", "unresolved")
            if resource_kind in {"font", "model"}:
                category = "native_dependency"
        elif isinstance(value, str) and value.startswith("pkg://"):
            category = "font" if "/fonts/" in value else "resource"
            if category == "resource":
                resource_kind = "media"
        elif isinstance(value, str) and (
            (
                group["id"] in {"CX-G04", "CX-G05", "CX-G06"}
                and names == ["items", "image"]
            )
            or (group["id"] == "CX-G08" and parts == ["presenter"])
        ):
            category, resource_kind = "resource", "media"
        elif isinstance(value, str) and (
            (group["id"] == "Z-M07" and names == ["content", "photos"])
            or (group["id"] == "Z-M08" and names == ["content", "items", "image"])
        ):
            category = "native_media_key"
        elif (
            group["id"] == "YY6O01"
            and parts == ["content", "question"]
            and value == "?"
        ):
            category = "original_design_glyph"
        elif isinstance(value, str) and (
            (first == "content" and key not in STYLE_NAMES)
            or (group["id"] == "LYO02" and parts == ["content", "theme"])
            or (backend == "browser" and key in TEXT_NAMES)
            or (group["id"] == "CX-G06" and names == ["items", "description"])
        ):
            category = "text"
        elif type(value) in {int, float}:
            if key in {
                "frames",
                "fps",
                "duration",
                "duration_seconds",
                "offset_seconds",
                "start_seconds",
                "source_start_frame",
            }:
                category = "clock_owned_by_compiler"
            elif native_clock := clock_category(backend, names):
                category = native_clock
                unit = "seconds" if backend in {"unified", "browser"} else "frames"
            elif first in {"events", "timing"} or (
                first == "content" and key in {"at", "start", "end"}
            ):
                category = "event"
                unit = "seconds" if backend == "unified" else "frames"
            elif backend == "browser" and key == "at":
                category, unit = "event", "seconds"
            elif names[:-1] == [
                "style",
                "geometry",
            ] and key in SHIFTED_GEOMETRY_EVENTS.get(group["id"], ()):
                category, unit = "event", "frames"
            elif backend == "browser" and "keys" in names and parts[-1] == 0:
                category = (
                    "event"
                    if group["id"] == CARD_GROUP and pointer(parts) in CARD_LANDMARKS
                    else "native_keyframe_clock"
                )
                unit = "frames"
            elif first == "content" and not (
                group["id"] == PACKAGE_GROUP and names == ["content", "items", "color"]
            ):
                category = "numeric_content_requires_grounding"
        elif value is None and key in {"presenter", "background"}:
            category = "optional_media"
        fields.append(
            {
                "path": pointer(parts),
                "category": category,
                "value_type": type(value).__name__,
                **({"unit": unit} if unit else {}),
                **({"resource_kind": resource_kind} if resource_kind else {}),
            }
        )

    def visit(value: Any, parts: list[str | int]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, [*parts, key])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, [*parts, index])
        else:
            describe(parts, value)

    profile_id = PICTURE_PROFILE if group["id"] == PICTURE_GROUP else None
    if profile_id:
        fields = picture_fields(schema)
        fps = PICTURE_FPS
    else:
        visit(template, [])
    if question_group and branch is None:
        smoke_fields = fields.copy()
        smoke_paths = {f["path"] for f in smoke_fields}
        fields.clear()
        visit(question_variant_template(template, live_background=True), [])
        question_paths = {f["path"] for f in fields}
        fields = [
            f if f["path"] in smoke_paths else {**f, "native_branch": QUESTION_BRANCH}
            for f in fields
        ] + [
            {**f, "native_branch": "smoke"}
            for f in smoke_fields
            if f["path"] not in question_paths
        ]
    if group["id"] in STAGGER_GROUPS:
        fields.extend(strip_fields(group["id"]))
    if group["id"] in SILHOUETTE_GROUPS:
        fields.extend(
            {
                "path": path,
                "category": "resource",
                "value_type": "str",
                "resource_kind": "media",
            }
            for path in SILHOUETTE_PATHS
        )
    return {
        "version": "tengli.native-input-contract/1",
        "release": MOTION_SHA256,
        "group_id": group["id"],
        "backend": backend,
        "schema_sha256": sha256(package / group["input_schema"]),
        "template_sha256": sha256(package / group["input_template"]),
        "native_fps": fps,
        "fields": fields,
        "text_paths": [f["path"] for f in fields if f["category"] == "text"],
        "event_paths": [
            {"path": f["path"], "unit": f["unit"]}
            for f in fields
            if f["category"] == "event"
        ],
        "resource_paths": [
            {"path": f["path"], "kind": f.get("resource_kind")}
            for f in fields
            if f["category"] in {"resource", "optional_media"}
        ],
        "array_capacity_scope": (
            "three images in original picture-parallel-3; internal test workspace only"
            if profile_id
            else "observed indices; schema controls capacity"
        ),
        **(
            {
                "native_profile": profile_id,
                "classic_authoring_status": "classic_attributes_schema_closed",
            }
            if backend == "hypit"
            else {}
        ),
        "schema_variants": {
            keyword: len(schema[keyword])
            for keyword in ("oneOf", "anyOf")
            if keyword in schema
        },
        **(
            {"website_sidecar_profile": stagger_profile(group["id"])}
            if group["id"] in STAGGER_GROUPS
            else {}
        ),
        **(
            {"website_sidecar_scope": "component_only_until_chart_facts_are_bound"}
            if group["id"] == FLOW_GROUP
            else {}
        ),
        **(
            {
                "native_branches": {
                    name: {
                        **dependency,
                        "branch_paths": [
                            field["path"]
                            for field in fields
                            if field.get("native_branch") == name
                        ],
                    }
                    for name, dependency in (
                        (
                            QUESTION_BRANCH,
                            {
                                "original_font_id": QUESTION_FONT,
                                "live_background_slot": QUESTION_BACKGROUND,
                            },
                        ),
                        ("smoke", {"original_external_media": "smoke_alpha_sequence"}),
                    )
                }
            }
            if question_group and branch is None
            else {}
        ),
        **(
            {"native_scene_chain": role_scene_contract()}
            if group["id"] == ROLE_CHAIN_GROUP
            else {}
        ),
        "fresh_recipe_required": True,
        "media_clock_profile": (
            {
                **{
                    k: profile[k]
                    for k in ("id", "media_paths", "scope", "local_sample_seconds")
                },
                **(
                    {
                        "project_scene_clip_paths": list(
                            profile["project_scene_clip_start_events"]
                        )
                    }
                    if "project_scene_clip_start_events" in profile
                    else {}
                ),
            }
            if (profile := clock_profile(group["id"]))
            else None
        ),
        "hypit_compound_attributes_require_native_review": backend == "hypit",
        "runtime_validation": "unverified",
    }


def all_contracts(package: Path) -> dict[str, dict[str, Any]]:
    groups = read_json(package / "catalog/groups.json")["groups"]
    result = {g["id"]: input_contract(package, g) for g in groups}
    if len(result) != 132:
        raise ValueError(
            "Every one of the 132 original groups needs a parameter contract"
        )
    return result
