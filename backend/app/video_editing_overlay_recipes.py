"""Build trusted text-layer recipes from original inputs and measured word IDs."""

from pathlib import Path
from typing import Any

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
from .video_editing_native_sound import (
    NativeMusicTrack,
    NativeSoundCue,
    NativeSoundDesign,
)
from .video_editing_overlay_templates import validate_template_plan
from .video_editing_word_bindings import word_bindings

PROFILE_ID = "tengli-overlay-recipe-v2"
# Audited source slices: asset ID, slice start, slice duration, target peak dBFS.
_TYPING = ("sfx-31fef1615e1ded4d", 0.44, 0.25, -27)
_CLICK = ("sfx-caca4bd9dd717c9f", 0, 0.14, -26)
_SELECT = ("sfx-dbafeebc3f7297da", 0.04, 0.16, -25)
_SLIDE = ("sfx-22f661280569e8bc", 0.07, 0.32, -27)
_IMPACT = ("sfx-69dba3f8f41f94e1", 0.03, 0.27, -25)
_ENTRY_SOUNDS = {
    "AH-S05": ("/events/type_frame", _TYPING),
    "AH-S09": ("/events/title_frame", _CLICK),
    "AHG-S02": ("/events/mark/0", _SELECT),
    "BG-S04": ("/events/body_frame", _SLIDE),
    "BG-S06": ("/events/upper_start", _SLIDE),
    "JJ-S01": ("/events/main/0", _CLICK),
    "JJ-S03": ("/events/line/0", _IMPACT),
    "SG-S02": ("/events/drop_frame", _SELECT),
    "SG-S03": ("/events/enter_start", _IMPACT),
    "SG-S06": ("/events/upper_start", _SLIDE),
    "SG-S09": ("/events/enter_start", _TYPING),
    "SG-S10": ("/events/enter_start", _SLIDE),
}
_MUSIC = ("bgm-b5035a43098ee293", "bgm-f318d21e6b2d98bb")
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
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
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
    entry = NativeEpisodeEntry(
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
    return entry, anchors


def _entry_sound(
    beat: SemanticBeat, anchors: dict[str, Any], duration_ms: int, avoided: set[str]
) -> NativeSoundCue:
    path, selection = _ENTRY_SOUNDS[beat.group_id]
    event = next(row for row in anchors["events"] if row["path"] == path)
    asset_id, source_start, length, peak = (
        selection if selection[0] not in avoided else _CLICK
    )
    if asset_id in avoided:
        asset_id, source_start, length, peak = _SELECT
    if asset_id in avoided:
        raise ApiError(
            422, "EDITING_TEMPLATE_SOUND_UNAVAILABLE", "入场候选音效均已被避用。"
        )
    remaining = (
        duration_ms - event["measured_anchor_ms"] - event["frame_quantization_ms"]
    ) / 1000
    length = min(length, remaining)
    if length < 0.06:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_SOUND_TOO_LATE",
            f"{beat.group_id} 的入场词点距离片尾太近，无法保留可听音效。",
        )
    return NativeSoundCue(
        asset_id=asset_id,
        beat_id=beat.id,
        event_path=path,
        phase="entry",
        purpose="原生文字动效入场时给一次短提示，口播继续。",
        source_start_seconds=source_start,
        trim_duration_seconds=length,
        target_peak_dbfs=peak,
    )


def build_overlay_recipes(
    package: Path,
    semantic: SemanticPlan,
    transcript: Transcript,
    transcript_sha256: str,
    template: dict,
    choice_snapshot: dict,
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
    avoided = {
        row["target_id"]
        for row in choice_snapshot.get("notes", [])
        if row["target_kind"] == "bundled_asset" and row["choice"] == "avoid"
    }
    music_id = next((asset_id for asset_id in _MUSIC if asset_id not in avoided), None)
    if music_id is None:
        raise ApiError(
            422, "EDITING_TEMPLATE_MUSIC_UNAVAILABLE", "候选背景音乐均已被避用。"
        )
    entries, cues = {}, []
    for beat in beats:
        entries[beat.id], anchors = _entry(
            package, groups[beat.group_id], beat, transcript
        )
        cues.append(_entry_sound(beat, anchors, transcript.duration_ms, avoided))
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
            "sound_direction": (
                "保留实际口播电平，每次原生动效入场加短音效。全程以低位原库背景乐铺底。"
            ),
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
        sound_mode="native_mix",
        sound=NativeSoundDesign(
            fx=cues,
            music=[
                NativeMusicTrack(
                    asset_id=music_id,
                    start="episode_start",
                    end="episode_end",
                    gain_db=-33,
                    fade_seconds=min(0.8, transcript.duration_ms / 2000),
                    reason="让原库背景乐在连续口播下低位铺底，片头片尾淡入淡出。",
                    loop=True,
                )
            ],
        ),
    )
