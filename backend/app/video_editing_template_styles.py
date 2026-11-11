"""Product styles beside frozen engine templates; only new prepares opt in.

A template's distinctive scene is a requirement, not a suggestion that can be
silently replaced by shared subtitles. Historical captures have no style policy.
"""

from copy import deepcopy

from .video_editing_contracts import SemanticPlan, SemanticRelationItem, Transcript

STYLE_POLICY_VERSION = "tengli.template-style/1"
TEXT_RELATION_ADAPTER = "tengli.native-text-relations/1"


def _style(
    name: str,
    category: str,
    signature: str,
    flow: str,
    requirements: str,
    mode: str = "speech",
    topic: str = "overview",
) -> dict:
    return {
        "name": name,
        "category": category,
        "signature_group_ids": signature.split(),
        "visual_features": flow.split(" / "),
        "description": " → ".join(flow.split(" / "))
        + "。保留同期口播，用本套招牌画面组织信息。",
        "material_requirements": [
            "9:16 竖屏口播，建议无内嵌字幕",
            *requirements.split(" / "),
        ],
        "material_mode": mode,
        "demo_topic": topic,
    }


STYLES = {
    "product-explainer-v1": _style(
        "产品讲解",
        "产品展示",
        "CX-G01 CX-G02",
        "人物钩子 / 横竖分屏 / 手机图卡",
        "建议 3 张不同的商品或界面图",
        "images",
    ),
    "knowledge-talk-v1": _style(
        "知识口播",
        "观点叙事",
        "Z-M03 Z-M13",
        "整帧追问 / 分层论点 / 黑白资料板",
        "无需补充图片，按实录保留完整条件",
    ),
    "presenter-openings-v1": _style(
        "人物亮相",
        "人物场景",
        "LYO01 LYO02 LYO03 LYO04",
        "人物开场 / 原生标题 / 重点接棒",
        "干净口播与适合开场的完整信息点",
    ),
    "rotation-cards-v1": _style(
        "三图轮换",
        "图卡资料",
        "CX-G04",
        "纵深图卡 / 逐张轮换 / 口播结论",
        "3 张不同的本期图片；实录有对应的三个信息点",
        "images",
        "three-goals",
    ),
    "azl-panels-v1": _style(
        "杂志多格",
        "图卡资料",
        "AZL01 AZL02 AZL03 AZL04 AZL05 AZL06 AZL07",
        "人物图文多格 / 素材换位 / 标题卡收口",
        "无内嵌字幕原片，按板式需 1–3 份本期图片或短视频",
        "images",
        "three-goals",
    ),
    "unified-chapter-v1": _style(
        "章节导航",
        "实景教程",
        "Z-M15",
        "目录建立 / 章节切换 / 全文回顾",
        "实录有清晰章节，标题与章节边界均绑定原词",
        topic="four-goals",
    ),
    "unified-paper-typewriter-v1": _style(
        "方格纸打字",
        "文字动效",
        "Z-M11",
        "方格纸铺开 / 逐字说明 / 同期人物",
        "无内嵌字幕原片及可用原抠像模型；说明短语需有阅读时间",
        topic="replica",
    ),
    "chenxi-broll-v1": _style(
        "操作实景",
        "实景教程",
        "CXBR01 CXBR02 CXBR03 CXBR04 CXBR05",
        "真实操作 / 人物圆窗 / 纸条说明",
        "已分好步骤且覆盖使用段的短录屏；部分板式另需纸纹底图 / "
        "长录屏自动找操作起止尚未接入",
        "clips",
        "workflow",
    ),
}

# Product choices are deliberately smaller than the engine combination catalog.
PUBLIC_TEMPLATE_IDS = tuple(STYLES)
FEATURED = set(PUBLIC_TEMPLATE_IDS)


def style_policy(template: dict | None) -> dict | None:
    if (
        not template
        or template["id"] not in STYLES
        or template["id"] in {"product-explainer-v1", "knowledge-talk-v1"}
    ):
        return None
    profile = STYLES[template["id"]]
    return {
        "version": STYLE_POLICY_VERSION,
        "template_id": template["id"],
        "name": profile["name"],
        "signature_group_ids": deepcopy(profile["signature_group_ids"]),
        "narrative": deepcopy(profile["visual_features"]),
        "minimum_signature_occurrences": 1,
        "catalog_scope": "template_members",
        "measured_word_clock": True,
        "native_role_capacities": True,
    }


def style_candidate_ids(
    template: dict | None, runtime: dict | None, choices: dict | None
) -> set[str] | None:
    policy = (runtime or {}).get("template_style", {})
    if not template or policy.get("catalog_scope") != "template_members":
        return None
    unavailable = set((runtime or {}).get("unavailable_template_groups", {}))
    unavailable.update(
        note["target_id"]
        for note in (choices or {}).get("notes", [])
        if note["target_kind"] == "group" and note["choice"] == "avoid"
    )
    return ({slot["group_id"] for slot in template["slots"]} - unavailable) | {"Z-M00"}


def style_blockers(snapshot: dict) -> list[str]:
    policy = (snapshot.get("planning_runtime") or {}).get("template_style")
    if not policy:
        return []
    unavailable = set(snapshot["planning_runtime"]["unavailable_template_groups"])
    unavailable.update(
        note["target_id"]
        for note in snapshot["choice_snapshot"]["notes"]
        if note["target_kind"] == "group" and note["choice"] == "avoid"
    )
    if set(policy["signature_group_ids"]) <= unavailable:
        return [
            f"{policy['name']}的招牌画面条件未满足，请补齐素材、原件或调整避用设置后重新准备。"
        ]
    return []


def validate_template_style(plan: SemanticPlan, runtime: dict | None) -> None:
    policy = (runtime or {}).get("template_style")
    if not policy:
        return
    if policy["version"] != STYLE_POLICY_VERSION:
        raise ValueError("Unknown template style policy")
    signature = set(policy["signature_group_ids"])
    if (
        sum(beat.group_id in signature for beat in plan.beats)
        < policy["minimum_signature_occurrences"]
    ):
        raise ValueError(
            f"{policy['name']}缺少本套招牌动效，不能以通用字幕替代本款风格"
        )


def adapt_style_text_relations(
    plan: SemanticPlan, transcript: Transcript, runtime: dict | None
) -> tuple[SemanticPlan, dict | None]:
    """Project redundant text-only annotations onto their actual native slots.

    These three native groups show complete title/detail phrases. A model may
    describe several subphrases inside one detail slot. The strict compiled
    contract instead needs one membership item per displayed slot. This adapter
    changes only redundant relation metadata; never group choices, words, timing,
    images, conditions, native fields or parallel/contrast relations. The raw
    response is retained, and the receipt explicitly records every adapted beat.
    """
    if not (runtime or {}).get("template_style"):
        return plan, None
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    result = plan.model_copy(deep=True)
    changed = []
    for beat in result.beats:
        if (
            beat.group_id not in {"JJ-S01", "AH-S05", "AH-S09"}
            or beat.relation not in {"explanation", "condition", "sequence"}
            or not beat.relation_items
            or beat.asset_ids
            or beat.native_media
        ):
            continue
        anchors = {anchor.path: anchor for anchor in beat.native_text}
        referenced = []
        admissible = True
        for item in beat.relation_items:
            if (
                item.asset_ids
                or item.native_media_paths
                or len(item.native_text_paths) != 1
            ):
                admissible = False
                break
            path = item.native_text_paths[0]
            anchor = anchors.get(path)
            if (
                anchor is None
                or any(
                    key not in positions
                    for key in (
                        item.first_token_id,
                        item.last_token_id,
                        anchor.first_token_id,
                        anchor.last_token_id,
                    )
                )
                or not positions[anchor.first_token_id]
                <= positions[item.first_token_id]
                <= positions[item.last_token_id]
                <= positions[anchor.last_token_id]
            ):
                admissible = False
                break
            referenced.append(path)
        if not admissible:
            continue  # The original validator will reject an invented binding.
        if len(set(referenced)) == len(referenced) and all(
            item.first_token_id == anchors[item.native_text_paths[0]].first_token_id
            and item.last_token_id == anchors[item.native_text_paths[0]].last_token_id
            for item in beat.relation_items
        ):
            continue
        selected = sorted(
            set(referenced), key=lambda path: positions[anchors[path].first_token_id]
        )
        beat.relation_items = [
            SemanticRelationItem(
                id=f"native-slot-{i + 1}",
                first_token_id=anchors[path].first_token_id,
                last_token_id=anchors[path].last_token_id,
                native_text_paths=[path],
            )
            for i, path in enumerate(selected)
        ]
        changed.append(beat.id)
    if not changed:
        return plan, None
    return result, {
        "version": TEXT_RELATION_ADAPTER,
        "beat_ids": changed,
        "visual_fields_changed": False,
        "review": "slot_metadata_adapted_not_unmodified_first_pass",
    }
