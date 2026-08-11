from __future__ import annotations

import re
from typing import Iterable, List

from .state import HarnessError


FORBIDDEN_PIXEL_PATTERNS = (
    (re.compile(r"\bM\d{2,}\b", re.IGNORECASE), "internal module identifier"),
    (re.compile(r"上一屏|下一屏|页面职责|买家问题|主结论|承接|引向"), "workflow navigation"),
    (re.compile(r"构图家族|证据等级|文字模式|Logo策略|模块编号|页码|屏号"), "internal planning label"),
)


def prompt_preflight(prompt: str) -> None:
    """Fail closed when internal planning language could be rendered into pixels."""
    hits = []
    for pattern, label in FORBIDDEN_PIXEL_PATTERNS:
        if pattern.search(prompt):
            hits.append(label)
    if hits:
        raise HarnessError("Compiled image prompt leaks internal metadata: " + ", ".join(sorted(set(hits))))


def _clean(value: object) -> str:
    text = str(value or "").strip()
    for pattern, _label in FORBIDDEN_PIXEL_PATTERNS:
        text = pattern.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" ；，。:-")


def _clean_many(values: Iterable[object]) -> List[str]:
    return [item for item in (_clean(value) for value in values) if item]


def _dedupe(values: Iterable[object]) -> List[str]:
    result: List[str] = []
    for item in _clean_many(values):
        if item not in result:
            result.append(item)
    return result


def _joined(values: Iterable[object], empty: str = "无") -> str:
    cleaned = _clean_many(values)
    return "；".join(cleaned) if cleaned else empty


def _copy_instruction(visible_copy: list) -> str:
    if not visible_copy:
        return "画面不放宣传文字，只保留产品包装上真实存在的印刷信息。"
    lines = []
    for item in visible_copy:
        text = _clean(item.get("text"))
        role = _clean(item.get("role"))
        anchor = _clean(item.get("anchor"))
        if text:
            lines.append("文字“{}”{}{}".format(
                text,
                "，承担" + role if role else "",
                "，贴合" + anchor if anchor else "",
            ))
    if not lines:
        return "画面不放宣传文字，只保留产品包装上真实存在的印刷信息。"
    return "仅允许出现以下宣传文字：\n" + "\n".join("- " + line for line in lines)


def compile_prompt(session: dict, module: dict, repair: bool = False) -> str:
    """Compile a pixel-facing brief, never a planning transcript.

    Internal IDs, workflow transitions, enum labels and raw user feedback deliberately
    stay in the request envelope and never enter the image model prompt.
    """
    facts = {item["id"]: item for item in session["input"].get("verified_facts", [])}
    plan = module["plan"]
    fact_ids = [plan["lead_claim_id"]] + list(plan.get("supporting_claim_ids", []))
    fact_lines = []
    for fact_id in fact_ids:
        fact = facts.get(fact_id)
        if not fact:
            continue
        sentence = _clean(fact.get("text"))
        condition = _clean(fact.get("conditions"))
        if sentence:
            fact_lines.append(sentence + ("；适用条件：" + condition if condition else ""))

    constitution = session["plan"]["style_constitution"]
    dna = session["plan"]["series_visual_dna"]
    identity = session["identity"]
    contract = plan["visual_proof_contract"]
    evidence = plan["visual_evidence"]
    pattern_index = {
        item["id"]: item
        for item in session["plan"].get("reference_expression_system", {}).get("adopted_patterns", [])
    }
    selected_patterns = [pattern_index[item] for item in plan.get("reference_pattern_ids", []) if item in pattern_index]
    reference_grammar = _joined(
        [item.get("adaptation_for_product") for item in selected_patterns],
        empty="Use only the approved campaign visual language",
    )
    reference_do_not_copy = _joined(
        [value for item in selected_patterns for value in item.get("do_not_copy", [])],
        empty="Do not copy another brand, wording, watermark or proprietary layout",
    )
    copy_bindings = _joined(
        [
            "{} -> {}".format(item.get("text", ""), item.get("bound_to_visual", ""))
            for item in plan.get("copy_intent", {}).get("text_to_visual_bindings", [])
        ],
        empty="No unbound decorative copy",
    )

    logo_rule = (
        "若提供了清晰且获授权的品牌标志，可在自然留白处出现一次独立品牌标志，保持原比例、颜色和留白；"
        "包装上的真实标志自然保留。"
        if module["order"] == 1
        else
        "不新增独立、悬浮、角标、水印式品牌标志；包装上的真实标志随产品自然保留，不拆出、不放大。"
    )

    copy_density = {
        "none": "无额外宣传文案",
        "low": "少量短文案，最多三个文字单元，文字随主体和留白分布",
        "medium": "适量文案，层级清晰，避免文字墙",
        "high": "较完整的信息层级，但仍以图像证据为主",
    }[plan["copy_density"]]
    payload_density = {
        "low": "画面至少有两个有效视觉信息载荷",
        "medium": "画面至少有三个相互关联的有效视觉信息载荷",
        "high": "画面至少有四个层次清楚、相互关联的有效视觉信息载荷",
    }[plan["visual_payload_density"]]
    commercial_energy = {
        "restrained": "克制但仍具商品吸引力，主体明确，不能像空白概念海报",
        "standard": "有成熟国内电商详情页的商品冲击力、丰富度和购买引导",
        "high": "高商业表现力，主体有冲击力，层次丰富但不杂乱",
    }[plan["commercial_energy"]]

    prompt = """创作一张竖版国内电商商品详情画面。

【商品与事实】
商品：{product}
外观必须保持：{invariants}
可表现状态：{allowed}
不得改变：{forbidden}
事实依据：
{facts}

【本张画面的视觉表达】
买家看完应理解：{takeaway}
核心动作：{verb}
主视觉主体：{primary}
辅助主体：{supporting}
主体之间必须清楚呈现：{relations}
商品专属识别锚点：{specificity}
允许的视觉比喻：{metaphor}
{payload_density}。有效载荷必须来自商品或部件、动作路径、可见结果或尺度反馈、材料微距、与商品绑定的真实场景；单纯冰雪、光效、箭头、渐变和装饰图标不计入。
即使遮住全部宣传文字，观看者仍应通过商品、动作和结果关系看懂“{hidden_test}”。

【系列视觉一致性】
视觉世界：{visual_world}
色彩与光线：{color_light}
字体与图形气质：{type_graphics}
商品表现：{rendering}
系列节奏：{rhythm}
色彩角色：{palette}
图形语言：{graphics}
摄影与光线：{photo}
空间语言：{spatial}
需要延续：{inherit}
本张应有的可见变化：{variation}
{commercial_energy}。

【文字与品牌】
{copy_rule}
文字排版要顺应主体位置、动作方向、视线和自然留白，可偏置、贴物、沿动作路径、形成局部信息组；只有画面需要时才使用居中大标题。
除上述白名单文字及包装原有文字外，不增加任何写作、编号、导航提示、设计过程说明或水印。
文字策略：{copy_density}。
{logo_rule}

【真实性与输出】
允许的可见内容：{visible_content}
不得虚构：{forbidden_inventions}
参考图只借鉴视觉语法，不复制品牌、文案、数字、水印和独占版式。
画布 {width}×{height} 像素，四周安全边距至少 {margin} 像素。中文准确可读。
""".format(
        product=_clean(identity["canonical_name"]),
        invariants=_joined(identity["invariant_features"]),
        allowed=_joined(identity["allowed_states"]),
        forbidden=_joined(identity["forbidden_mutations"]),
        facts="\n".join("- " + item for item in fact_lines) if fact_lines else "- 不添加新的事实性宣传",
        takeaway=_clean(contract["buyer_takeaway"]),
        verb=_clean(contract["visual_verb"]),
        primary=_clean(contract["primary_subject"]),
        supporting=_joined(contract["supporting_subjects"]),
        relations=_joined(contract["required_relations"]),
        specificity=_joined(contract["visual_specificity_anchor"]),
        metaphor=_clean(contract.get("allowed_metaphor")) or "仅使用与真实结构和体验一致的克制比喻",
        payload_density=payload_density,
        hidden_test=_clean(contract["hidden_copy_test"]),
        visual_world=_clean(constitution["visual_world"]),
        color_light=_clean(constitution["color_and_light"]),
        type_graphics=_clean(constitution["typography_and_graphics"]),
        rendering=_clean(constitution["product_rendering"]),
        rhythm=_clean(constitution["rhythm"]),
        palette=_clean(dna["palette_tokens"]),
        graphics=_clean(dna["graphic_tokens"]),
        photo=_clean(dna["photography_tokens"]),
        spatial=_clean(dna["spatial_tokens"]),
        inherit=_joined(plan["inherited_dna_tokens"]),
        variation=_joined(plan["variation_from_previous"]),
        commercial_energy=commercial_energy,
        copy_rule=_copy_instruction(plan.get("visible_copy", [])),
        copy_density=copy_density,
        logo_rule=logo_rule,
        visible_content=_joined(evidence["visible_content"]),
        forbidden_inventions=_joined(evidence["forbidden_inventions"]),
        width=plan["output"]["width_px"],
        height=plan["output"]["height_px"],
        margin=plan["output"]["safe_margin_px"],
    )

    if repair:
        repair_plan = module.get("repair_plan") or {}
        prompt += "\n【局部修正】\n以现有图片为底图，只修正这些可见问题：{}。应看到的变化：{}。其余已经正确的商品外观、事实、系列气质和画面关系保持稳定。\n".format(
            _joined([item.get("required_change", item) if isinstance(item, dict) else item for item in repair_plan.get("material_failures", [])]),
            _clean(repair_plan.get("expected_visible_change")),
        )

    persistent = session.get("feedback_constraints", {})
    if "global" in persistent or "by_module" in persistent:
        global_ledger = persistent.get("global", {})
        module_ledger = persistent.get("by_module", {}).get(module["id"], {})
    else:  # Backward-compatible reader for v0.6 sessions.
        global_ledger = persistent
        module_ledger = {}

    global_preserve = _dedupe(list(global_ledger.get("preserve", [])))
    global_non_regress = _dedupe(list(global_ledger.get("must_not_regress", [])))
    module_preserve = _dedupe(list(module_ledger.get("preserve", [])))
    module_non_regress = _dedupe(list(module_ledger.get("must_not_regress", [])))
    if global_preserve or global_non_regress or module_preserve or module_non_regress:
        prompt += (
            "\nPERSISTED FEEDBACK CONTRACT (binding):\n"
            "- Preserve globally: {}.\n"
            "- Never regress globally: {}.\n"
            "- Preserve for current module only: {}.\n"
            "- Never regress for current module only: {}.\n"
            "Do not import constraints from any other module.\n"
        ).format(
            _joined(global_preserve),
            _joined(global_non_regress),
            _joined(module_preserve),
            _joined(module_non_regress),
        )

    adjustment = module.get("user_adjustment")
    if adjustment:
        change_only = adjustment.get("change_only", adjustment.get("visible_changes", []))
        preserve = _dedupe(
            global_preserve
            + module_preserve
            + list(adjustment.get("preserve", []))
        )
        non_regress = _dedupe(
            global_non_regress
            + module_non_regress
            + list(adjustment.get("must_not_regress", []))
        )
        prompt += "\n【定向调整】\n只改变：{}。必须保留：{}。不得退化：{}。不要重做其他已经正确的部分。\n".format(
            _joined(change_only), _joined(preserve), _joined(non_regress)
        )

    prompt = prompt.strip() + "\n"
    text_system = plan["text_system"]
    prompt += (
        "TYPOGRAPHY LAYOUT CONTRACT (binding, pixel-audited):\n"
        "- Primary mode: {primary_mode}; supporting mode: {supporting_mode}.\n"
        "- Bind the typography to: {anchor_target}. Place the primary group in zone: {anchor_zone}.\n"
        "- Reading direction: {reading_direction}. Placement logic: {placement_logic}.\n"
        "- Hierarchy: {hierarchy}. Maximum lines in the primary group: {max_lines}. Container treatment: {container_style}.\n"
        "- Reserve this negative space before placing subjects: {negative_space}.\n"
        "- Image/text relationship: {relationship}. Composition flexibility: {flexibility}.\n"
        "- Required visible difference from the neighboring screen: {neighbor_difference}.\n"
        "Do not fall back to a generic top-left or centered headline unless that exact mode and zone are named above. "
        "Low copy means concise auxiliary copy, never a lone headline replacing visual proof.\n"
    ).format(
        primary_mode=_clean(text_system["primary_mode"]),
        supporting_mode=_clean(text_system.get("supporting_mode")) or "none",
        anchor_target=_clean(text_system["anchor_target"]),
        anchor_zone=_clean(text_system["anchor_zone"]),
        reading_direction=_clean(text_system["reading_direction"]),
        placement_logic=_clean(text_system["placement_logic"]),
        hierarchy=_clean(text_system["hierarchy"]),
        max_lines=text_system["max_lines"],
        container_style=_clean(text_system["container_style"]),
        negative_space=_clean(text_system["negative_space_reservation"]),
        relationship=_clean(text_system["image_text_relationship"]),
        flexibility=_clean(text_system["composition_flexibility"]),
        neighbor_difference=_clean(text_system["neighbor_difference"]),
    )
    flexibility = text_system["composition_flexibility"]
    if flexibility == "CONTROLLED_REFLOW":
        prompt += (
            "TYPOGRAPHY REFLOW PERMISSION: controlled local reflow is required when needed. You may move or recrop "
            "supporting subjects and rebuild negative space so the approved text can bind naturally to its target, "
            "while preserving product identity, factual evidence, campaign palette, lighting, and screen duty.\n"
        )
    elif flexibility == "NEGATIVE_SPACE_ONLY":
        prompt += (
            "TYPOGRAPHY REFLOW PERMISSION: use only the reserved negative-space zone. Do not move the product or proof relationship.\n"
        )
    else:
        prompt += (
            "TYPOGRAPHY REFLOW PERMISSION: composition is locked; fit typography only inside the declared zone without changing geometry.\n"
        )
    prompt += (
        "APPROVED PLAN CONTRACT (binding): do not replace, simplify, or reinterpret the approved selling point, "
        "subjects, relations, composition duty, or copy whitelist.\n"
        "REFERENCE EXPRESSION GRAMMAR TO ADAPT: {}.\n"
        "REFERENCE MATERIAL MUST NOT BE COPIED: {}.\n"
        "COPY IS AUXILIARY, NOT ABSENT: keep the image understandable without copy, then bind each approved text unit "
        "to its visible object/relation/result as follows: {}.\n"
    ).format(reference_grammar, reference_do_not_copy, copy_bindings)
    prompt_preflight(prompt)
    return prompt
