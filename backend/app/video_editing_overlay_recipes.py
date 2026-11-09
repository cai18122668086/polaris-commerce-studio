"""Build trusted composition recipes from original inputs and measured word IDs."""

from pathlib import Path
from typing import Any

from .errors import ApiError
from .motion_library import MOTION_SHA256, inside, read_json
from .motion_parameter_contracts import input_contract
from .video_editing_browser_clocks import CARD_GROUP, CARD_LANDMARKS, SPLIT_TITLE_FONT
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
from .video_editing_overlay_templates import (
    PICTURE_TEMPLATE_ID,
    validate_template_plan,
)
from .video_editing_question_branch import (
    QUESTION_BACKGROUND,
    QUESTION_BRANCH,
    QUESTION_ENTRY,
    QUESTION_FONT,
    QUESTION_GROUP,
    question_variant_template,
)
from .video_editing_word_bindings import word_bindings

PROFILE_ID = "tengli-overlay-recipe-v2"
# Audited source slices: asset ID, slice start, slice duration, target peak dBFS.
_TYPING = ("sfx-31fef1615e1ded4d", 0.44, 0.25, -27)
_CLICK = ("sfx-caca4bd9dd717c9f", 0, 0.14, -26)
_SELECT = ("sfx-dbafeebc3f7297da", 0.04, 0.16, -25)
_SLIDE = ("sfx-22f661280569e8bc", 0.07, 0.32, -27)
_IMPACT = ("sfx-69dba3f8f41f94e1", 0.03, 0.27, -25)
_ENTRY_SOUNDS = {
    QUESTION_GROUP: (QUESTION_ENTRY, ("sfx-6de45a8ba721db1b", 0.0, 0.5, -22)),
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
_CARD_ENTRY_PATHS = tuple(CARD_LANDMARKS)[:3]
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


def _question_entry(
    package: Path, group: dict, beat: SemanticBeat, transcript: Transcript
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(
        package,
        group,
        branch=QUESTION_BRANCH,
        embedded_question_caption=False,
        live_question_background=True,
    )
    config = question_variant_template(
        read_json(inside(package, group["input_template"])),
        embedded_caption=False,
        live_background=True,
    )
    anchors = word_bindings(beat, transcript, contract, set(beat.asset_ids))
    media = {row["path"]: row["asset_id"] for row in anchors["media"]}
    media_slots = ("presenter", QUESTION_BACKGROUND)
    paths = {f"/media/{slot}/path" for slot in media_slots}
    events = {row["path"]: row["value"] for row in anchors["events"]}
    (text,) = contract["text_paths"]
    if (
        beat.relation != "question"
        or set(media) != paths
        or len(set(media.values())) != 1
        or set(events) != {QUESTION_ENTRY, "/timing/events/dissolve_in"}
        or events[QUESTION_ENTRY] != 0
        or events["/timing/events/dissolve_in"] <= 0
        or [row["path"] for row in anchors["text"]] != [text]
    ):
        raise ApiError(
            422,
            "EDITING_QUESTION_SCENE_BINDINGS_REQUIRED",
            "整帧追问需要实录标题、首词入场、溶解词点及同一原片的两路绑定。",
        )
    for slot in media_slots:
        config["media"][slot]["end_policy"] = "error"
    slots = [
        text,
        *events,
        *(
            f"/media/{slot}/{field}"
            for slot in media_slots
            for field in ("path", "offset_seconds", "duration_seconds")
        ),
    ]
    for path in slots:
        set_native_field(config, path, None)
    return NativeEpisodeEntry(
        carrier="text",
        placement=NativePlacement(
            layer="scene",
            rect=[0, 0, 1, 1],
            reason="原生追问在整帧虚化并溶回同期原片，口播声音持续。",
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": beat.group_id,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": "tengli-question-story-v1",
            "design_reason": "从原片词点绑定整帧追问与溶解。",
            "config": config,
            "placeholders": slots,
            "parameter_decisions": {
                key: "沿用原生追问画布、字形和溶解。" for key in config
            },
            "dependency_ids": [QUESTION_FONT],
            "media_clocks": [
                {"media_path": path, "policy": "transcript_source_window"}
                for path in sorted(paths)
            ],
        },
    ), anchors


def _card_entry(
    package: Path,
    group: dict,
    beat: SemanticBeat,
    transcript: Transcript,
    asset_cards: list[dict],
    *,
    live_background: bool,
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group)
    assets = {
        card["id"]: card["sha256"]
        for card in asset_cards
        if card["kind"] == "image" and card["id"].startswith("material-")
    }
    anchors = word_bindings(beat, transcript, contract, set(beat.asset_ids))
    media = {row["path"]: row["asset_id"] for row in anchors["media"]}
    text = {row["path"]: row["token_ids"] for row in anchors["text"]}
    events = {row["path"]: row for row in anchors["events"]}
    media_paths = {row["path"] for row in contract["resource_paths"]}
    background = media.get("/background")
    allowed_assets = set(assets)
    if live_background:
        allowed_assets.update(
            card["id"]
            for card in asset_cards
            if card["kind"] == "original_video"
            and card["sha256"] == transcript.source_sha256
            and card["id"].startswith("source-")
        )
    if (
        beat.relation != "parallel"
        or len(beat.relation_items) != 3
        or set(media) != media_paths
        or set(media.values()) != set(beat.asset_ids)
        or not set(media.values()) <= allowed_assets
        or (live_background and background in assets)
        or set(text) != set(contract["text_paths"])
        or set(events) != CARD_LANDMARKS.keys()
    ):
        raise ApiError(
            422,
            "EDITING_TEMPLATE_CARD_INPUTS_REQUIRED",
            "三图卡需要本段的三个并列项、已选项目图片及完整词点。",
        )
    image_digests = set()
    for index, item in enumerate(beat.relation_items):
        food, city = (f"/cards/{index}/{key}" for key in ("food", "city"))
        pictures = {food + "/image", city + "/image"}
        labels = {food + "/label", city + "/label"}
        image_id = media[food + "/image"]
        entry = events[_CARD_ENTRY_PATHS[index]]
        if (
            image_id not in assets
            or media[city + "/image"] != image_id
            or text[food + "/label"] != text[city + "/label"]
            or item.asset_ids != [image_id]
            or set(item.native_text_paths) != labels
            or set(item.native_media_paths) != pictures
            or entry["token_id"] != text[food + "/label"][0]
            or entry["edge"] != "start"
        ):
            raise ApiError(
                422,
                "EDITING_TEMPLATE_CARD_RELATION_REQUIRED",
                "每张图卡的两套槽须对应同一词组和图片，并由该词组首词触发。",
            )
        image_digests.add(assets[image_id])
    if len(image_digests) != 3:
        raise ApiError(
            422, "EDITING_TEMPLATE_CARD_IMAGES_DISTINCT", "三张图卡需要三份不同的图片。"
        )
    config = read_json(inside(package, group["input_template"]))
    slots = [
        row["path"]
        for row in contract["fields"]
        if row["category"] in {"text", "resource", "event", "native_keyframe_clock"}
    ]
    for path in slots:
        set_native_field(config, path, None)
    return NativeEpisodeEntry(
        carrier="picture",
        placement=NativePlacement(
            layer="overlay" if live_background else "scene",
            rect=[0, 0, 1, 1],
            reason="原生三图卡叠在同期口播画面上。"
            if live_background
            else "按原全幅三图卡构图呈现项目图片，口播继续。",
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": CARD_GROUP,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": "tengli-picture-compare-v2"
            if live_background
            else "tengli-picture-compare-v1",
            "design_reason": "保留原三张图卡的几何和轨迹，按本期三个词组驱动。",
            "parameter_decisions": {
                key: "沿用原三图卡的画幅、字形、姿态和主题。" for key in config
            },
            "config": config,
            "placeholders": slots,
            "dependency_ids": [SPLIT_TITLE_FONT],
            "browser_word_entry": True,
            **({"browser_live_background": True} if live_background else {}),
        },
    ), anchors


def _entry_sound(
    beat: SemanticBeat,
    anchors: dict[str, Any],
    duration_ms: int,
    avoided: set[str],
    card_path: str | None = None,
) -> NativeSoundCue:
    path, selection = (
        (card_path, _SLIDE) if card_path is not None else _ENTRY_SOUNDS[beat.group_id]
    )
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
        purpose={
            QUESTION_GROUP: "整帧追问入场时给一次短提示，口播继续。",
            CARD_GROUP: "图卡进入时给一次短提示，口播继续。",
        }.get(beat.group_id, "原生文字动效入场时给一次短提示，口播继续。"),
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
    asset_cards: list[dict] | None = None,
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
    entries = {}
    cues: list[NativeSoundCue] = []
    for beat in beats:
        group = groups[beat.group_id]
        if beat.group_id == CARD_GROUP:
            entries[beat.id], anchors = _card_entry(
                package,
                group,
                beat,
                transcript,
                asset_cards or [],
                live_background=template["id"] == PICTURE_TEMPLATE_ID,
            )
            cues.extend(
                _entry_sound(beat, anchors, transcript.duration_ms, avoided, path)
                for path in _CARD_ENTRY_PATHS
            )
        else:
            make_entry = _question_entry if beat.group_id == QUESTION_GROUP else _entry
            entries[beat.id], anchors = make_entry(package, group, beat, transcript)
            cues.append(_entry_sound(beat, anchors, transcript.duration_ms, avoided))
    has_scene = any(entry.placement.layer == "scene" for entry in entries.values())
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
            "objective": (
                "按口播重点显示所选模板的原生构图和动效。"
                if has_scene
                else "按口播重点显示所选模板的原生透明动效。"
            ),
            "tone": "清晰",
            "background_strategy": (
                "保留连续口播，按模板使用原片或整帧原生场景。"
                if has_scene
                else "保留连续人物原片。"
            ),
            "motion_direction": (
                "按实录词点执行模板指定的字幕叠加或整帧构图。"
                if has_scene
                else "按实录词点在人物周围叠加原生动效。"
            ),
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
