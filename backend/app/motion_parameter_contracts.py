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
from .video_editing_browser_rotation import ROTATION_GROUP
from .video_editing_hypit import (
    PICTURE_FPS,
    PICTURE_GROUP,
    PICTURE_PROFILE,
    picture_fields,
)
from .video_editing_hypit_strips import (
    FLOW_GROUP,
    SLANT_BACKGROUND,
    SLANT_FOREGROUND,
    SLANT_GROUP,
    SLANT_IMAGES,
    STAGGER_GROUPS,
    stagger_profile,
    strip_fields,
)
from .video_editing_judgment import JUDGMENT_GROUP
from .video_editing_line_branch import LINE_GROUP, LINE_HAND_PATH, line_template
from .video_editing_media_clocks import clock_profile
from .video_editing_native_content import (
    FILM_FEEDBACK_GROUP,
    PACKAGE_GROUP,
    ROLE_CHAIN_GROUP,
    WHY_GROUP,
    WHY_TEXT,
    live_package_template,
    role_scene_contract,
    why_template,
)
from .video_editing_question_branch import (
    QUESTION_BACKGROUND,
    QUESTION_BRANCH,
    QUESTION_FONT,
    QUESTION_GROUP,
    question_variant_template,
)
from .video_editing_question_card import QUESTION_CARD_GLYPH, question_card_a_input
from .video_editing_story_panels import TRIPTYCH, triptych_template
from .video_editing_unified_scenes import (
    PRESENTER_VIDEO_GROUPS,
    unified_presenter_template,
)

SILHOUETTE_GROUPS = frozenset(("W-R04", "W-R09"))
SILHOUETTE_PATHS = tuple(f"/media/silhouettes/{i}/path" for i in range(7))

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
    current_line_art: bool = True,
    embedded_line_caption: bool = True,
    embedded_judgment_caption: bool = True,
    current_why_props: bool = True,
    embedded_why_caption: bool = True,
    original_input_a: bool = False,
    current_unified_presenter: bool = False,
    triptych_video_slots: set[int] | None = None,
) -> dict[str, Any]:
    template_path = (
        question_card_a_input(package, group)
        if original_input_a
        else package / group["input_template"]
    )
    template = read_json(template_path)
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
    if group["id"] in PRESENTER_VIDEO_GROUPS and current_unified_presenter:
        template = unified_presenter_template(template)
    if group["id"] == TRIPTYCH and triptych_video_slots:
        template = triptych_template(template, triptych_video_slots)
    if group["id"] == LINE_GROUP and current_line_art:
        template = line_template(template, embedded_caption=embedded_line_caption)
    if group["id"] == JUDGMENT_GROUP and not embedded_judgment_caption:
        template["content"]["captions"] = []
    if group["id"] == WHY_GROUP and current_why_props:
        template = why_template(template, embedded_caption=embedded_why_caption)
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
            if group["id"] == LINE_GROUP and pointer(parts) == LINE_HAND_PATH:
                resource_kind = "transparent_png_sheet"
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
            original_input_a
            and pointer(parts) == QUESTION_CARD_GLYPH
            or group["id"] == "YY6O01"
            and parts == ["content", "question"]
        ) and value == "?":
            category = "original_design_glyph"
        elif isinstance(value, str) and (
            (first == "content" and key not in STYLE_NAMES)
            or (group["id"] == "LYO02" and parts == ["content", "theme"])
            or (backend == "browser" and key in TEXT_NAMES)
            or (group["id"] == "CX-G06" and names == ["items", "description"])
        ):
            category = "text"
        elif type(value) in {int, float}:
            if group["id"] == LINE_GROUP and names[:2] == ["media", "hand_sequence"]:
                category = "native_parameter"
            elif key in {
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
            elif group["id"] == FILM_FEEDBACK_GROUP and names == [
                "content",
                "comments",
                "likes",
            ]:
                category = "evidence_bound_comment_likes"
            elif (
                group["id"] == FILM_FEEDBACK_GROUP
                and names[:2]
                == [
                    "content",
                    "comments",
                ]
                and key in {"x", "y", "size"}
            ):
                category = "native_parameter"
            elif first == "content" and not (
                group["id"] == PACKAGE_GROUP and names == ["content", "items", "color"]
            ):
                category = "numeric_content_requires_grounding"
        elif value is None and key in {"presenter", "background"}:
            category = "optional_media"
        if group["id"] == SLANT_GROUP:
            slot = pointer(parts)
            if slot == SLANT_FOREGROUND:
                resource_kind = "original_video"
            elif slot in (SLANT_BACKGROUND, *SLANT_IMAGES):
                resource_kind = "image"
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
    media_profile = clock_profile(group["id"])
    references = (media_profile or {}).get("source_reference_aliases", {})
    return {
        "version": "tengli.native-input-contract/1",
        "release": MOTION_SHA256,
        "group_id": group["id"],
        "backend": backend,
        "schema_sha256": sha256(package / group["input_schema"]),
        "template_sha256": sha256(template_path),
        "native_fps": fps,
        "fields": fields,
        "text_paths": [f["path"] for f in fields if f["category"] == "text"],
        "event_paths": [
            {"path": f["path"], "unit": f["unit"]}
            for f in fields
            if f["category"] == "event"
        ],
        "resource_paths": [
            {
                "path": f["path"],
                "kind": f.get("resource_kind"),
                **(
                    {"same_asset_as": references[f["path"]]}
                    if f["path"] in references
                    else {}
                ),
            }
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
        **(
            {
                "native_question_gloss": {
                    "path": WHY_TEXT,
                    "source": "锚定原话中完整的短问词，例如为什么、怎么、谁。",
                    "binding": "英文由编译器映射。两个问号道具须分别引用本期透明图片。",
                }
            }
            if group["id"] == WHY_GROUP and current_why_props
            else {}
        ),
        **(
            {
                "native_evidence_requirements": {
                    "counts": [
                        f["path"]
                        for f in fields
                        if f["category"] == "evidence_bound_comment_likes"
                    ],
                    "binding": (
                        "点赞数由可信配方绑定本期对应证据图、记录来源和采集时间。"
                        "规划只提供评论实录词点与素材 ID。缺少点赞记录时登记缺口。"
                    ),
                }
            }
            if group["id"] == FILM_FEEDBACK_GROUP
            else {}
        ),
        "fresh_recipe_required": True,
        **(
            {
                "native_card_focus": {
                    "presenter": "绑定本期同期口播原片。",
                    "artwork": "三张不同的本期图片对应三项并列内容。",
                    "timing": "第一项首词开始该镜头，后两项各用首词切换焦点。",
                    "background": "原生暖色背景固定。",
                }
            }
            if group["id"] == ROTATION_GROUP
            else {}
        ),
        "media_clock_profile": (
            {
                **{
                    k: media_profile[k]
                    for k in ("id", "media_paths", "scope", "local_sample_seconds")
                },
                **(
                    {
                        "project_scene_clip_paths": list(
                            media_profile["project_scene_clip_start_events"]
                        )
                    }
                    if "project_scene_clip_start_events" in media_profile
                    else {}
                ),
            }
            if media_profile
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
