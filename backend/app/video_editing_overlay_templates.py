"""Versioned composition slots built from the preserved Motion catalog."""

from copy import deepcopy

from .video_editing_browser_rotation import ROTATION_GROUP
from .video_editing_contracts import SemanticPlan

MIN_OVERLAY_TYPES = 5
PREFERRED_OVERLAY_TYPES = 10
LEGACY_PICTURE_TEMPLATE_ID = "picture-compare-v1"
PICTURE_TEMPLATE_ID = "picture-compare-v2"
ROTATION_TEMPLATE_ID = "rotation-cards-v1"
_SHARED_SLOTS = [
    {"group_id": "SG-S09", "purpose": "分别表达单件规格和到手总量"},
    {"group_id": "SG-S03", "purpose": "强调真实的使用时长或体验短句"},
    {"group_id": "AH-S05", "purpose": "突出优惠条件和结论"},
    {"group_id": "JJ-S01", "purpose": "区分来源与对应说明"},
    {"group_id": "SG-S02", "purpose": "标注条款或标准的上下文"},
    {"group_id": "SG-S06", "purpose": "分两层呈现成分或功能短语"},
    {"group_id": "BG-S04", "purpose": "突出并列用途中的关键词"},
]
_FRONT_LAYER = {"group_id": "SG-S10", "purpose": "保留下单条件或行动条件"}
_ROLL_SLOTS = [
    {"group_id": "BG-S06", "purpose": "用两层滚动字幕表达报价及到手件数"},
    {"group_id": "AHG-S02", "purpose": "区分先前的实际购买经历"},
    *_SHARED_SLOTS,
]
_QUESTION_SLOT = {
    "group_id": "W-R18",
    "purpose": "实际追问可短暂整帧虚化，随后回到同期原片",
    "layer": "scene",
    "native_branch": "question",
    "binding": (
        "选择完整追问段，将 question_in 锚定该段首词。"
        "用 question 和 dissolve_in 标记实录标题和溶解词点。"
        "presenter 与 question_background 都绑定同一原片素材 ID。"
        "主字幕由网站统一生成。"
    ),
}
_ACTION_SLOT = {"group_id": "AH-S09", "purpose": "分开显示下单前提与对应行动"}
_TEMPLATES = {
    "label-compare-v1": {
        "id": "label-compare-v1",
        "name": "价签与规格对照",
        "slots": [
            {"group_id": "AHG-S02", "purpose": "标注本期真实口播里的报价"},
            {"group_id": "JJ-S03", "purpose": "标出价格或关键结论"},
            {"group_id": "AH-S09", "purpose": "分开呈现主张和补充信息"},
            *_SHARED_SLOTS,
            _FRONT_LAYER,
        ],
    },
    "roll-compare-v1": {
        "id": "roll-compare-v1",
        "name": "滚动报价与规格对照",
        "slots": [*_ROLL_SLOTS, _FRONT_LAYER],
    },
    "question-story-v1": {
        "id": "question-story-v1",
        "name": "整帧追问与口播重点",
        "slots": [_QUESTION_SLOT, *_ROLL_SLOTS, _ACTION_SLOT],
    },
    "roll-compare-v2": {
        "id": "roll-compare-v2",
        "name": "滚动报价与规格对照",
        "slots": [*_ROLL_SLOTS, _ACTION_SLOT],
    },
    ROTATION_TEMPLATE_ID: {
        "id": ROTATION_TEMPLATE_ID,
        "name": "三图轮换与口播重点",
        "slots": [
            {
                "group_id": ROTATION_GROUP,
                "purpose": "保留同期人物，围绕三个并列事项逐张轮换图卡焦点",
                "layer": "scene",
                "binding": (
                    "仅在有三个并列事项及三张对应项目图时使用。"
                    "presenter 使用本期原片 source 素材，原生暖色背景固定。"
                    "首项首词开始该段，三项各用短标签和自己的首词锚定 at。"
                    "relation_items 按顺序绑定各项标签和图片，不共用素材。"
                    "在第三项之后给切换留出实录阅读区间。"
                ),
            },
            _QUESTION_SLOT,
            *_ROLL_SLOTS,
            _ACTION_SLOT,
        ],
    },
    LEGACY_PICTURE_TEMPLATE_ID: {
        "id": LEGACY_PICTURE_TEMPLATE_ID,
        "name": "三图卡与口播重点",
        "slots": [
            {
                "group_id": "CX-G07",
                "purpose": "在整帧画面依次展示与口播对应的三张项目图片",
                "layer": "scene",
                "binding": (
                    "只在本段有三个并列项目和对应图片时使用。"
                    "background 绑定已选背景图，三个 cards 各用不同图片。"
                    "同一卡的 food 和 city 槽绑定相同的实录标签和图片。"
                    "前三个动作锚定各卡标签首词，最后一项落稳使用后续实录词点。"
                    "relation_items 逐卡列出两套槽对应的词范围和素材。"
                ),
            },
            _QUESTION_SLOT,
            *_ROLL_SLOTS,
            _ACTION_SLOT,
        ],
    },
}

_TEMPLATES[PICTURE_TEMPLATE_ID] = {
    "id": PICTURE_TEMPLATE_ID,
    "name": "三图卡与口播重点",
    "slots": [
        {
            "group_id": "CX-G07",
            "purpose": "保持同期人物口播，依次叠加对应三个并列事项的图卡",
            "layer": "overlay",
            "binding": (
                "background 绑定本期原片 source 素材，人物随同期画面继续口播。"
                "每张卡使用一张与标签内容对应的本期项目图片。"
                "素材描述应支持这一对应关系，通用人物头像不能代替场景图。"
                "没有合适的三张图片时跳过该槽。"
                "同一卡的 food 和 city 槽绑定相同的实录标签和图片。"
                "前三个动作锚定各卡标签首词，最后一项落稳使用后续实录词点。"
                "relation_items 逐卡列出两套槽对应的词范围和素材。"
            ),
        },
        _QUESTION_SLOT,
        *_ROLL_SLOTS,
        _ACTION_SLOT,
    ],
}


def overlay_templates() -> list[dict]:
    return [
        overlay_template(key)
        for key in (
            "label-compare-v1",
            "roll-compare-v2",
            "question-story-v1",
            PICTURE_TEMPLATE_ID,
            ROTATION_TEMPLATE_ID,
        )
    ]


def overlay_template(template_id: str) -> dict:
    if template_id not in _TEMPLATES:
        raise ValueError("Unknown original overlay composition template")
    return deepcopy(_TEMPLATES[template_id])


def validate_template_plan(
    plan: SemanticPlan, template: dict, *, complete: bool
) -> None:
    if template != overlay_template(template["id"]):
        raise ValueError("Overlay template version or slots changed")
    groups = {slot["group_id"] for slot in template["slots"]}
    chosen = {beat.group_id for beat in plan.beats if beat.group_id != "Z-M00"}
    if not chosen <= groups or (complete and len(chosen) < MIN_OVERLAY_TYPES):
        raise ValueError(
            "Selected native groups do not match the chosen overlay template"
        )
