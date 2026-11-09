"""Versioned composition slots built from the preserved Motion catalog."""

from copy import deepcopy

from .video_editing_contracts import SemanticPlan

MIN_OVERLAY_TYPES = 5
PREFERRED_OVERLAY_TYPES = 10
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
        "slots": [
            {
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
            },
            *_ROLL_SLOTS,
            {"group_id": "AH-S09", "purpose": "分开显示下单前提与对应行动"},
        ],
    },
    "roll-compare-v2": {
        "id": "roll-compare-v2",
        "name": "滚动报价与规格对照",
        "slots": [
            *_ROLL_SLOTS,
            {"group_id": "AH-S09", "purpose": "分开显示下单前提与对应行动"},
        ],
    },
}


def overlay_templates() -> list[dict]:
    return [
        overlay_template(key)
        for key in ("label-compare-v1", "roll-compare-v2", "question-story-v1")
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
