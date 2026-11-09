"""Build trusted text-layer recipes from original inputs and measured word IDs."""

from pathlib import Path

from .errors import ApiError
from .motion_library import MOTION_SHA256, inside, read_json
from .motion_parameter_contracts import input_contract
from .video_editing_contracts import (
    EditingOptions,
    SemanticBeat,
    SemanticPlan,
    Transcript,
)
from .video_editing_episode_compiler import (
    RELATION_MAPPING,
    EpisodeRecipeBundle,
    NativeEpisodeEntry,
    NativePlacement,
)
from .video_editing_native_compiler import set_native_field
from .video_editing_native_layout import BACKDROP_GROUP
from .video_editing_overlay_templates import validate_template_plan
from .video_editing_word_bindings import word_bindings

PROFILE_ID = "tengli-overlay-recipe-v1"
_FONT_SIZES = {
    "BG-S06": {"upper": 42, "lower": 62},
    "SG-S03": {"prefix": 59, "keyword": 59},
    "AH-S05": {"body": 49, "emphasis": 69},
    "JJ-S01": {"main": 60, "detail": 44},
    "AH-S09": {"title": 78},
}
_TEXT_RECIPE_FIELDS = {
    "text",
    "event",
    "font",
    "native_parameter",
    "native_clock_length",
    "clock_owned_by_compiler",
    "output_owned_by_compiler",
}


def _entry(
    package: Path, group: dict, beat: SemanticBeat, transcript: Transcript
) -> NativeEpisodeEntry:
    if beat.relation in RELATION_MAPPING and not beat.relation_items:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_RELATION_ITEMS_REQUIRED",
            f"{beat.group_id} 缺少关系各项对应的实录词点。",
        )
    if (
        (group["kind"], group["backend"]) != ("subtitle", "subtitle")
        or beat.native_media
        or beat.asset_ids
    ):
        raise ApiError(
            422,
            "EDITING_TEMPLATE_TEXT_LAYER_REQUIRED",
            f"{beat.group_id} 的模板槽需要纯文字透明层。",
        )
    contract = input_contract(package, group)
    if {field["category"] for field in contract["fields"]} - _TEXT_RECIPE_FIELDS:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_NATIVE_PROFILE_REQUIRED",
            f"{beat.group_id} 仍需原生适配。",
        )
    config = read_json(inside(package, group["input_template"]))
    anchors = word_bindings(beat, transcript, contract, set())
    slots = [
        *contract["text_paths"],
        *(event["path"] for event in contract["event_paths"]),
    ]
    text = {row["path"]: row["text"] for row in anchors["text"]}
    if set(slots) != set(text) | {row["path"] for row in anchors["events"]}:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_ANCHORS_REQUIRED",
            f"{beat.group_id} 缺少原生文字或动作的词点。",
        )
    for role, size in _FONT_SIZES.get(beat.group_id, {}).items():
        config["fonts"][role]["size"] = size
    if beat.group_id == "BG-S06":
        config["geometry"].update(left=156, upper_top=76, lower_top=134, mask_top=124)
        config["fonts"]["lower"].update(
            fill="#f6ce68", shadow={"x": 3, "y": 4, "blur": 0.7, "color": "#13100e"}
        )
        if len(text["/content/lower"]) == 6:
            config["capacity"]["lower"] = [6, 6]
    if beat.group_id == "SG-S03":
        for font in config["fonts"].values():
            font["shadow"].update(x=0, y=0, blur=0)
    for role, (minimum, maximum) in config.get("capacity", {}).items():
        path = "/content/" + config["role_content"][role]
        if not minimum <= len(text[path]) <= maximum:
            raise ApiError(
                422,
                "EDITING_TEMPLATE_ROLE_LENGTH",
                f"{beat.group_id} 的实录词组超出角色字数范围。",
            )
    for path in slots:
        set_native_field(config, path, None)
    vertical = beat.group_id == "BG-S04"
    return NativeEpisodeEntry(
        carrier="text",
        placement=NativePlacement(
            layer="subtitle",
            rect=[0.015, 0.21, 0.92, 0.53] if vertical else [0.065, 0.43, 0.87, 0.32],
            reason="给原生左右竖排保留高画幅。"
            if vertical
            else "在人物下方使用原生透明字层。",
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": beat.group_id,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": PROFILE_ID,
            "design_reason": "本期词点绑定原生透明字效。",
            "parameter_decisions": {
                key: "采用原生输入机制和本版网站模板配置。" for key in config
            },
            "config": config,
            "placeholders": slots,
            "dependency_bindings": {},
        },
    )


def build_overlay_recipes(
    package: Path,
    semantic: SemanticPlan,
    transcript: Transcript,
    transcript_sha256: str,
    template: dict,
) -> EpisodeRecipeBundle:
    try:
        validate_template_plan(semantic, template, complete=True)
    except ValueError as error:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_EFFECT_COUNT_REQUIRED",
            "候选须保留至少五种不同的已选模板动效。",
        ) from error
    groups = {
        row["id"]: row for row in read_json(package / "catalog/groups.json")["groups"]
    }
    beats = [beat for beat in semantic.beats if beat.group_id != "Z-M00"]
    entries = {
        beat.id: _entry(package, groups[beat.group_id], beat, transcript)
        for beat in beats
    }
    return EpisodeRecipeBundle(
        version="tengli.episode-recipes/1",
        library_release=MOTION_SHA256,
        source_sha256=transcript.source_sha256,
        transcript_sha256=transcript_sha256,
        planning_origin="tengli_gateway",
        source_review="按实际词点生成原生编排，人物构图、语义、商品事实及听感待预览验收。",
        design={
            "id": PROFILE_ID,
            "mode": "new",
            "sector": "本期口播",
            "audience": "本项目观众",
            "objective": "按口播重点显示所选模板的原生透明动效。",
            "tone": "清晰",
            "background_strategy": "保留连续人物原片。",
            "motion_direction": "按实录词点在人物周围叠加原生动效。",
            "sound_direction": "保留实际口播音轨。",
            "reason": "沿用已保存的模板版本与模型候选。",
            "caption_font_id": EditingOptions().caption_font_id,
        },
        typography=None,
        layout_policy={
            "reason": "按竖屏居中口播布局保护人物与主字幕。",
            "subtitle_safe_rect": [0.055, 0.255, 0.89, 0.625],
        },
        protected_regions=[
            {
                "id": "centered-portrait",
                "start_seconds": 0,
                "end_seconds": transcript.duration_ms / 1000,
                "rect": [0.35, 0.09, 0.34, 0.34],
                "reason": "居中竖屏模板的静态人物保护区，实际画面待核对。",
            }
        ],
        entries=entries,
        overlay_template_id=template["id"],
        intentional_backdrop_beat_ids=[
            beat.id for beat in beats if beat.group_id == BACKDROP_GROUP
        ],
        sound_mode="original_voice_only",
    )
