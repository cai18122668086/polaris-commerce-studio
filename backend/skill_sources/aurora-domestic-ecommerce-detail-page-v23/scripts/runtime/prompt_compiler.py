from __future__ import annotations

import re
from typing import Iterable, List

from .performance_contract import resolve_performance_contract
from .spatial_contract import resolve_spatial_contract
from .state import HarnessError


FORBIDDEN_PIXEL_PATTERNS = (
    (re.compile(r"\bM\d{2,}\b", re.IGNORECASE), "internal module identifier"),
    (re.compile(r"上一屏|下一屏|页面职责|买家问题|主结论|承接|引向"), "workflow navigation"),
    (re.compile(r"构图家族|证据等级|文字模式|Logo策略|模块编号|页码|屏号"), "internal planning label"),
    (re.compile(r"对应包装|正标位置|卖点对应|证据区|限定语|来源说明|绑定位置"), "internal copy-placement language"),
    (re.compile(r"以包装标[示识]为准|购买前请核对|购买前以实际|当前仅能确认|缺少检测报告|待核验|待验证|未确认"), "machine-side evidence qualification"),
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
    if isinstance(values, (str, bytes)):
        raise HarnessError("Prompt list field received a scalar string; refusing character-by-character compilation")
    if not isinstance(values, Iterable):
        raise HarnessError("Prompt list field must be iterable")
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
    if not isinstance(visible_copy, list):
        raise HarnessError("visible_copy must be a list")
    support_mark_rule = (
        "允许按画面逻辑使用不承载新主张的视觉组织标记：当画面确有连续动作或并列步骤时，"
        "可用1/2/3或01/02/03作为小型顺序标记，也可使用简单箭头、圆点和分隔线。"
        "这些标记只能帮助阅读已经可见的动作与区域，不得新增功效、成分、数量、条件、认证或结论。"
    )
    if not visible_copy:
        return "画面不放宣传文字，只保留产品包装上真实存在的印刷信息。" + support_mark_rule
    lines = []
    for item in visible_copy:
        text = _clean(item.get("text"))
        if text:
            lines.append("文字“{}”".format(text))
    if not lines:
        return "画面不放宣传文字，只保留产品包装上真实存在的印刷信息。" + support_mark_rule
    return "仅允许出现以下宣传文字：\n" + "\n".join("- " + line for line in lines) + "\n" + support_mark_rule


def compile_prompt(
    session: dict,
    module: dict,
    repair: bool = False,
    format_canvas_lock: bool = False,
) -> str:
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
    performance = resolve_performance_contract(
        plan,
        order=module.get("order", 1),
        module_count=len(session.get("plan", {}).get("modules", [])) or 1,
    )
    evidence = plan["visual_evidence"]
    archetype = _clean(plan.get("visual_archetype"))
    if not archetype:
        if plan.get("authoring_plan_format") == "COMPACT_V1_2":
            raise HarnessError("Every v1.2 module requires a cross-category visual archetype")
        archetype = {
            "HOOK": "BENEFIT_OVERVIEW", "PAIN_ARTICULATION": "PAIN_SCENE",
            "PAIN_SOLUTION_COMBINED": "PAIN_TO_SOLUTION_BRIDGE",
            "SOLUTION_PROOF": "DEDICATED_BENEFIT_PROOF", "MECHANISM_PROOF": "SOURCE_ACTION_RESULT",
            "MATERIAL_PROOF": "WHOLE_PLUS_MACRO", "USE_OR_RESULT": "USE_SCOPE_MATRIX",
            "TRUST_OR_RISK_REMOVAL": "TRUST_EVIDENCE", "SELECTION_OR_SPECIFICATION": "SELECTION_COMPARISON",
            "PURCHASE_CLOSURE": "PURCHASE_CLOSURE",
        }.get(plan.get("story_function"), "BENEFIT_OVERVIEW")
    expression = plan.get("module_visual_expression_contract") or {
        "expression_mode": "IMAGE_FIRST",
        "claim_visualizability": "VISUALIZABLE",
        "primary_visual_carrier": "PRODUCT_HERO",
        "visual_scene_sentence": contract["visual_verb"],
        "visual_semantic_payload": contract["hidden_copy_test"],
        "required_visual_relations": contract["required_relations"],
        "copy_responsibility": "文字只命名或限定画面中已经可见的关系",
        "copy_only_justification": "",
        "forbidden_substitutes": ["纯文字解释", "纯图标解释", "装饰氛围替代证据", "通用商品摆拍", "等大卡片平铺"],
        "product_presence_policy": "REQUIRED_DOMINANT",
        "evidence_subject_policy": "PRODUCT_DOMINANT",
        "visualization_mode": "DIRECT_OBSERVATION",
        "transformation_required": False,
        "transformation_stages": [],
        "truth_boundary": "只呈现可核实的商品外观、动作和结果",
    }
    transition = plan.get("transition_contract") or {}
    transition_instruction = (
        "屏间衔接：主方法={method}（{basis}）；接收锚点={incoming_anchor}；交付锚点={outgoing_anchor}；"
        "本屏采用{mode}；从前段接收{incoming}；本屏向后段交付{outgoing}；"
        "空间方向为{direction}；保持{invariants}；允许{change}。"
        "按主方法形成真实可见的屏边、动线、状态或图形接力；接缝来源={source}，接缝目标={target}，接缝几何={geometry}，"
        "必须有可追踪的画面元素在边界处连续{overlap}；只继承色彩、材质、光线或动线线索，不复制前段主体坐标、文字区域或版式骨架。"
    ).format(
        method=_clean(transition.get("method_id", "自动选择的衔接方法")),
        basis=_clean(transition.get("selection_basis", "依据本屏证据与叙事职责")),
        incoming_anchor=_clean(transition.get("incoming_anchor", "前屏可见线索")),
        outgoing_anchor=_clean(transition.get("outgoing_anchor", "下一屏可接线索")),
        mode=_clean(transition.get("mode", "CARRIER_HANDOFF")),
        incoming=_clean(transition.get("incoming_carrier", "一项可见视觉线索")),
        outgoing=_clean(transition.get("outgoing_carrier", "一项可继续变化的线索")),
        direction=_clean(transition.get("spatial_direction", "由本屏关系自然决定")),
        invariants=_joined(transition.get("shared_invariants", []), empty="当前系列DNA"),
        change=_clean(transition.get("allowed_change", "改变主体状态或结构")),
        source=_clean(transition.get("source_region_previous", "上一屏靠近分界的可见元素")),
        target=_clean(transition.get("target_region_current", "本屏靠近分界的对应区域")),
        geometry=_clean(transition.get("handoff_geometry", "位置、方向、尺度或运动关系在分界处可追踪")),
        overlap="（允许明确断开，仅适用于章节转场）" if not transition.get("visible_overlap_required", True) else "，不得只用相似配色替代",
    )
    presence_policy = expression.get("product_presence_policy", "REQUIRED_DOMINANT")
    presence_decision = plan.get("product_presence_decision") or {}
    carrier_priority = {
        "REQUIRED_DOMINANT": "商品是第一视觉主体。",
        "REQUIRED_SUPPORTING": "功效对象、动作或结果是第一视觉主体；商品只作第二或第三识别锚点。",
        "IDENTITY_TOKEN_ONLY": "禁止完整商品、完整包装、包装轮廓或角落商品图；只允许计划中批准的局部、材质、色彩或部件身份线索。",
        "OPTIONAL": "商品可以小比例出现，也可以完全不出现；不能为了露出商品牺牲核心证据。",
        "ABSENT_ALLOWED": "本屏允许并优先不出现商品，让功效对象、作用路径和结果变化占据全部主要视觉重量。",
        "ABSENT_PREFERRED": "本屏优先完全不出现商品或包装；禁止把商品藏在角落、背景、虚化层、边缘卡片或装饰性小图中。让来源、材质、机制、结果、场景或信任证据占据全部主要视觉重量。",
    }.get(presence_policy, "商品是第一视觉主体。")
    presence_decision_instruction = (
        "商品若出镜承担的唯一任务：{job}。商品缺席时的第一视觉主体：{subject}。"
        "无完整商品时仍需通过以下商品专属线索维持归属：{bindings}。缺席理由：{reason}。"
    ).format(
        job=_clean(presence_decision.get("unique_job_if_present")) or "NONE",
        subject=_clean(presence_decision.get("primary_subject_without_product")) or _clean(contract["primary_subject"]),
        bindings=_joined(presence_decision.get("identity_binding_without_product", []), empty="当前卖点的商品专属对象、材质、动作或视觉DNA"),
        reason=_clean(presence_decision.get("absence_reason")) or "本屏不以重复露出商品替代证据",
    )
    prominence_instruction = (
        f"商品视觉占比不得低于约 {performance['product_prominence_min_percent']}%。"
        if performance["product_prominence_min_percent"] > 0
        else "本屏不设商品最低占比；商品缺席不构成失败，功效证据被商品抢占才构成失败。"
    )
    transformation_instruction = (
        "必须把以下阶段画成连续或可比较的可见变化：" + _joined(expression.get("transformation_stages", []), empty="问题对象→发生作用→减少、分离、失活语义或结果状态")
        if expression.get("transformation_required")
        else "本屏无需强制三段变化，但核心结论仍必须有真实对象或状态承载。"
    )
    conceptual_instruction = {
        "CONCEPTUAL_NON_DIAGNOSTIC": "允许使用明显经过设计的概念性科学画面：可画细菌、真菌、螨虫、异味粒子、污渍、热量、粉尘等卖点对象及其被包围、松脱、隔离、移除、减少或失活语义；也允许使用未标注、明显风格化的球体连线、节点网络或分子感图形来表达已核实的配方/成分群概念。这些图形只作视觉修辞，不代表具体分子结构，不要求与计划中的示意形状逐点一致，也不得仅因其造型差异触发重修。不得标注未经核实的化学名称、键位或结构式，不得伪装成真实显微、实验、检测、精确作用机理、数值或实验结论。",
        "DIRECT_OBSERVATION": "使用可直接观察的真实商品、材质、动作、前后状态或使用结果，不把概念图伪装成检测证据。",
        "CONTEXTUAL_ONLY": "只表现使用环境、买家问题和适用情境，不声称画面本身证明了不可见功效。",
    }.get(expression.get("visualization_mode"), "只表现事实允许的对象和关系。")
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
    spatial = resolve_spatial_contract(plan)
    zone_lines = []
    for index, zone in enumerate(spatial["zones"], start=1):
        zone_lines.append(
            "区域{}承担{}，采用{}，放置{}，约占{}%视觉重量".format(
                index, _clean(zone["role"]), _clean(zone["geometry"]),
                _clean(zone["content"]), zone["visual_weight_percent"],
            )
        )
    full_bleed_rule = (
        "允许一个连续场景承载本屏，但仍须满足声明的意义层次。"
        if spatial["full_bleed_single_scene_allowed"]
        else "禁止退化成一张全幅照片叠加标题或底部说明卡；必须清楚看出多个空间区域及其关系。"
    )

    logo_source = identity.get("brand_logo_source") or {}
    logo_source_id = plan.get("independent_logo_source_id") or logo_source.get("image_id") or identity["reference_image_ids"][0]
    logo_rule = (
        "首屏必须恰好出现一次清晰、独立的品牌Logo，不能只依赖包装上印刷的小Logo。"
        f"品牌Logo必须严格匹配当前商品参考图 {logo_source_id} 中的真实标志，保持字形、比例、颜色与安全留白；"
        "将其放入自然留白或明确的品牌锚点区，不得省略、改写、重绘成近似字样，也不得出现第二个独立Logo。"
        "包装上的真实标志仍作为商品身份自然保留，不计入这一次独立Logo。"
        if module["order"] == 1
        else
        "本屏独立品牌Logo数量必须为零；不新增悬浮、角标、页眉、页脚或水印式品牌标志。"
        "包装上的真实标志随产品自然保留，不拆出、不放大。"
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
    background_competition = {
        "LOW": "低，背景只提供环境与纵深，不得抢夺商品和证据",
        "LOW_TO_MEDIUM": "低到中，允许可信环境信息，但商品和证据必须明显占优",
        "MEDIUM": "中等，背景可承担场景意义，但不得成为第一视觉主体",
    }[performance["background_competition_max"]]
    headline_rule = (
        f"标题必须进入前 {performance['headline_rank_max']} 个视觉层级，移动端缩略图仍可识别"
        if performance["headline_must_enter_top_three"]
        else "标题服从证据与场景，不得抢占不必要的第一视觉层级"
    )
    visible_copy_count = len([item for item in plan.get("visible_copy", []) if _clean(item.get("text"))])
    type_role_requirement = min(performance["type_role_target"], max(1, visible_copy_count))
    unequal_group_requirement = min(performance["unequal_information_groups_min"], max(1, visible_copy_count + 1))
    pain_expression = expression.get("pain_expression") or {}
    pain_expression_instruction = (
        "痛点表达形式：{form}；痛点主体：{subject}；可见性：{visibility}；数量结构：{multiplicity}；"
        "痛点关系：{relation}；情绪强度：{intensity}。选择理由：{reason}。"
        "必须按这种信息关系组织画面，但不得套用任何品类模板；参考案例只提供视觉语法。"
        "人物、商品、环境、任务或系统关系均可成为主视觉，产品不必强行出现。"
        .format(
            form=_clean(pain_expression.get("expression_form")),
            subject=_clean(pain_expression.get("pain_subject_type")),
            visibility=_clean(pain_expression.get("pain_visibility")),
            multiplicity=_clean(pain_expression.get("pain_multiplicity")),
            relation=_clean(pain_expression.get("pain_relation")),
            intensity=_clean(pain_expression.get("emotional_intensity")),
            reason=_clean(pain_expression.get("selection_reason")),
        )
        if pain_expression
        else "本屏不是痛点表达模块，不套用痛点版式。"
    )
    commercial_comfort = expression.get("commercial_comfort") or {}
    commercial_comfort_instruction = (
        "厌恶风险：{risk}；目标不适强度：{target}；净化表达策略：{strategy}；"
        "问题细节主导策略：{dominance}。禁止出现：{forbidden}。替代表达：{replacement}。"
        "痛点必须一眼可识别，但不得用令人反胃、惊吓、羞辱或临床化的视觉刺激换取冲击力。"
        .format(
            risk=_clean(commercial_comfort.get("aversion_risk")),
            target=_clean(commercial_comfort.get("discomfort_target")),
            strategy=_clean(commercial_comfort.get("sanitization_strategy")),
            dominance=_clean(commercial_comfort.get("detail_dominance_policy")),
            forbidden=_joined(commercial_comfort.get("forbidden_visual_details", [])),
            replacement=_clean(commercial_comfort.get("replacement_expression")),
        )
        if commercial_comfort
        else "本屏未识别到中高厌恶风险；仍保持适合电商销售的整洁、克制和尊重。"
    )

    prompt = """创作一张竖版国内电商商品详情画面。

【商品与事实】
商品：{product}
外观必须保持：{invariants}
可表现状态：{allowed}
不得改变：{forbidden}
事实依据：
{facts}

【本张画面的视觉表达】
表现原型：{archetype}。原型只规定信息关系，不套用固定行业模板。
买家看完应理解：{takeaway}
核心动作：{verb}
主视觉主体：{primary}
辅助主体：{supporting}
主体之间必须清楚呈现：{relations}
商品专属识别锚点：{specificity}
允许的视觉比喻：{metaphor}
{payload_density}。有效载荷必须来自商品或部件、动作路径、可见结果或尺度反馈、材料微距、与商品绑定的真实场景；单纯冰雪、光效、箭头、渐变和装饰图标不计入。
即使遮住全部宣传文字，观看者仍应通过商品、动作和结果关系看懂“{hidden_test}”。

【无文字视觉语义合同】
表达模式：{expression_mode}；可视觉化等级：{claim_visualizability}。
先构建可见场景：{visual_scene_sentence}
主视觉载体：{primary_visual_carrier}。{carrier_priority}
商品出镜策略：{product_presence_policy}。证据主体策略：{evidence_subject_policy}。
{transition_instruction}
商品出镜节奏合同：{presence_decision_instruction}
视觉化方式：{visualization_mode}。{conceptual_instruction}
变化合同：{transformation_instruction}
真实性边界：{truth_boundary}
遮住宣传文字后，观众仍必须理解：{visual_semantic_payload}
必须清楚可见的语义关系：{semantic_relations}
文字只负责：{copy_responsibility}
纯文字例外理由：{copy_only_justification}
不得用以下内容替代画面语义：{forbidden_substitutes}
图标、箭头、光效和标签只能辅助已经可见的对象、动作、状态变化或结果，不能独立承担核心卖点。
痛点表达路由：{pain_expression_instruction}
商业舒适度控制：{commercial_comfort_instruction}

【视觉表现合同】
商品主导：{product_dominance}；{prominence_instruction}
标题主导：{headline_dominance}；{headline_rule}。
核心证据：{evidence_anchor}；必须成为主视觉：{evidence_primary}。
纵深结构：{depth_plan}；至少形成 {depth_layers} 个可区分的意义层次。
视觉张力：{visual_tension}；必须清楚可见：{tension_required}。
背景竞争：最高允许 {background_competition}。
信息层级：最多只围绕白名单文字建立 {type_roles} 种必要文字角色，同时形成至少 {unequal_groups} 个由画面与文字共同组成的不等权信息组；不得为了凑层级自动添加卡片、小字或图标标签。
移动端扫描停顿：至少 {scan_stops} 个，顺序为 {scan_order}。
商业闭合：{commercial_closure}；必须可见：{closure_required}。
允许大胆使用：{creative_permissions}，但只能建立在当前商品事实和证据上。
禁止退化：{forbidden_regression}。

【画面空间结构合同】
本屏必须形成 {zone_count} 个可辨认的意义区域，结构关系为：{structural_relationship}。
{zones}
主导区域数量：{dominant_zone_count}；辅助面板数量不得少于：{secondary_panel_count}；独立小场景数量不得少于：{mini_scene_count}。
{full_bleed_rule}
与相邻画面的结构差异：{structure_difference}。
不得退化为：{spatial_fallbacks}。
区域必须以真实对象、动作、状态、结果或购买判断区分；同一照片上漂浮几个通用卡片不算多区域。

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
首屏参考如被提供，只用于继承色彩角色、光线、摄影质感、字体气质、图形语言、商品渲染和系列装饰母题。严禁继承首屏的版式骨架、主体坐标、商品占比、文字区域、景别、区域几何或全幅海报模板；当前画面必须服从本屏空间结构合同。

【文字与品牌】
{copy_rule}
文字排版要顺应主体位置、动作方向、视线和自然留白，可偏置、贴物、沿动作路径、形成局部信息组；只有画面需要时才使用居中大标题。
除上述白名单文字、包装原有文字及被允许的非主张型视觉组织标记外，不增加任何写作、导航提示、设计过程说明或水印。
不得自动补充白名单之外的解释性小字、脚注、位置提示、来源提示、图标标签或排版注释。
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
        archetype=archetype,
        verb=_clean(contract["visual_verb"]),
        primary=_clean(contract["primary_subject"]),
        supporting=_joined(contract["supporting_subjects"]),
        relations=_joined(contract["required_relations"]),
        specificity=_joined(contract["visual_specificity_anchor"]),
        metaphor=_clean(contract.get("allowed_metaphor")) or "仅使用与真实结构和体验一致的克制比喻",
        payload_density=payload_density,
        hidden_test=_clean(contract["hidden_copy_test"]),
        expression_mode=_clean(expression["expression_mode"]),
        claim_visualizability=_clean(expression["claim_visualizability"]),
        visual_scene_sentence=_clean(expression["visual_scene_sentence"]),
        primary_visual_carrier=_clean(expression["primary_visual_carrier"]),
        carrier_priority=carrier_priority,
        product_presence_policy=_clean(presence_policy),
        presence_decision_instruction=presence_decision_instruction,
        evidence_subject_policy=_clean(expression.get("evidence_subject_policy")),
        transition_instruction=transition_instruction,
        visualization_mode=_clean(expression.get("visualization_mode")),
        conceptual_instruction=conceptual_instruction,
        transformation_instruction=transformation_instruction,
        truth_boundary=_clean(expression.get("truth_boundary")),
        visual_semantic_payload=_clean(expression["visual_semantic_payload"]),
        semantic_relations=_joined(expression["required_visual_relations"]),
        copy_responsibility=_clean(expression["copy_responsibility"]),
        copy_only_justification=_clean(expression.get("copy_only_justification")) or "不适用；核心含义必须由画面承担",
        forbidden_substitutes=_joined(expression["forbidden_substitutes"]),
        pain_expression_instruction=pain_expression_instruction,
        commercial_comfort_instruction=commercial_comfort_instruction,
        product_dominance=_clean(performance["product_dominance"]),
        prominence_instruction=prominence_instruction,
        headline_dominance=_clean(performance["headline_dominance"]),
        headline_rule=headline_rule,
        evidence_anchor=_clean(performance["primary_evidence_anchor"]),
        evidence_primary="是" if performance["evidence_must_be_primary_visual"] else "否",
        depth_plan=_clean(performance["depth_plan"]),
        depth_layers=performance["depth_layers_min"],
        visual_tension=_clean(performance["visual_tension"]),
        tension_required="是" if performance["visual_tension_required"] else "否",
        background_competition=background_competition,
        type_roles=type_role_requirement,
        unequal_groups=unequal_group_requirement,
        scan_stops=performance["mobile_scan_stops_min"],
        scan_order=_joined(performance["mobile_scan_order"]),
        commercial_closure=_clean(performance["commercial_closure"]),
        closure_required="是" if performance["commercial_closure_required"] else "否",
        creative_permissions=_joined(performance["creative_permissions"]),
        forbidden_regression=_joined(performance["forbidden_regression"]),
        zone_count=spatial["zone_count"],
        structural_relationship=_clean(spatial["structural_relationship"]),
        zones="\n".join("- " + item for item in zone_lines),
        dominant_zone_count=spatial["dominant_zone_count"],
        secondary_panel_count=spatial["secondary_panel_count"],
        mini_scene_count=spatial["mini_scene_count"],
        full_bleed_rule=full_bleed_rule,
        structure_difference=_clean(spatial["structure_difference_from_previous"]),
        spatial_fallbacks=_joined(spatial["forbidden_fallbacks"]),
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
        "to the visible object, action, relation or result it names. Never render the binding instruction itself.\n"
    ).format(reference_grammar, reference_do_not_copy)
    if format_canvas_lock:
        output = plan["output"]
        prompt = (
            "【输出比例硬锁】第一张参考图是纯格式底板，只规定画布，不提供任何商品、风格、背景或版式内容。"
            f"必须在整张 {output['width_px']}×{output['height_px']} 像素、"
            f"{output['width_px']}:{output['height_px']} 比例的底板内完成画面，完整覆盖四边；"
            "不得生成更窄或更长的内嵌海报，不得保留底板颜色、空白边、边框或留白柱。\n"
        ) + prompt
    prompt_preflight(prompt)
    return prompt
