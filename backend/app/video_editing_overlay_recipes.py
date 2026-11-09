"""Build trusted composition recipes from original inputs and measured word IDs."""

import math
from pathlib import Path
from typing import Any

from .errors import ApiError
from .motion_library import MOTION_SHA256, inside, read_json
from .motion_parameter_contracts import input_contract
from .video_editing_azl_panels import (
    AZL_DESIGN_ID,
    AZL_ENTRY,
    AZL_GROUPS,
    AZL_PRESENTER,
    AZL_RECT,
    azl_materials,
    azl_slots,
    validate_azl_anchors,
)
from .video_editing_bg03_readability import BG_OFFSET_GROUP, apply_outline
from .video_editing_browser_clocks import (
    CARD_GROUP,
    CARD_LANDMARKS,
    NUMBERED_EVENTS,
    NUMBERED_GROUP,
    NUMBERED_IMAGES,
    NUMBERED_LABELS,
    NUMBERED_LINES,
    NUMBERED_PRESENTER,
)
from .video_editing_browser_rotation import (
    ROTATION_EVENTS,
    ROTATION_GROUP,
    ROTATION_IMAGES,
    ROTATION_LABELS,
    rotation_card_clock,
    rotation_source_clock,
)
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
from .video_editing_highlights import AUTOMATIC_TEXT_PROFILE
from .video_editing_hypit_strips import (
    LIVE_STRIP_GROUP,
    STRIP_EVENTS,
    STRIP_IMAGE,
    STRIP_TEXT,
    compile_flow_plate,
    compile_strips,
)
from .video_editing_judgment import (
    JUDGMENT_BACKGROUND,
    JUDGMENT_CONCLUSION,
    JUDGMENT_EVENTS,
    JUDGMENT_GROUP,
    JUDGMENT_IMAGES,
    JUDGMENT_LABELS,
)
from .video_editing_line_branch import (
    LINE_DIRECTOR_PATH,
    LINE_GROUP,
    LINE_HAND_ENTRY,
    LINE_HAND_PATH,
    LINE_PREVIOUS_PATH,
    line_template,
)
from .video_editing_materials import project_image_digests
from .video_editing_native_compiler import set_native_field
from .video_editing_native_content import PACKAGE_GROUP, live_package_template
from .video_editing_native_layout import (
    BACKDROP_GROUP,
    TEXT_HANDOFF_GROUP,
    TEXT_HANDOFF_MAX_FRAMES,
)
from .video_editing_native_sound import (
    NativeMusicTrack,
    NativeSoundCue,
    NativeSoundDesign,
)
from .video_editing_overlay_templates import (
    AUTOMATIC_TEMPLATE_DEPENDENCIES,
    OPENING_GROUPS,
    PICTURE_TEMPLATE_ID,
    validate_template_plan,
)
from .video_editing_presenter_motion import (
    MOTION_CAPTION,
    MOTION_CLIPS,
    MOTION_PRESENTER,
    PRESENTER_MOTION_GROUPS,
    motion_project_clips,
    motion_sound_paths,
    validate_motion_anchors,
)
from .video_editing_question_branch import (
    QUESTION_BACKGROUND,
    QUESTION_BRANCH,
    QUESTION_ENTRY,
    QUESTION_GROUP,
    question_variant_template,
)
from .video_editing_question_card import (
    QUESTION_CARD_A_DESIGN,
    QUESTION_CARD_ENGLISH,
    QUESTION_CARD_GLYPH,
    QUESTION_CARD_GROUP,
    QUESTION_CARD_SOUND,
    automatic_question_card_gloss,
    question_card_a_input,
)
from .video_editing_subtitle_foreground import FOREGROUND_SUBTITLE_DEPENDENCIES
from .video_editing_word_bindings import word_bindings
from .video_editing_yy_openings import (
    YY_OPENING_ENTRY_EVENTS,
    YY_OPENING_EXPANDED_GROUPS,
    YY_OPENING_SOURCE_EVENTS,
    validate_yy_opening,
)

PROFILE_ID = AUTOMATIC_TEXT_PROFILE
# Audited source slices: asset ID, slice start, slice duration, target peak dBFS.
_TYPING = ("sfx-31fef1615e1ded4d", 0.44, 0.25, -27)
_CLICK = ("sfx-caca4bd9dd717c9f", 0, 0.14, -26)
_SELECT = ("sfx-dbafeebc3f7297da", 0.04, 0.16, -25)
_SLIDE = ("sfx-22f661280569e8bc", 0.07, 0.32, -27)
_IMPACT = ("sfx-69dba3f8f41f94e1", 0.03, 0.27, -25)
_ENTRY_SOUNDS = {
    **dict.fromkeys(AZL_GROUPS, (AZL_ENTRY, _SLIDE)),
    **{group: (path, _SLIDE) for group, path in YY_OPENING_ENTRY_EVENTS.items()},
    QUESTION_GROUP: (QUESTION_ENTRY, ("sfx-6de45a8ba721db1b", 0.0, 0.5, -22)),
    QUESTION_CARD_GROUP: (QUESTION_CARD_SOUND, ("sfx-6de45a8ba721db1b", 0.0, 0.5, -22)),
    "AH-S01": ("/events/keyword_frame", _IMPACT),
    "AH-S02": ("/events/body_frame", _SLIDE),
    "AH-S04": ("/events/body_frame", _TYPING),
    "AH-S05": ("/events/type_frame", _TYPING),
    "AH-S06": ("/events/center_frame", _SLIDE),
    "AH-S08": ("/events/title_frame", _SLIDE),
    "AH-S09": ("/events/title_frame", _CLICK),
    "AHG-S01": ("/events/body/0", _SLIDE),
    "AHG-S02": ("/events/mark/0", _SELECT),
    "AHG-S04": ("/events/type/0", _TYPING),
    "AHG-S05": ("/events/body/0", _SLIDE),
    "BG-S01": ("/events/body_frame", _SLIDE),
    "BG-S02": ("/events/body_frame", _CLICK),
    "BG-S03": ("/events/body_frame", _SLIDE),
    "BG-S04": ("/events/body_frame", _SLIDE),
    "BG-S05": ("/events/body_frame", _IMPACT),
    "BG-S06": ("/events/upper_start", _SLIDE),
    "BG-S07": ("/events/upper_start", _SLIDE),
    "BG-S08": ("/events/upper_start", _IMPACT),
    "BG-S09": ("/events/body_frame", _IMPACT),
    "BG-S10": ("/events/left_frame", _SLIDE),
    "BG-S11": ("/events/body_frame", _IMPACT),
    "JJ-S01": ("/events/main/0", _CLICK),
    "JJ-S02": ("/events/grow/0", _SLIDE),
    "JJ-S03": ("/events/line/0", _IMPACT),
    "JJ-S04": ("/events/body/0", _CLICK),
    "JJ-S05": ("/events/body/0", _SELECT),
    "JJ-S06": ("/events/body/0", _SLIDE),
    "JJ-S07": ("/events/merge/0", _SLIDE),
    "JJ-S08": ("/events/settle/0", _SLIDE),
    "JJ-S09": ("/events/zoom1/0", _IMPACT),
    LINE_GROUP: (LINE_HAND_ENTRY, _SLIDE),
    "LYO01": ("/events/text_frame", _SLIDE),
    "LYO02": ("/events/text_frame", _SELECT),
    "LYO03": ("/events/subtitle_frame", _CLICK),
    "LYO04": ("/events/text_frame", _SLIDE),
    "SG-S01": ("/events/enter_start", _SLIDE),
    "SG-S02": ("/events/drop_frame", _SELECT),
    "SG-S03": ("/events/enter_start", _IMPACT),
    "SG-S04": ("/events/enter_start", _SLIDE),
    "SG-S05": ("/events/enter_start", _SLIDE),
    "SG-S06": ("/events/upper_start", _SLIDE),
    "SG-S07": ("/events/lead_start", _SLIDE),
    "SG-S08": ("/events/lead_start", _SLIDE),
    "SG-S09": ("/events/enter_start", _TYPING),
    "SG-S10": ("/events/enter_start", _SLIDE),
}
_CARD_ENTRY_PATHS = tuple(CARD_LANDMARKS)[:3]
_JUDGMENT_SOUNDS = dict(
    zip(
        JUDGMENT_EVENTS[:5],
        (
            _SLIDE,
            _SLIDE,
            _SELECT,
            _IMPACT,
            _CLICK,
        ),
        strict=True,
    )
)
_OPENING_PRESENTER = "/media/presenter/path"
_PACKAGE_LABELS = tuple(f"/content/items/{i}/label" for i in range(4))
_PACKAGE_IMAGES = tuple(f"/media/product_images/{i}/path" for i in range(4))
_PACKAGE_EVENTS = tuple(f"/timing/events/item{i}" for i in range(4))
_PACKAGE_EXTRA = "/content/items/3/extra"
_LINE_LABELS = {
    "/content/director_label": 4,
    "/content/hand_label": 4,
    "/content/paper_text": 9,
}
_LINE_EVENTS = (
    "/timing/events/previous_out",
    LINE_HAND_ENTRY,
    "/timing/events/label_in",
    *(f"/timing/events/portrait_scale_keys/{i}" for i in range(4)),
)
_OPENING_ROLES = {
    "/content/caption": ("/events/text_frame", 14),
    "/content/theme": ("/events/text_frame", 8),
    "/content/title": ("/events/title_frame", 4),
    "/content/subtitle": ("/events/subtitle_frame", 12),
}
_MUSIC = ("bgm-b5035a43098ee293", "bgm-f318d21e6b2d98bb")
_FONT_SIZES = {
    "AH-S04": {"header": 56},
    "AHG-S01": {"body": 80},
    "BG-S06": {"upper": 42, "lower": 62},
    "BG-S08": {"lower": 84},
    "SG-S03": {"prefix": 59, "keyword": 59},
    "SG-S01": {"main": 86, "detail": 62},
    "AH-S05": {"body": 49, "emphasis": 69},
    "JJ-S01": {"main": 60, "detail": 44},
    "JJ-S07": {"left": 54, "right": 54, "keyword": 57},
    "JJ-S09": {"top": 63, "bottom": 62},
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
_TEXT_ENTRY_WORDS = {
    "AH-S01": {"keyword_frame": "keyword", "body_frame": "body"},
    "AH-S04": {"body_frame": "body", "header_frame": "header"},
    "AH-S06": {"center_frame": "center"},
    "AHG-S01": {"body/0": "body", "keyword/0": "keyword"},
    "BG-S01": {"body_frame": "body", "focus_frame": "focus"},
    "BG-S07": {"upper_start": "upper", "lower_start": "lower"},
    "BG-S08": {"upper_start": "upper", "lower_start": "lower"},
    "BG-S09": {"body_frame": "body", "focus_frame": "focus"},
    "BG-S10": {"left_frame": "left", "right_frame": "right", "focus_frame": "focus"},
    "BG-S11": {"body_frame": "body", "focus_frame": "focus"},
    TEXT_HANDOFF_GROUP: {"body/0": "body", "handoff/0": "keyword"},
    "JJ-S07": {"merge/0": "left", "keyword/0": "keyword"},
    "JJ-S08": {"settle/0": "headline", "swap/0": "detail"},
    "JJ-S09": {"zoom1/0": "top", "zoom2/0": "bottom"},
    "SG-S01": {"enter_start": "main", "detail_start": "detail"},
    "SG-S04": {"enter_start": "lead_a", "accent_start": "accent"},
    "SG-S05": {"enter_start": "lead", "front_start": "accent"},
    "SG-S07": {"lead_start": "lead", "accent_start": "accent"},
    "SG-S08": {"lead_start": "lead", "accent_start": "accent"},
}
_TEXT_CLEAR_FRAMES = {"AH-S01": 10, "AH-S04": 10}
_SIMULTANEOUS_TEXT_START = {"JJ-S08": "headline", "JJ-S09": "top"}
_TEXT_TRANSITIONS = {
    "JJ-S07": ("merge", "split", "keyword"),
    "JJ-S08": ("settle", "swap"),
    "JJ-S09": ("zoom1", "zoom2"),
    "SG-S01": ("enter", "split", "detail"),
    "SG-S04": ("enter", "merge", "accent", "exit"),
    "SG-S05": ("enter", "front", "exit"),
    "SG-S07": ("lead", "raise", "accent", "swap", "exit"),
    "SG-S08": ("lead", "back", "accent", "exit"),
}
_BG_FOREGROUND_LIMITS = {
    "BG-S09": {"body": 6, "focus": 7},
    "BG-S10": {"left": 2, "right": 2, "focus": 7},
    "BG-S11": {"body": 6, "focus": 7},
}


def _foreground_anchors(group: str, anchors: dict, text: dict, config: dict) -> None:
    events = {row["path"][8:]: row for row in anchors["events"]}
    frames = {event: row["value"] for event, row in events.items()}
    if group == "AH-S06":
        words = {row["path"]: row["token_ids"] for row in anchors["text"]}
        english = text["/content/english"]
        if (
            not english.isascii()
            or not any(char.isalpha() for char in english)
            or any(not (char.isalpha() or char in " '-") for char in english)
            or events["english_frame"]["token_id"] not in words["/content/english"]
            or events["side_frame"]["token_id"] not in words["/content/right"]
            or not frames["center_frame"]
            <= frames["english_frame"]
            <= frames["side_frame"]
            or frames["clear_frame"] - frames["side_frame"]
            < config["events"]["shard_spread_frames"] + 8
        ):
            raise ApiError(
                422,
                "EDITING_TEMPLATE_ANCHORS_REQUIRED",
                "AH-S06 须绑定实录英文字母及侧字，并给原生溶落留足时间。",
            )
    if group == "SG-S05" and not (
        frames["enter_end"] <= frames["cycle_2"]
        and frames["cycle_2"] + 8 <= frames["cycle_3"]
        and frames["cycle_3"] + 8 <= frames["front_start"]
        and frames["front_end"] <= frames["exit_start"]
    ):
        raise ApiError(
            422,
            "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
            "SG-S05 须先完成三种原字体轮换，再显示金字并退场。",
        )
    if group == "SG-S08" and not (
        frames["lead_end"] <= frames["back_start"] <= frames["accent_start"]
        and frames["accent_end"] <= frames["exit_start"]
    ):
        raise ApiError(
            422,
            "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
            "SG-S08 须从引导词退为背衬，再完成前景重点的入场与退场。",
        )
    if limits := _BG_FOREGROUND_LIMITS.get(group):
        if any(
            not 1 <= len(text["/content/" + role]) <= limit
            for role, limit in limits.items()
        ):
            raise ApiError(
                422,
                "EDITING_TEMPLATE_ROLE_LENGTH",
                f"{group} 的实录字数超出原生字槽范围。",
            )
        if not 0 <= frames["retreat_frame"] - frames["focus_frame"] <= 5:
            raise ApiError(
                422,
                "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
                f"{group} 的白字须紧随前景重点退为背衬。",
            )
        if group == "BG-S10" and frames["right_frame"] + 5 > frames["focus_frame"]:
            raise ApiError(
                422,
                "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
                "BG-S10 须让右侧白词拼合后，再显示金色重点。",
            )


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
    config = read_json(inside(package, group["input_template"]))
    dependency_ids = FOREGROUND_SUBTITLE_DEPENDENCIES.get(beat.group_id, ())
    dependency_fields = {
        field["path"]
        for field in contract["fields"]
        if field["category"] == "native_dependency"
    }
    expected_fields = {
        f"/fonts/{role}/path": style["path"].removeprefix("input://")
        for role, style in config.get("fonts", {}).items()
        if style.get("path", "").startswith("input://")
    }
    if (
        {field["category"] for field in contract["fields"]}
        - (_TEXT_RECIPE_FIELDS | {"native_dependency"})
        or dependency_fields != expected_fields.keys()
        or set(expected_fields.values()) != set(dependency_ids)
    ):
        raise ApiError(
            422,
            "EDITING_TEMPLATE_NATIVE_PROFILE_REQUIRED",
            f"{beat.group_id} 仍需原生适配。",
        )
    anchors = word_bindings(beat, transcript, contract, set())
    slots = [
        *contract["text_paths"],
        *(event["path"] for event in contract["event_paths"]),
    ]
    text = {row["path"]: row["text"] for row in anchors["text"]}
    event_values = {row["path"]: row["value"] for row in anchors["events"]}
    if set(slots) != set(text) | event_values.keys():
        raise ApiError(
            422,
            "EDITING_TEMPLATE_ANCHORS_REQUIRED",
            f"{beat.group_id} 缺少原生文字或动作的词点。",
        )
    if beat.group_id in FOREGROUND_SUBTITLE_DEPENDENCIES or beat.group_id in {
        "BG-S09",
        "SG-S08",
    }:
        _foreground_anchors(beat.group_id, anchors, text, config)
    if entry_words := _TEXT_ENTRY_WORDS.get(beat.group_id):
        text_starts = {row["path"]: row["token_ids"][0] for row in anchors["text"]}
        events = {row["path"]: row for row in anchors["events"]}
        if any(
            events["/events/" + event]["edge"] != "start"
            or events["/events/" + event]["token_id"]
            != text_starts["/content/" + field]
            for event, field in entry_words.items()
        ):
            raise ApiError(
                422,
                "EDITING_TEMPLATE_ANCHORS_REQUIRED",
                f"{beat.group_id} 的各层文字必须在对应实录首词入场。",
            )
        entrance_frames = [event_values["/events/" + event] for event in entry_words]
        clear_length = _TEXT_CLEAR_FRAMES.get(beat.group_id)
        if entrance_frames != sorted(set(entrance_frames)) or (
            clear_length
            and event_values["/events/clear_frame"] - entrance_frames[-1] < clear_length
        ):
            raise ApiError(
                422,
                "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
                f"{beat.group_id} 的各层文字须依次出画，留足原生入场时间。",
            )
        original_limits = read_json(inside(package, group["contract"])).get(
            "content_capacity", {}
        )
        if any(
            type(limit) is int and not 1 <= len(text["/content/" + role]) <= limit
            for role, limit in original_limits.items()
        ):
            raise ApiError(
                422,
                "EDITING_TEMPLATE_ROLE_LENGTH",
                f"{beat.group_id} 的实录词组超出原生角色字数范围。",
            )
        first_role = _SIMULTANEOUS_TEXT_START.get(beat.group_id)
        if first_role and text_starts["/content/" + first_role] != beat.first_token_id:
            raise ApiError(
                422,
                "EDITING_TEMPLATE_ANCHORS_REQUIRED",
                f"{beat.group_id} 的原生双行须从本段首个实录词开始。",
            )
        for transition in _TEXT_TRANSITIONS.get(beat.group_id, ()):
            path = "/events/" + transition
            begin, end = (
                ("/0", "/1") if beat.group_id.startswith("JJ-") else ("_start", "_end")
            )
            if event_values[path + begin] >= event_values[path + end]:
                raise ApiError(
                    422,
                    "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
                    f"{beat.group_id} 的原生动作起止需要不同的实录帧。",
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
    if beat.group_id == "JJ-S02" and (
        event_values["/events/retreat/1"] > event_values["/events/front/0"]
    ):
        raise ApiError(
            422,
            "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
            "JJ-S02 的实录词点须让后景退定，再开始显示前景说明。",
        )
    if beat.group_id == "AHG-S01" and (
        event_values["/events/retreat/1"] > event_values["/events/keyword/0"]
    ):
        raise ApiError(
            422,
            "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
            "AHG-S01 须在前字退定后再按实录词点显示后字。",
        )
    if beat.group_id == "SG-S04" and not (
        0
        < event_values["/events/accent_start"] - event_values["/events/merge_start"]
        < event_values["/events/accent_end"] - event_values["/events/merge_start"]
        <= 32
    ):
        raise ApiError(
            422,
            "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
            "SG-S04 的白词合并与金字接力须处在同一段短交接。",
        )
    if beat.group_id == "JJ-S08" and (
        event_values["/events/swap/0"] - event_values["/events/settle/1"] < 6
    ):
        raise ApiError(
            422,
            "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
            "JJ-S08 两行落定后须留出可读时间，再开始斜排换位。",
        )
    if beat.group_id == TEXT_HANDOFF_GROUP and not (
        1
        <= event_values["/events/handoff/1"] - event_values["/events/handoff/0"]
        <= TEXT_HANDOFF_MAX_FRAMES
    ):
        raise ApiError(
            422,
            "EDITING_TEMPLATE_TEXT_HANDOFF_REQUIRED",
            "JJ-S06 的同位换字需要 1 至 12 帧的实录交接窗口。",
        )
    if beat.group_id in {
        "AH-S04",
        "AHG-S01",
        "SG-S01",
        "SG-S03",
        "BG-S03",
        "JJ-S07",
        "JJ-S09",
    }:
        for font in config["fonts"].values():
            font["shadow"].update(x=0, y=0, blur=0)
    if beat.group_id == "BG-S08":
        config["fonts"]["lower"].update(outline_px=2, outline_color="#151419")
    decisions = {key: "采用原生输入机制和本版网站模板配置。" for key in config}
    if beat.group_id == BG_OFFSET_GROUP:
        apply_outline(config, "both")
        decisions["fonts"] = "保持原字色和字号，按原生分层检查选择深色描边。"
    for field, (minimum, maximum) in config.get("capacity", {}).items():
        path = "/content/" + field
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
            "parameter_decisions": decisions,
            "config": config,
            "placeholders": slots,
            "dependency_bindings": {},
            **({"dependency_ids": list(dependency_ids)} if dependency_ids else {}),
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
            "dependency_ids": list(AUTOMATIC_TEMPLATE_DEPENDENCIES[beat.group_id]),
            "media_clocks": [
                {"media_path": path, "policy": "transcript_source_window"}
                for path in sorted(paths)
            ],
        },
    ), anchors


def _question_card_entry(
    package: Path, group: dict, beat: SemanticBeat, transcript: Transcript
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group, original_input_a=True)
    config = read_json(question_card_a_input(package, group))
    anchors = word_bindings(beat, transcript, contract, set())
    gloss = automatic_question_card_gloss(beat, anchors, transcript)
    slots = [
        *(row["path"] for row in anchors["text"]),
        *(row["path"] for row in anchors["events"]),
        QUESTION_CARD_ENGLISH,
    ]
    for path in slots:
        set_native_field(config, path, None)
    return NativeEpisodeEntry(
        carrier="text",
        placement=NativePlacement(
            layer="subtitle",
            rect=[0.10, 0.435, 0.80, 0.258],
            reason="按原画幅放置左右短语与问号，给人物和主字幕留空间。",
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": beat.group_id,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": QUESTION_CARD_A_DESIGN,
            "design_reason": "沿用原 A 版字形与动画，绑定本期实录追问及短释义。",
            "config": config,
            "placeholders": slots,
            "parameter_decisions": {
                **{key: "沿用原生构图与参数。" for key in config},
                QUESTION_CARD_GLYPH: "保留原设计问号。",
            },
            "dependency_ids": list(AUTOMATIC_TEMPLATE_DEPENDENCIES[beat.group_id]),
            "question_card_gloss": gloss,
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
    assets = project_image_digests(asset_cards)
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
            "dependency_ids": list(AUTOMATIC_TEMPLATE_DEPENDENCIES[beat.group_id]),
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
        (
            card_path,
            _JUDGMENT_SOUNDS[card_path] if beat.group_id == JUDGMENT_GROUP else _SLIDE,
        )
        if card_path is not None
        else _ENTRY_SOUNDS[beat.group_id]
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
    if beat.group_id == QUESTION_CARD_GROUP:
        remaining -= 1 / 30
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
            QUESTION_CARD_GROUP: "原问号首个可见帧给一次短提示，口播继续。",
            CARD_GROUP: "图卡进入时给一次短提示，口播继续。",
            NUMBERED_GROUP: "各项原生编号标签进入时给一次短提示，口播继续。",
            LIVE_STRIP_GROUP: "每道斜切标签开始出现时给一次短提示，口播继续。",
            ROTATION_GROUP: "图卡首次聚焦时给一次短提示，口播继续。",
            JUDGMENT_GROUP: "按证据、勾叉和结论各自的原生动作绑定提示音。",
            LINE_GROUP: "线描手势入场时给一次原库提示音，口播继续。",
        }.get(
            beat.group_id,
            "原生画面运动开始时给一次短提示，口播继续。"
            if beat.group_id in PRESENTER_MOTION_GROUPS or beat.group_id in AZL_GROUPS
            else "原生文字动效入场时给一次短提示，口播继续。",
        ),
        source_start_seconds=source_start,
        trim_duration_seconds=length,
        target_peak_dbfs=peak,
    )


def _numbered_entry(
    package: Path,
    group: dict,
    beat: SemanticBeat,
    transcript: Transcript,
    cards: list[dict],
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group)
    images = project_image_digests(cards)
    presenters = {
        row["id"]
        for row in cards
        if row["kind"] == "original_video"
        and row["sha256"] == transcript.source_sha256
        and row["id"].startswith("source-")
    }
    config = read_json(inside(package, group["input_template"]))
    try:
        anchors = word_bindings(beat, transcript, contract, presenters | images.keys())
        text = {row["path"]: row for row in anchors["text"]}
        events = {row["path"]: row for row in anchors["events"]}
        media = {row["path"]: row["asset_id"] for row in anchors["media"]}
        if (
            beat.relation not in {"parallel", "sequence"}
            or len(beat.relation_items) != 3
            or set(text) != {*NUMBERED_LABELS, *NUMBERED_LINES}
            or set(events) != set(NUMBERED_EVENTS)
            or set(media) != {NUMBERED_PRESENTER, *NUMBERED_IMAGES}
            or set(media.values()) != set(beat.asset_ids)
            or media[NUMBERED_PRESENTER] not in presenters
            or len({images[media[path]] for path in NUMBERED_IMAGES}) != 3
        ):
            raise ValueError("Numbered tags need the current source and three images")
        for item, label, line, image, event in zip(
            beat.relation_items,
            NUMBERED_LABELS,
            NUMBERED_LINES,
            NUMBERED_IMAGES,
            NUMBERED_EVENTS,
            strict=True,
        ):
            line_tokens = text[line]["token_ids"]
            if (
                item.asset_ids != [media[image]]
                or set(item.native_text_paths) != {label, line}
                or item.native_media_paths != [image]
                or item.first_token_id != line_tokens[0]
                or item.last_token_id != line_tokens[-1]
                or not 1 <= len(text[label]["text"]) <= 2
                or events[event]["token_id"] != text[label]["token_ids"][0]
                or events[event]["edge"] != "start"
            ):
                raise ValueError("Each numbered label follows its own spoken item")
        starts = [events[path]["value"] for path in NUMBERED_EVENTS]
        clock = anchors["clock"]
        frames = round((clock["end_ms"] - clock["start_ms"]) * 30 / 1000)
        if not (
            0 <= starts[0] < starts[1] < starts[2]
            and all(
                start + item["enter"] <= (frames - 1) / 30
                for start, item in zip(starts, config["items"], strict=True)
            )
        ):
            raise ValueError("Leave time for the last numbered label to settle")
    except (KeyError, ValueError) as error:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_NUMBERED_INPUTS_REQUIRED",
            "编号标签需绑定同期原片、三份不同的项目图片和三个依次出现的实录短词。",
        ) from error
    slots = [*text, *events, *media]
    for path in slots:
        set_native_field(config, path, None)
    return NativeEpisodeEntry(
        carrier="picture",
        placement=NativePlacement(
            layer="overlay",
            rect=[0, 0, 1, 1],
            reason="原生编号和标签叠在同期口播画面上。",
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": NUMBERED_GROUP,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": "tengli-numbered-pictures-v1",
            "design_reason": "保留原编号、标签、配图及入场曲线，主画面使用连续口播。",
            "parameter_decisions": {
                key: "沿用原生画幅、标签构图及入场机制。" for key in config
            },
            "config": config,
            "placeholders": slots,
            "dependency_ids": list(AUTOMATIC_TEMPLATE_DEPENDENCIES[NUMBERED_GROUP]),
            "browser_live_background": True,
        },
    ), anchors


def _live_strip_entry(
    package: Path,
    group: dict,
    beat: SemanticBeat,
    transcript: Transcript,
    cards: list[dict],
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group)
    assets = {
        row["id"]: row
        for row in cards
        if row["kind"] == "original_video" and row["id"].startswith("source-")
    }
    try:
        anchors = word_bindings(beat, transcript, contract, set(assets))
        text = {row["path"]: row["token_ids"] for row in anchors["text"]}
        media = anchors["media"]
        if (
            beat.relation not in {"parallel", "sequence"}
            or len(beat.relation_items) != 3
            or set(text) != set(STRIP_TEXT)
            or len(media) != 1
            or media[0]["path"] != STRIP_IMAGE
            or beat.asset_ids != [media[0]["asset_id"]]
            or any(
                item.native_text_paths != [path]
                or item.asset_ids
                or item.native_media_paths
                or item.first_token_id != text[path][0]
                or item.last_token_id != text[path][-1]
                for item, path in zip(beat.relation_items, STRIP_TEXT, strict=True)
            )
        ):
            raise ValueError("Each original strip must correspond to a spoken item")
        anchors["media_clocks"] = [
            compile_flow_plate(anchors, assets, transcript, live_stage=True)
        ]
        compile_strips(package, group, anchors, assets, live_stage=True)
    except (KeyError, ValueError) as error:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_STRIP_INPUTS_REQUIRED",
            "斜切标签需绑定同期原片及三个按首词触发的实录短词，末项须留出入场时间。",
        ) from error
    config = read_json(inside(package, group["input_template"]))
    set_native_field(config, STRIP_IMAGE, None)
    return NativeEpisodeEntry(
        carrier="text",
        placement=NativePlacement(
            layer="overlay",
            rect=[0, 0, 1, 1],
            reason="原生斜切标签使用本期同期活动画面，主字幕单独排在下方。",
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": LIVE_STRIP_GROUP,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": "tengli-live-strip-story-v1",
            "design_reason": "按实录词点沿用原斜切、擦入、字体与大小，标签让出脸部。",
            "parameter_decisions": {"fonts": "沿用原思源宋体 Heavy。"},
            "config": config,
            "placeholders": [STRIP_IMAGE],
            "hypit_live_stage": True,
        },
    ), anchors


def _rotation_entry(
    package: Path,
    group: dict,
    beat: SemanticBeat,
    transcript: Transcript,
    asset_cards: list[dict],
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group)
    assets = {
        card["id"]: {
            "kind": card["kind"],
            "sha256": card["sha256"],
            **({"source": "project_upload"} if card["kind"] == "image" else {}),
        }
        for card in asset_cards
        if (card["kind"] == "image" and card["id"].startswith("material-"))
        or (card["kind"] == "original_video" and card["id"].startswith("source-"))
    }
    config = read_json(inside(package, group["input_template"]))
    try:
        anchors = word_bindings(beat, transcript, contract, set(assets))
        media = {row["path"]: row["asset_id"] for row in anchors["media"]}
        text = {row["path"]: row for row in anchors["text"]}
        events = {row["path"]: row for row in anchors["events"]}
        if (
            beat.relation != "parallel"
            or len(beat.relation_items) != 3
            or set(media.values()) != set(beat.asset_ids)
            or set(text) != set(ROTATION_LABELS)
            or set(events) != set(ROTATION_EVENTS)
            or any(
                item.asset_ids != [media.get(image_path)]
                or item.native_text_paths != [label_path]
                or item.native_media_paths != [image_path]
                or item.first_token_id != text[label_path]["token_ids"][0]
                or item.last_token_id != text[label_path]["token_ids"][-1]
                for item, label_path, image_path in zip(
                    beat.relation_items, ROTATION_LABELS, ROTATION_IMAGES, strict=True
                )
            )
        ):
            raise ValueError("Rotating cards must bind each spoken item to its image")
        source = rotation_source_clock(anchors, assets, transcript)
        config["duration"] = (
            source["source_end_ms"] - source["source_start_ms"]
        ) / 1000
        for path, row in text.items():
            set_native_field(config, path, row["text"])
        for path, row in events.items():
            set_native_field(config, path, row["value"])
        rotation_card_clock(config, anchors, assets)
    except ValueError as error:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_ROTATION_INPUTS_REQUIRED",
            "轮换图卡需绑定本期原片与三个各自配图的实录短词，首项开场，后两项留足切换时间。",
        ) from error
    slots = [*text, *events, *media]
    for path in slots:
        set_native_field(config, path, None)
    return NativeEpisodeEntry(
        carrier="picture",
        placement=NativePlacement(
            layer="scene", rect=[0, 0, 1, 1], reason="按原生暖色构图轮换同期图卡。"
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": ROTATION_GROUP,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": "tengli-rotation-cards-v1",
            "design_reason": "保留三张原卡的重叠位置和切换曲线，按本期词点轮换。",
            "parameter_decisions": {
                key: "沿用原生构图、画幅和卡片切换机制。" for key in config
            },
            "config": config,
            "placeholders": slots,
            "dependency_ids": list(AUTOMATIC_TEMPLATE_DEPENDENCIES[beat.group_id]),
        },
    ), anchors


def _judgment_entry(
    package: Path,
    group: dict,
    beat: SemanticBeat,
    transcript: Transcript,
    cards: list[dict],
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group, embedded_judgment_caption=False)
    images = project_image_digests(cards)
    presenters = {
        card["id"]
        for card in cards
        if card["kind"] == "original_video"
        and card["sha256"] == transcript.source_sha256
    }
    try:
        anchors = word_bindings(beat, transcript, contract, set(images) | presenters)
        text = {row["path"]: row for row in anchors["text"]}
        events = {row["path"]: row for row in anchors["events"]}
        media = {row["path"]: row["asset_id"] for row in anchors["media"]}
        if (
            beat.relation != "contrast"
            or len(beat.relation_items) != 2
            or set(text) != {*JUDGMENT_LABELS, JUDGMENT_CONCLUSION}
            or set(events) != set(JUDGMENT_EVENTS)
            or set(media) != {JUDGMENT_BACKGROUND, *JUDGMENT_IMAGES}
            or set(media.values()) != set(beat.asset_ids)
            or media[JUDGMENT_BACKGROUND] not in presenters
            or any(media[path] not in images for path in JUDGMENT_IMAGES)
            or images[media[JUDGMENT_IMAGES[0]]] == images[media[JUDGMENT_IMAGES[1]]]
        ):
            raise ValueError("W-R14 requires two distinct current comparison images")
        for item, label, image, event in zip(
            beat.relation_items,
            JUDGMENT_LABELS,
            JUDGMENT_IMAGES,
            JUDGMENT_EVENTS[2:4],
            strict=True,
        ):
            if (
                item.asset_ids != [media[image]]
                or item.native_text_paths != [label]
                or item.native_media_paths != [image]
                or events[event]["token_id"] not in text[label]["token_ids"]
            ):
                raise ValueError("Each judgment mark follows its recorded label")
        times = [events[path]["value"] for path in JUDGMENT_EVENTS]
        conclusion = text[JUDGMENT_CONCLUSION]
        clock = anchors["clock"]
        duration = (clock["end_ms"] - clock["start_ms"]) / 1000
        if (
            not 0
            < times[0]
            < times[1]
            < times[2]
            < times[3]
            < times[4]
            < times[5]
            < duration
            or not 1 <= len(conclusion["text"]) <= 8
            or events[JUDGMENT_EVENTS[4]]["token_id"] != conclusion["token_ids"][0]
            or events[JUDGMENT_EVENTS[4]]["edge"] != "start"
            or times[5] - times[4] < len(conclusion["text"]) / 8
        ):
            raise ValueError(
                "Preserve ordered comparison actions and conclusion reading time"
            )
    except (KeyError, ValueError) as error:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_JUDGMENT_INPUTS_REQUIRED",
            "证据判断需要同期原片、两份对应图片和按原顺序出现的勾叉及结论词点。",
        ) from error
    config = read_json(inside(package, group["input_template"]))
    config["content"]["captions"] = []
    config["media"]["background"]["end_policy"] = "error"
    slots = [
        *text,
        *events,
        *media,
        "/media/background/offset_seconds",
        "/media/background/duration_seconds",
    ]
    for path in slots:
        set_native_field(config, path, None)
    return NativeEpisodeEntry(
        carrier="picture",
        placement=NativePlacement(
            layer="scene",
            rect=[0, 0, 1, 1],
            reason="保留原勾叉判断整帧构图和同期动态底片。",
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": JUDGMENT_GROUP,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": "tengli-evidence-judgment-v1",
            "design_reason": "保留原判断标记、竖排字及遮罩退出，统一绘制主字幕。",
            "parameter_decisions": {
                key: "采用原生角色和几何，由本期实录驱动事件。" for key in config
            },
            "config": config,
            "placeholders": slots,
            "dependency_ids": list(AUTOMATIC_TEMPLATE_DEPENDENCIES[JUDGMENT_GROUP]),
            "media_clocks": [
                {
                    "media_path": JUDGMENT_BACKGROUND,
                    "policy": "transcript_source_window",
                }
            ],
        },
    ), anchors


def _line_entry(
    package: Path,
    group: dict,
    beat: SemanticBeat,
    transcript: Transcript,
    cards: list[dict],
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group, embedded_line_caption=False)
    images = project_image_digests(cards)
    presenters = {
        row["id"]
        for row in cards
        if row["kind"] == "original_video" and row["sha256"] == transcript.source_sha256
    }
    try:
        anchors = word_bindings(beat, transcript, contract, presenters | images.keys())
        text = {row["path"]: row for row in anchors["text"]}
        events = {row["path"]: row for row in anchors["events"]}
        media = {row["path"]: row["asset_id"] for row in anchors["media"]}
        art_paths = (LINE_PREVIOUS_PATH, LINE_DIRECTOR_PATH, LINE_HAND_PATH)
        if (
            beat.relation not in {"explanation", "sequence"}
            or set(text) != set(_LINE_LABELS)
            or set(events) != set(_LINE_EVENTS)
            or set(media) != {_OPENING_PRESENTER, *art_paths}
            or set(media.values()) != set(beat.asset_ids)
            or media[_OPENING_PRESENTER] not in presenters
            or len({images[media[path]] for path in art_paths}) != len(art_paths)
            or any(
                len(text[path]["text"]) > limit for path, limit in _LINE_LABELS.items()
            )
        ):
            raise ValueError(
                "Line scene needs the current source, three art roles and short labels"
            )
        for event, label in (
            (LINE_HAND_ENTRY, "/content/paper_text"),
            (_LINE_EVENTS[2], "/content/hand_label"),
        ):
            if (
                events[event]["token_id"] != text[label]["token_ids"][0]
                or events[event]["edge"] != "start"
            ):
                raise ValueError(
                    "Bind the hand and label reveals to their spoken words"
                )
        times = [events[path]["value"] for path in _LINE_EVENTS]
        clock = anchors["clock"]
        fps = clock["native_fps"]
        frames = [math.ceil(round(seconds * fps, 8)) for seconds in times]
        duration = (clock["end_ms"] - clock["start_ms"]) / 1000
        if frames != sorted(set(frames)) or times[-1] + 0.1 > duration:
            raise ValueError(
                "Line scene needs ordered visible actions and a settled live return"
            )
    except (KeyError, ValueError) as error:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_LINE_INPUTS_REQUIRED",
            "线描场景需要同期原片、三份对应图片和按顺序出现的实录词点。",
        ) from error
    config = line_template(
        read_json(inside(package, group["input_template"])), embedded_caption=False
    )
    slots = [
        *text,
        *events,
        *media,
        "/media/presenter/offset_seconds",
        "/media/presenter/duration_seconds",
    ]
    for path in slots:
        set_native_field(config, path, None)
    return NativeEpisodeEntry(
        carrier="text",
        placement=NativePlacement(
            layer="scene",
            rect=[0, 0, 1, 1],
            reason="沿用原线描画幅和人物回切路径。",
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": LINE_GROUP,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": "tengli-line-story-v1",
            "design_reason": "保留原线描、纸面和人物缩放路径，填入本期素材。",
            "parameter_decisions": {
                key: "沿用原线描构图与实录词点。" for key in config
            },
            "config": config,
            "placeholders": slots,
            "dependency_ids": list(AUTOMATIC_TEMPLATE_DEPENDENCIES[LINE_GROUP]),
            "media_clocks": [
                {"media_path": _OPENING_PRESENTER, "policy": "transcript_source_window"}
            ],
        },
    ), anchors


def _package_entry(
    package: Path,
    group: dict,
    beat: SemanticBeat,
    transcript: Transcript,
    cards: list[dict],
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group, live_package_presenter=True)
    images = project_image_digests(cards)
    presenters = {
        row["id"]
        for row in cards
        if row["kind"] == "original_video" and row["sha256"] == transcript.source_sha256
    }
    try:
        anchors = word_bindings(beat, transcript, contract, presenters | images.keys())
        text = {row["path"]: row for row in anchors["text"]}
        events = {row["path"]: row for row in anchors["events"]}
        media = {row["path"]: row["asset_id"] for row in anchors["media"]}
        if (
            beat.relation not in {"parallel", "explanation"}
            or len(beat.relation_items) != 4
            or set(text) != set(_PACKAGE_LABELS)
            or set(events) != set(_PACKAGE_EVENTS)
            or set(media) != {_OPENING_PRESENTER, *_PACKAGE_IMAGES}
            or set(media.values()) != set(beat.asset_ids)
            or media[_OPENING_PRESENTER] not in presenters
            or len({images[media[path]] for path in _PACKAGE_IMAGES}) != 4
        ):
            raise ValueError(
                "Z-M12 needs the current presenter and four distinct images"
            )
        for item, label, image, event in zip(
            beat.relation_items,
            _PACKAGE_LABELS,
            _PACKAGE_IMAGES,
            _PACKAGE_EVENTS,
            strict=True,
        ):
            if (
                item.asset_ids != [media[image]]
                or item.native_text_paths != [label]
                or item.native_media_paths != [image]
                or events[event]["token_id"] != text[label]["token_ids"][0]
                or events[event]["edge"] != "start"
            ):
                raise ValueError("Each package image follows its own spoken label")
        times = [events[path]["value"] for path in _PACKAGE_EVENTS]
        clock = anchors["clock"]
        duration = (clock["end_ms"] - clock["start_ms"]) / 1000
        if not 0 <= times[0] < times[1] < times[2] < times[3] <= duration - 0.4:
            raise ValueError(
                "Leave time for the final original package entry to settle"
            )
    except (KeyError, ValueError) as error:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_PACKAGE_INPUTS_REQUIRED",
            "纸面规格需要同期原片、四份不同项目图片和按顺序出现的四个实录标签。",
        ) from error
    config = live_package_template(read_json(inside(package, group["input_template"])))
    if beat.relation == "explanation":
        config["intent"]["relation"] = "example"
    slots = [
        *text,
        *events,
        *media,
        _PACKAGE_EXTRA,
        "/media/presenter/offset_seconds",
        "/media/presenter/duration_seconds",
    ]
    for path in slots:
        set_native_field(config, path, None)
    return NativeEpisodeEntry(
        carrier="picture",
        placement=NativePlacement(
            layer="scene",
            rect=[0, 0, 1, 1],
            reason="保留原全幅纸面构图和同期讲述者圆窗。",
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": PACKAGE_GROUP,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": "tengli-package-specs-v1",
            "design_reason": "保留原纸面造型和入场曲线，以本期实录和素材填充。",
            "parameter_decisions": {
                key: "使用原纸面模板与本期素材。" for key in config
            },
            "config": config,
            "placeholders": slots,
            "empty_text": {_PACKAGE_EXTRA: "原生可选补充字由统一主字幕承载。"},
            "media_clocks": [
                {"media_path": _OPENING_PRESENTER, "policy": "transcript_source_window"}
            ],
        },
    ), anchors


def _azl_entry(
    package: Path,
    group: dict,
    beat: SemanticBeat,
    transcript: Transcript,
    asset_cards: list[dict],
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group)
    config = read_json(inside(package, group["input_template"]))
    presenter_ids = {
        row["id"]
        for row in asset_cards
        if row["kind"] == "original_video" and row["sha256"] == transcript.source_sha256
    }
    media_paths = (AZL_PRESENTER, *azl_slots(beat.group_id))
    try:
        available = azl_materials(asset_cards, transcript.source_sha256, 1)
        anchors = word_bindings(
            beat, transcript, contract, presenter_ids | available.keys()
        )
        bound = {row["path"]: row["asset_id"] for row in anchors["media"]}
        if (
            set(bound) != set(media_paths)
            or bound[AZL_PRESENTER] not in presenter_ids
            or set(beat.asset_ids) != set(bound.values())
            or {row["path"] for row in anchors["text"]} != set(contract["text_paths"])
        ):
            raise ValueError("Original panel requires its exact text and media slots")
        clock = anchors["clock"]
        frames = math.ceil((clock["end_ms"] - clock["start_ms"]) * 30 / 1000)
        available = azl_materials(asset_cards, transcript.source_sha256, frames)
        if (
            len({available[bound[path]]["sha256"] for path in media_paths[1:]})
            != len(media_paths) - 1
        ):
            raise ValueError("Original panel needs distinct current project materials")
        validate_azl_anchors(
            beat.group_id,
            anchors,
            config["capacity"],
            {token.id: i for i, token in enumerate(transcript.tokens)},
        )
    except (ValueError, KeyError) as error:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_AZL_INPUTS_REQUIRED",
            f"{beat.group_id} 需绑定同期原片、实录短句及四个字幕词点。"
            "各素材槽需不同的本期原件，补充视频须覆盖整段。",
        ) from error
    slots = [
        *media_paths,
        *(row["path"] for row in anchors["text"]),
        *(row["path"] for row in anchors["events"]),
        *(
            field["path"]
            for field in contract["fields"]
            if field["category"] == "clock_owned_by_compiler"
            and field["path"].startswith("/media/")
        ),
    ]
    for path in slots:
        set_native_field(config, path, None)
    for media in config["media"].values():
        media["end_policy"] = "error"
    reason = "上方完整保留原生二比三板式，底部留给连续主字幕。"
    return NativeEpisodeEntry(
        carrier="text",
        placement=NativePlacement(layer="scene", rect=list(AZL_RECT), reason=reason),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": beat.group_id,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": AZL_DESIGN_ID,
            "design_reason": reason,
            "parameter_decisions": {key: reason for key in config},
            "config": config,
            "placeholders": slots,
            "dependency_ids": list(AUTOMATIC_TEMPLATE_DEPENDENCIES[beat.group_id]),
            "media_clocks": [
                {
                    "media_path": path,
                    "policy": "transcript_source_window"
                    if path == AZL_PRESENTER
                    else "project_scene_clip_window",
                }
                for path in media_paths
            ],
        },
    ), anchors


def _presenter_motion_entry(
    package: Path,
    group: dict,
    beat: SemanticBeat,
    transcript: Transcript,
    asset_cards: list[dict],
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group)
    config = read_json(inside(package, group["input_template"]))
    presenter_ids = {
        row["id"]
        for row in asset_cards
        if row["kind"] == "original_video" and row["sha256"] == transcript.source_sha256
    }
    clips = motion_project_clips(asset_cards, transcript.source_sha256)
    media_paths = (
        (MOTION_PRESENTER, *MOTION_CLIPS)
        if beat.group_id == "YYP05"
        else (MOTION_PRESENTER,)
    )
    try:
        anchors = word_bindings(
            beat, transcript, contract, presenter_ids | clips.keys()
        )
        bound = {row["path"]: row["asset_id"] for row in anchors["media"]}
        if (
            set(bound) != set(media_paths)
            or bound[MOTION_PRESENTER] not in presenter_ids
            or set(beat.asset_ids) != set(bound.values())
            or any(bound[path] not in clips for path in media_paths[1:])
        ):
            raise ValueError("Original camera motion needs current sources per slot")
        validate_motion_anchors(beat.group_id, anchors, config, clips)
    except (KeyError, ValueError) as error:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_PRESENTER_MOTION_INPUTS_REQUIRED",
            f"{beat.group_id} 需绑定同期原片和原动作对应的实录词点。"
            "双素材镜头需两段独立且足够长的本期视频。",
        ) from error
    slots = [
        MOTION_CAPTION,
        *media_paths,
        *(row["path"] for row in anchors["events"]),
        *(
            field["path"]
            for field in contract["fields"]
            if field["category"] == "clock_owned_by_compiler"
            and field["path"].startswith("/media/")
        ),
    ]
    for path in slots:
        set_native_field(config, path, None)
    if beat.group_id in {"YYP01", "YYP02", "YYP06"}:
        config["events"]["shift_frames"] = 0
    config["media"]["presenter"]["end_policy"] = "error"
    reason = "沿用原人物构图与动作，主字幕和原声在整片时钟上持续。"
    return NativeEpisodeEntry(
        carrier="text",
        placement=NativePlacement(layer="scene", rect=[0, 0, 1, 1], reason=reason),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": beat.group_id,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": "tengli-presenter-reframing-v1",
            "design_reason": reason,
            "parameter_decisions": {key: reason for key in config},
            "config": config,
            "placeholders": slots,
            "empty_text": {MOTION_CAPTION: "原 episode 的主字幕承载完整实录。"},
            "dependency_ids": list(AUTOMATIC_TEMPLATE_DEPENDENCIES[beat.group_id]),
            "media_clocks": [
                {
                    "media_path": path,
                    "policy": "transcript_source_window"
                    if path == MOTION_PRESENTER
                    else "project_clip_from_start",
                }
                for path in media_paths
            ],
        },
    ), anchors


def _opening_entry(
    package: Path,
    group: dict,
    beat: SemanticBeat,
    transcript: Transcript,
    asset_cards: list[dict],
) -> tuple[NativeEpisodeEntry, dict[str, Any]]:
    contract = input_contract(package, group)
    config = read_json(inside(package, group["input_template"]))
    presenter_ids = {
        row["id"]
        for row in asset_cards
        if row["kind"] == "original_video" and row["sha256"] == transcript.source_sha256
    }
    yy_opening = beat.group_id in YY_OPENING_EXPANDED_GROUPS
    try:
        anchors = word_bindings(beat, transcript, contract, presenter_ids)
        (presenter,) = anchors["media"]
        text = {row["path"]: row for row in anchors["text"]}
        events = {row["path"]: row for row in anchors["events"]}
        clock = anchors["clock"]
        frames = math.ceil(
            (clock["end_ms"] - clock["start_ms"]) / 1000 * clock["native_fps"]
        )
        if (
            presenter["path"] != _OPENING_PRESENTER
            or beat.asset_ids != [presenter["asset_id"]]
            or set(text) != set(contract["text_paths"])
            or set(events) != {row["path"] for row in contract["event_paths"]}
        ):
            raise ValueError("Missing current source, text or measured opening event")
        if yy_opening:
            if (
                events[YY_OPENING_SOURCE_EVENTS[beat.group_id]]["token_id"]
                != beat.first_token_id
            ):
                raise ValueError(
                    "The original picture entry needs this beat's first word"
                )
            validate_yy_opening(beat.group_id, anchors, frames, transcript)
        else:
            for path, row in text.items():
                event_path, capacity = _OPENING_ROLES[path]
                event = events[event_path]
                reading_frames = max(
                    6, math.ceil(len(row["text"]) * clock["native_fps"] / 8)
                )
                if (
                    not 1 <= len(row["text"]) <= capacity
                    or "\n" in row["text"]
                    or event["token_id"] != row["token_ids"][0]
                    or event["edge"] != "start"
                    or event["value"] + reading_frames > frames
                ):
                    raise ValueError(
                        "Opening text needs capacity, its first word and time"
                    )
            if beat.group_id == "LYO02" and not (
                events["/style/geometry/mask_start_frame"]["value"]
                < events["/style/geometry/mask_end_frame"]["value"]
                < events["/events/text_frame"]["value"]
            ):
                raise ValueError("Opening round window must settle before its theme")
            if beat.group_id == "LYO03" and (
                events["/events/title_frame"]["value"] + 10
                > events["/events/subtitle_frame"]["value"]
            ):
                raise ValueError(
                    "Opening title must finish its slide before the subtitle"
                )
    except ValueError as error:
        raise ApiError(
            422,
            "EDITING_TEMPLATE_OPENING_INPUTS_REQUIRED",
            f"{beat.group_id} 需绑定同期原片、各项实录文字和词点，"
            "并留出入场及阅读时间。",
        ) from error

    slots = [
        *text,
        *events,
        _OPENING_PRESENTER,
        *(
            field["path"]
            for field in contract["fields"]
            if field["category"] == "clock_owned_by_compiler"
            and field["path"].startswith("/media/")
        ),
    ]
    for path in slots:
        set_native_field(config, path, None)
    if not yy_opening:
        config["events"]["shift_frames"] = 0
    config["media"]["presenter"]["end_policy"] = "error"
    return NativeEpisodeEntry(
        carrier="text",
        placement=NativePlacement(
            layer="scene", rect=[0, 0, 1, 1], reason="按原景别播放同期口播人物。"
        ),
        recipe={
            "version": "tengli.native-recipe/1",
            "release": MOTION_SHA256,
            "group_id": beat.group_id,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "design_id": (
                "tengli-yy-presenter-openings-v1"
                if yy_opening
                else "tengli-presenter-openings-v1"
            ),
            "design_reason": "沿用原景别、字型与轨迹，绑定当前人物和实录文字。",
            "parameter_decisions": {
                key: "沿用原生构图，人物时钟与文字按本期实录编译。" for key in config
            },
            "config": config,
            "placeholders": slots,
            "dependency_ids": list(AUTOMATIC_TEMPLATE_DEPENDENCIES[beat.group_id]),
            "media_clocks": [
                {"media_path": _OPENING_PRESENTER, "policy": "transcript_source_window"}
            ],
        },
    ), anchors


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
        paths: tuple[str | None, ...]
        if beat.group_id == CARD_GROUP:
            entries[beat.id], anchors = _card_entry(
                package,
                group,
                beat,
                transcript,
                asset_cards or [],
                live_background=template["id"] == PICTURE_TEMPLATE_ID,
            )
            paths = _CARD_ENTRY_PATHS
        elif beat.group_id == ROTATION_GROUP:
            entries[beat.id], anchors = _rotation_entry(
                package, group, beat, transcript, asset_cards or []
            )
            paths = ROTATION_EVENTS
        elif beat.group_id == NUMBERED_GROUP:
            entries[beat.id], anchors = _numbered_entry(
                package, group, beat, transcript, asset_cards or []
            )
            paths = NUMBERED_EVENTS
        elif beat.group_id == LIVE_STRIP_GROUP:
            entries[beat.id], anchors = _live_strip_entry(
                package, group, beat, transcript, asset_cards or []
            )
            paths = STRIP_EVENTS
        elif beat.group_id == JUDGMENT_GROUP:
            entries[beat.id], anchors = _judgment_entry(
                package, group, beat, transcript, asset_cards or []
            )
            paths = JUDGMENT_EVENTS[:5]
        elif beat.group_id == PACKAGE_GROUP:
            entries[beat.id], anchors = _package_entry(
                package, group, beat, transcript, asset_cards or []
            )
            paths = _PACKAGE_EVENTS
        elif beat.group_id == LINE_GROUP:
            entries[beat.id], anchors = _line_entry(
                package, group, beat, transcript, asset_cards or []
            )
            paths = (None,)
        elif beat.group_id == QUESTION_CARD_GROUP:
            entries[beat.id], anchors = _question_card_entry(
                package, group, beat, transcript
            )
            paths = (None,)
        elif beat.group_id in OPENING_GROUPS:
            entries[beat.id], anchors = _opening_entry(
                package, group, beat, transcript, asset_cards or []
            )
            paths = (None,)
        elif beat.group_id in PRESENTER_MOTION_GROUPS:
            entries[beat.id], anchors = _presenter_motion_entry(
                package, group, beat, transcript, asset_cards or []
            )
            paths = motion_sound_paths(beat.group_id)
        elif beat.group_id in AZL_GROUPS:
            entries[beat.id], anchors = _azl_entry(
                package, group, beat, transcript, asset_cards or []
            )
            paths = (None,)
        else:
            make_entry = _question_entry if beat.group_id == QUESTION_GROUP else _entry
            entries[beat.id], anchors = make_entry(package, group, beat, transcript)
            paths = (None,)
        cues.extend(
            _entry_sound(beat, anchors, transcript.duration_ms, avoided, path)
            for path in paths
        )
    has_scene = any(entry.placement.layer == "scene" for entry in entries.values())
    has_bottom_caption_lane = any(
        beat.group_id
        in {
            ROTATION_GROUP,
            JUDGMENT_GROUP,
            NUMBERED_GROUP,
            LIVE_STRIP_GROUP,
            *YY_OPENING_EXPANDED_GROUPS,
            *PRESENTER_MOTION_GROUPS,
            *AZL_GROUPS,
        }
        for beat in beats
    )
    has_lower_caption_lane = any(
        beat.group_id in {PACKAGE_GROUP, LINE_GROUP} for beat in beats
    )
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
            "subtitle_safe_rect": [
                0.055,
                0.255,
                0.89,
                0.735
                if has_bottom_caption_lane
                else 0.705
                if has_lower_caption_lane
                else 0.625,
            ],
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
