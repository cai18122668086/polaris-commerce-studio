import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness  # noqa: E402
from runtime.assembly import assemble_vertical  # noqa: E402
from runtime.prompt_compiler import compile_prompt, prompt_preflight  # noqa: E402
from runtime.plan_normalizer import normalize_plan  # noqa: E402
from runtime.sales_architecture import (  # noqa: E402
    validate_dynamic_count_formula,
    validate_user_selling_point_ledger,
    validate_visual_archetypes,
)
from runtime.sales_depth_contract import validate_sales_depth_contract  # noqa: E402
from runtime.spatial_contract import resolve_spatial_contract, validate_spatial_contract  # noqa: E402
from runtime.state import HarnessError  # noqa: E402
from runtime.visual_gate import CHECKS, validate_module_judgment  # noqa: E402


def profile():
    return {
        "target_platform": "淘宝移动端",
        "profile_name": "INTERNAL_REVIEW_1440_3_4",
        "selection_mode": "ADAPTIVE_PLANNED",
        "selection_rationale": "竖向产品结构、移动阅读节奏和动作关系都适合三比四的单屏表达。",
        "source": "internal review",
        "aspect_ratio": {"width_units": 3, "height_units": 4, "label": "3:4"},
        "canvas_width_px": 1440,
        "module_height_px": 1920,
        "safe_margin_px": 72,
        "slice_height_px": 1200,
        "format": "PNG",
        "max_file_bytes": None,
        "verification_status": "BACKEND_CONFIRMATION_REQUIRED",
    }


def raw_input(with_conflict=False, with_reference=False):
    facts = [
        {"id": "F1", "text": "产品支持接触式冷感并可送风", "source_class": "USER_FACT", "evidence_ref": "brief"}
    ]
    conflicts = []
    if with_conflict:
        facts.extend([
            {"id": "F2", "text": "电池容量为3000mAh", "source_class": "USER_FACT", "evidence_ref": "brief"},
            {"id": "F3", "text": "电池容量为5000mAh", "source_class": "DOCUMENTED_EVIDENCE", "evidence_ref": "package"},
        ])
        conflicts = [{
            "id": "C1", "topic": "电池容量", "alternative_fact_ids": ["F2", "F3"],
            "why_material": "容量会改变规格屏与续航表达，两个值不能同时描述同一SKU。", "status": "UNRESOLVED",
        }]
    references = []
    if with_reference:
        references = [{
            "id": "R1", "path": "reference.jpg", "category": "小家电", "analysis_status": "ANALYZED",
            "observed_expression_methods": ["主体占画面六成，气流路径从进风口连续指向出风结果"],
            "analyzed_units": [{
                "id": "R1-U1", "source_region": "拼接图第一列第一屏", "page_duty": "结构机制证明",
                "visual_carrier": "产品主体和连续气流路径", "composition_logic": "主体占六成并以路径连接部件",
                "typography_logic": "短标签贴近气流节点",
                "observed_expression_method": "主体占画面六成，气流路径从进风口连续指向出风结果",
            }],
        }]
    return {
        "product_name": "手持制冷风扇",
        "category": "小家电",
        "target_buyer": "通勤人群",
        "product_images": [
            {"id": "front", "path": "front.jpg", "role": "front_identity"},
            {"id": "rear", "path": "rear.jpg", "role": "rear_detail"},
        ],
        "verified_facts": facts,
        "conflict_policy": "BLOCK_PLAN_AND_BATCH_ASK",
        "conflict_scan": {
            "status": "CONFLICTS_FOUND" if conflicts else "CLEAR",
            "scanned_topics": ["identity", "specification", "formula", "audience", "compliance"],
            "conflict_ids": [item["id"] for item in conflicts],
        },
        "source_conflicts": conflicts,
        "reference_materials": references,
        "platform_profile": profile(),
    }


def route_aware_input(route="PHOTO_TO_PRODUCT_STRATEGY"):
    value = raw_input()
    value["verified_facts"][0].update({
        "atomic_key": "contact_cooling_and_airflow",
        "atomicity": "ONE_INDEPENDENT_PROPOSITION",
        "source_class": "DOCUMENTED_EVIDENCE" if route == "PHOTO_TO_PRODUCT_STRATEGY" else "USER_FACT",
    })
    value["intake_route"] = route
    value["user_supplied_selling_points"] = [] if route == "PHOTO_TO_PRODUCT_STRATEGY" else [{
        "id": "USP1", "text": "接触冷感与送风协同", "source_ref": "用户文字", "fact_ids": ["F1"],
    }]
    value["operating_analysis"] = {
        "route_reason": "用户只上传商品照片且没有主动指定可执行卖点。" if route == "PHOTO_TO_PRODUCT_STRATEGY" else "用户主动给出了具体的接触冷感卖点。",
        "confirmed_fact_ids": ["F1"],
        "buyer_hypotheses": [{"id": "B1", "buyer": "通勤人群", "scenario": "炎热天气通勤", "reasoning": "便携形态与手持使用方式适合通勤", "confidence": "MEDIUM"}],
        "pain_hypotheses": [{"id": "P1", "pain": "普通便携风扇体感降温不足", "kind": "FUNCTIONAL", "reasoning": "用户会比较送风之外的体感差异", "claim_boundary": "痛点可指导场景，效果表述只能使用已核验事实"}],
        "value_bridges": [{"id": "VB1", "fact_ids": ["F1"], "pain_id": "P1", "feature": "接触冷感并可送风", "buyer_benefit": "形成两种体感路径", "purchase_reason": "不只依赖普通送风", "visual_route": "展示气流与接触部件的两条真实路径", "claim_permission": "VERIFIED_CLAIM"}],
        "positioning_candidates": [
            {"id": "POS1", "thesis": "双路径便携冷感", "score_rationale": "事实明确、画面关系可见且适合通勤购买判断", "decision": "SELECTED"},
            {"id": "POS2", "thesis": "普通便携送风", "score_rationale": "风险较低但不能体现产品结构差异与购买理由", "decision": "REJECTED"},
        ],
        "selected_positioning_id": "POS1",
        "evidence_gaps": [],
        "assumption_disclosure": "通勤人群和痛点属于运营假设，只指导场景，不作为额外效果宣称。",
    }
    return value


def identity():
    return {
        "canonical_name": "手持制冷风扇", "category": "小家电",
        "reference_image_ids": ["front", "rear"],
        "brand_logo_source": {
            "image_id": "front",
            "authorization_basis": "USER_SUPPLIED_CURRENT_PRODUCT",
            "readability": "READABLE",
            "usage": "FIRST_SCREEN_INDEPENDENT_LOGO",
        },
        "invariant_features": ["真实轮廓", "真实按键和进出风口"],
        "allowed_states": ["手持", "桌面使用"], "uncertain_features": [],
        "forbidden_mutations": ["不得改成普通圆形风扇"],
    }


def performance_contract(order):
    strategy = {1: "FIRST_SCREEN_CORE_BENEFIT", 2: "MECHANISM", 3: "PURCHASE_CLOSURE"}[order]
    energy = "MEDIUM_HIGH" if order == 2 else "HIGH"
    return {
        "strategy_type": strategy,
        "target_energy": energy,
        "product_dominance": "商品必须是第一视觉主体并占据主要视觉重量",
        "product_prominence_min_percent": 35,
        "headline_dominance": "标题进入前三视觉层级并服从商品证据",
        "headline_must_enter_top_three": True,
        "headline_rank_max": 3,
        "primary_evidence_anchor": "冷感部件与连续气流路径",
        "evidence_must_be_primary_visual": True,
        "depth_plan": "前景接触反馈、中景真实商品、后景通勤环境",
        "depth_layers_min": 3,
        "visual_tension": "大比例商品与局部接触证据形成尺度反差",
        "visual_tension_required": True,
        "background_competition_max": "LOW_TO_MEDIUM",
        "information_density": "MEDIUM_HIGH",
        "type_role_target": 3,
        "unequal_information_groups_min": 3,
        "mobile_scan_stops_min": 3,
        "mobile_scan_order": ["核心标题", "冷感与气流证据", "完整商品"],
        "commercial_closure": "最终视线回到接触冷感与送风的购买理由",
        "commercial_closure_required": True,
        "creative_permissions": ["商品与部件双尺度", "气流路径与接触瞬间"],
        "forbidden_regression": [
            "商品加一句标题", "装饰元素替代卖点证据", "所有信息等大平铺",
            "通用摄影棚背景", "漂亮但看不出在卖什么",
        ],
    }


def module(order, cluster_ids=("SP1",), reference_pattern_ids=(), copy_density="low"):
    visible_copy = [
        {"text": "一握即凉", "role": "偏置短标题", "anchor": "冷感部件"},
        {"text": "强风×冷感", "role": "关系标签", "anchor": "气流路径"},
    ]
    if copy_density == "none":
        visible_copy = []
    spatial_options = {
        1: {
            "structure_family": "FULL_BLEED_HERO", "zone_count": 1,
            "zones": [{"role": "英雄商品舞台", "geometry": "全幅纵深主场景", "content": "完整商品、气流与冷感接触", "visual_weight_percent": 100}],
            "structural_relationship": "FULL_BLEED_SINGLE_SCENE", "full_bleed_single_scene_allowed": True,
            "dominant_zone_count": 1, "secondary_panel_count": 0, "mini_scene_count": 0,
            "structure_difference_from_previous": "首屏建立唯一的全幅英雄舞台。",
        },
        2: {
            "structure_family": "MACRO_DIAGRAM", "zone_count": 2,
            "zones": [
                {"role": "结构主图", "geometry": "左侧约六成的大型部件微距", "content": "真实产品与冷感部件", "visual_weight_percent": 60},
                {"role": "作用路径", "geometry": "右侧约四成的连续路径区域", "content": "进风、出风与接触反馈", "visual_weight_percent": 40},
            ],
            "structural_relationship": "PATH", "full_bleed_single_scene_allowed": False,
            "dominant_zone_count": 1, "secondary_panel_count": 1, "mini_scene_count": 0,
            "structure_difference_from_previous": "由全幅英雄舞台切换为左右两区的结构路径。",
        },
        3: {
            "structure_family": "FRAMED_LIFESTYLE_PLUS_CARDS", "zone_count": 2,
            "zones": [
                {"role": "通勤结果场景", "geometry": "上部大型框景人物区", "content": "人物使用商品后的通勤状态", "visual_weight_percent": 65},
                {"role": "购买收口", "geometry": "下部两个不等宽场景面板", "content": "手持与桌面使用及完整商品", "visual_weight_percent": 35},
            ],
            "structural_relationship": "SCENE_TO_CARDS", "full_bleed_single_scene_allowed": False,
            "dominant_zone_count": 1, "secondary_panel_count": 1, "mini_scene_count": 2,
            "structure_difference_from_previous": "由左右路径结构切换为上部框景和下部多场景收口。",
        },
    }
    spatial = spatial_options[order]
    spatial.update({
        "series_master_layout_inheritance": False,
        "forbidden_fallbacks": ["一张全幅照片加标题", "通用卡片漂浮在同一背景", "只换主体不换空间关系"],
    })
    return {
        "id": f"M{order:02d}", "order": order, "duty": "证明制冷送风价值",
        "buyer_question": "为什么体感更凉", "lead_conclusion": "冷感与送风协同",
        "lead_claim_id": "F1", "supporting_claim_ids": [],
        "selling_point_cluster_ids": list(cluster_ids), "reference_pattern_ids": list(reference_pattern_ids),
        "visual_proof_direction": "展示真实产品、进出风路径和接触冷感结果",
        "visual_evidence": {
            "evidence_class": "DIRECT_VERIFIED", "proof_device": "部件动作关系",
            "visible_content": ["产品", "进风口", "出风口", "冷感部件"],
            "forbidden_inventions": ["不得虚构温度数字"],
        },
        "visual_proof_contract": {
            "buyer_takeaway": "产品同时送风并提供接触冷感",
            "visual_verb": "空气从进风口进入并从出风口吹向面部，冷感部件贴近手腕",
            "primary_subject": "真实手持制冷风扇",
            "supporting_subjects": ["手部", "进风口", "出风口", "冷感部件"],
            "required_relations": ["进风口到出风口到发丝反馈", "冷感部件接触手腕"],
            "minimum_visual_payload": 3,
            "visual_specificity_anchor": ["真实轮廓", "真实按键", "真实冷感部件位置"],
            "allowed_metaphor": "少量冷色空气质感",
            "hidden_copy_test": "遮住文字仍能看出气流路径和接触冷感",
        },
        "module_spatial_structure_contract": spatial,
        "visible_copy": visible_copy,
        "copy_intent": {
            "policy": "VISUAL_FIRST_WITH_AUXILIARY_COPY",
            "why_text_is_needed": "短文字帮助识别冷感和送风两种关系而不替代画面证明。",
            "text_to_visual_bindings": [
                {"text": item["text"], "bound_to_visual": item["anchor"]} for item in visible_copy
            ],
            "hidden_copy_takeaway": "遮住文字仍能理解冷感与送风协同",
            "copy_adds": "命名并连接画面中已存在的两种价值",
        },
        "composition_family": ["hero_anchor", "structure_diagram", "immersive_scene"][min(order - 1, 2)],
        "camera_scale": "mixed",
        "text_system": {
            "primary_mode": ["offset_editorial_headline", "object_label", "scene_caption"][min(order - 1, 2)],
            "supporting_mode": "object_label",
            "anchor_target": ["product silhouette", "cooling contact part", "commuter result"][min(order - 1, 2)],
            "anchor_zone": ["top_left", "object_local", "lower_right"][min(order - 1, 2)],
            "reading_direction": ["top_to_bottom", "object_to_result", "scene_to_caption"][min(order - 1, 2)],
            "placement_logic": "Copy sits beside its named object or visible result, never in a generic floating title block.",
            "hierarchy": "Product first, proof relation second, auxiliary copy third.",
            "max_lines": 3,
            "container_style": ["open_negative_space", "micro_label", "soft_caption_panel"][min(order - 1, 2)],
            "negative_space_reservation": ["upper-left 22 percent", "local halo around contact part", "lower-right calm scene area"][min(order - 1, 2)],
            "image_text_relationship": "Every text unit is attached to a visible object, relation, or result.",
            "composition_flexibility": "CONTROLLED_REFLOW",
            "neighbor_difference": "Establishes the campaign baseline." if order == 1 else "Changes both anchor zone and reading direction from the previous screen.",
        },
        "reading_path": "产品到部件到使用反馈", "copy_density": copy_density,
        "visual_payload_density": "high", "proof_relation_strength": "strong", "commercial_energy": "high",
        "breathing_screen": False, "brand_anchor": "蓝白冷感视觉",
        "independent_logo_policy": "REQUIRED_IF_AUTHORIZED" if order == 1 else "FORBIDDEN",
        "independent_logo_source_id": "front" if order == 1 else "NONE",
        "inherited_dna_tokens": ["蓝白冷感", "高亮产品边缘"],
        "variation_from_previous": ["首屏建立母版"] if order == 1 else ["改变构图载体和文字锚点"],
        "output": {"width_px": 1440, "height_px": 1920, "safe_margin_px": 72},
    }


def session(with_reference=False):
    return {
        "input": raw_input(with_reference=with_reference), "identity": identity(),
        "planning_fact_ids": ["F1"],
        "plan": {
            "style_constitution": {
                "visual_world": "清爽商业摄影", "color_and_light": "蓝白高亮",
                "typography_and_graphics": "现代中文与对象标签", "product_rendering": "真实结构",
                "rhythm": "机制与场景交替",
            },
            "series_visual_dna": {
                "brand_anchor_system": "包装与蓝白色形", "palette_tokens": "冷蓝白",
                "typography_tokens": "现代黑体", "graphic_tokens": "弧形气流",
                "photography_tokens": "通透商业摄影", "product_tokens": "真实轮廓和材质",
                "spatial_tokens": "前景产品后景环境",
                "style_master_transfer_scope": {
                    "allowed": ["PALETTE", "LIGHTING", "PHOTOGRAPHIC_FINISH", "TYPOGRAPHY_CHARACTER", "GRAPHIC_LANGUAGE", "PRODUCT_RENDERING"],
                    "forbidden": ["LAYOUT_SKELETON", "SUBJECT_COORDINATES", "PRODUCT_OCCUPANCY", "TEXT_ZONE", "CAMERA_SCALE", "ZONE_GEOMETRY", "FULL_BLEED_TEMPLATE"],
                },
                "invariants": ["真实产品", "蓝白色彩"],
            },
        },
        "modules": [{"id": "M01", "order": 1, "plan": module(1), "accepted_asset": None}],
        "current_index": 0,
        "feedback_constraints": {"global": {"preserve": [], "must_not_regress": []}, "by_module": {}},
    }


def plan(with_reference=False, no_text=False):
    modules = [module(i, reference_pattern_ids=("RP1",) if with_reference else (), copy_density="none" if no_text else "low") for i in (1, 2, 3)]
    reference_system = {
        "coverage": [], "adopted_patterns": [],
        "anti_copy_rule": "ADAPT_VISUAL_GRAMMAR_ONLY_NEVER_COPY_BRAND_COPY_OR_ASSET",
    }
    if with_reference:
        reference_system = {
            "coverage": [{"reference_id": "R1", "disposition": "ADOPTED_GRAMMAR", "pattern_ids": ["RP1"], "reason": "适合表达气流关系"}],
            "adopted_patterns": [{
                "id": "RP1", "source_reference_ids": ["R1"], "source_unit_ids": ["R1-U1"],
                "observed_method": "主体占画面六成，气流路径从进风口连续指向出风结果",
                "adaptation_for_product": "用真实风扇结构和发丝反馈重建路径，不复制参考品牌与版式",
                "scheduled_module_ids": ["M01", "M02", "M03"],
                "do_not_copy": ["品牌", "文案", "水印", "整页版式"],
            }],
            "anti_copy_rule": "ADAPT_VISUAL_GRAMMAR_ONLY_NEVER_COPY_BRAND_COPY_OR_ASSET",
        }
    return {
        "campaign_thesis": "用真实结构和反馈证明便携冷感价值", "dominant_decision_type": "functional",
        "output_strategy": {
            "target_platform": "淘宝移动端", "profile_name": "INTERNAL_REVIEW_1440_3_4", "selection_mode": "ADAPTIVE_PLANNED",
            "module_count": 3,
            "module_count_rationale": "三个模块分别承担总价值、结构机制和通勤结果，避免一个卖点簇被塞入单屏。",
            "module_count_candidates": [
                {"count": 2, "coverage_tradeoff": "结构与场景被迫合并，画面关系拥挤", "selling_point_fit": "能覆盖事实但证明不足", "decision": "REJECTED"},
                {"count": 3, "coverage_tradeoff": "每一类证明都有独立空间且没有填充屏", "selling_point_fit": "适配总价值、机制和场景", "decision": "SELECTED"},
            ],
            "selling_point_clusters": [{
                "id": "SP1", "buyer_question": "为什么更凉", "fact_ids": ["F1"],
                "purchase_role": "MECHANISM", "separation_policy": "MERGEABLE",
                "assigned_module_ids": ["M01", "M02", "M03"],
            }],
            "merge_decisions": ["同一核心事实按总价值、机制和场景分层证明"],
            "claim_coverage": [{"claim_id": "F1", "disposition": "LEAD", "module_ids": ["M01", "M02", "M03"], "rationale": "核心事实贯穿三屏", "defer_reason_code": "NOT_DEFERRED"}],
            "aspect_ratio": {"width_units": 3, "height_units": 4, "label": "3:4"},
            "ratio_candidates": [
                {"label": "3:4", "composition_fit": "适合竖向商品、动作关系和分区证据表达。", "mobile_reading_tradeoff": "信息容量与移动端连续阅读节奏较平衡。", "decision": "SELECTED"},
                {"label": "9:16", "composition_fit": "纵向叙事空间更长但横向关系表达会变窄。", "mobile_reading_tradeoff": "单屏阅读距离更长，主体和小字更容易被压缩。", "decision": "REJECTED"},
            ],
            "canvas_width_px": 1440, "module_height_px": 1920, "safe_margin_px": 72, "slice_height_px": 1200,
            "ratio_rationale": "三比四适合竖向结构、人物动作和移动端连续阅读，也便于稳定生成。",
            "dimension_rationale": "以一千四百四十乘一千九百二十作为高清母版，交付再按后台限制切片。",
            "uniform_dimensions": True, "verification_status": "BACKEND_CONFIRMATION_REQUIRED",
        },
        "reference_expression_system": reference_system,
        "style_constitution": session()["plan"]["style_constitution"],
        "series_visual_dna": session()["plan"]["series_visual_dna"],
        "typography_rhythm": {
            "campaign_rule": "Typography follows the visual proof object; no default headline position is allowed.",
            "primary_mode_sequence": [item["text_system"]["primary_mode"] for item in modules],
            "anchor_zone_sequence": [item["text_system"]["anchor_zone"] for item in modules],
            "centered_hero_max": 1,
            "consecutive_anchor_repeat_limit": 1,
            "exceptions": [],
        },
        "modules": modules,
    }


def route_aware_plan():
    value = plan()
    value["output_strategy"]["module_count_candidates"] = [
        {
            "candidate_mode": "COMPACT_COVERAGE", "count": 2,
            "coverage_tradeoff": "事实可被提及，但痛点、机制与结果会被迫挤入同一屏。",
            "selling_point_fit": "能够覆盖核心事实但销售表达深度不足。",
            "story_obligation_fit": "只能把痛点和解决关系压缩到同一画面。",
            "primary_selling_point_depth_fit": "核心卖点只能获得总览和收口，缺少独立表达。",
            "evidence_boundary_fit": "能够保持事实边界，但证据关系会因拥挤而变弱。",
            "decision": "REJECTED",
        },
        {
            "candidate_mode": "BALANCED_EXPRESSION", "count": 3,
            "coverage_tradeoff": "分别安排总价值、痛点解决与购买收口，没有填充屏。",
            "selling_point_fit": "核心事实获得总览、独立关系和回忆强化。",
            "story_obligation_fit": "痛点与解决关系在中段明确可见。",
            "primary_selling_point_depth_fit": "核心卖点获得两个以上决策任务和独立主导模块。",
            "evidence_boundary_fit": "所有效果均回到已核验结构和使用关系。",
            "decision": "SELECTED",
        },
        {
            "candidate_mode": "FULL_SALES", "count": 4,
            "coverage_tradeoff": "可再增加使用场景，但当前单一事实会产生轻微重复。",
            "selling_point_fit": "表达更完整，但第四屏缺少新的独立事实。",
            "story_obligation_fit": "完整保留痛点、解决、结果与收口。",
            "primary_selling_point_depth_fit": "深度充足但新增模块的边际价值较低。",
            "evidence_boundary_fit": "可保持证据边界，但不应为了扩屏虚构新结果。",
            "decision": "REJECTED",
        },
    ]
    value["operating_strategy"] = {
        "intake_route": "PHOTO_TO_PRODUCT_STRATEGY", "target_buyer": "通勤人群",
        "primary_pain_id": "P1", "selected_positioning_id": "POS1",
        "core_promise": "接触冷感与送风形成双路径体感",
        "priority_claim_ids": ["F1"], "supporting_claim_ids": [],
        "assumption_boundary": "通勤痛点只指导场景，所有产品效果必须回到F1。",
    }
    value["campaign_recall_contract"] = {
        "must_remember_claim_ids": ["F1"], "first_screen_value_claim_ids": ["F1"],
        "proof_module_ids_by_claim": {"F1": ["M02"]},
        "closure_reinforcement_claim_ids": ["F1"],
        "buyer_recall_test": "看完整页后应能说出产品同时提供接触冷感和送风。",
    }
    value["selling_point_depth_contract"] = {
        "selection_policy": "SMALLEST_CANDIDATE_THAT_SATISFIES_SALES_DEPTH_NOT_MINIMUM_FACT_LISTING",
        "primary_claim_ids": ["F1"],
        "claim_depth": [{
            "claim_id": "F1", "depth_tier": "DEEP", "evidence_ceiling": "DIRECT_PROOF_AVAILABLE",
            "required_decision_jobs": ["VALUE_OVERVIEW", "DEDICATED_EXPRESSION", "RECALL"],
            "scheduled_module_ids": ["M01", "M02", "M03"], "dedicated_module_ids": ["M02"],
            "non_duplicate_rationale": "首屏承诺、中段展示双路径关系、收口强化购买理由，三个任务不同。",
            "forbidden_expansion": ["不得虚构温度数字或未提供的续航结果"],
        }],
        "compact_selection_exception": "",
    }
    carriers = ["PRODUCT_HERO", "STATE_CONTRAST", "PURCHASE_CLOSURE"]
    story_functions = ["HOOK", "PAIN_SOLUTION_COMBINED", "PURCHASE_CLOSURE"]
    for item, carrier, story_function in zip(value["modules"], carriers, story_functions):
        item["story_function"] = story_function
        item["pain_ids"] = ["P1"] if item["order"] == 2 else []
        item["value_bridge_ids"] = ["VB1"] if item["order"] in (2, 3) else []
        item["module_visual_expression_contract"] = {
            "expression_mode": "IMAGE_PLUS_COPY",
            "claim_visualizability": "VISUALIZABLE",
            "primary_visual_carrier": carrier,
            "visual_scene_sentence": "通勤热感困扰与产品气流、接触冷感部件及舒适反馈形成清楚关系。",
            "visual_semantic_payload": "遮住文字仍能看出问题状态以及产品通过两条真实路径提供解决方向。",
            "required_visual_relations": ["热感困扰到产品动作再到使用反馈"],
            "copy_responsibility": "只命名画面已经显示的两条价值路径",
            "copy_only_justification": "",
            "forbidden_substitutes": ["纯文字解释", "纯图标解释", "装饰氛围", "通用商品摆拍", "等大卡片平铺"],
        }
    value["campaign_pain_solution_contract"] = {
        "primary_pain_id": "P1", "coverage_mode": "COMBINED_PAIN_SOLUTION_MODULE",
        "pain_module_ids": ["M02"], "solution_module_ids": ["M02", "M03"],
        "value_bridge_ids": ["VB1"],
        "visible_problem_boundary": "只表现炎热通勤中的体感困扰，不虚构医疗或量化结果。",
        "pain_to_solution_transition": "由热感动作与表情进入产品气流和接触部件，再落到舒适使用反馈。",
        "exemption_basis": "NOT_APPLICABLE", "exemption_reason": "不适用，当前为正常销售页并已安排可见痛点与解决关系。",
    }
    value["campaign_visual_carrier_sequence"] = {
        "sequence": [
            {"module_id": item["id"], "primary_visual_carrier": carrier, "static_packshot_primary": item["order"] == 1,
             "expression_mode": "IMAGE_PLUS_COPY", "carrier_reason": "载体匹配本屏购买决策职责并避免连续静态商品摆拍。"}
            for item, carrier in zip(value["modules"], carriers)
        ],
        "max_consecutive_static_packshots": 1, "minimum_carrier_classes": 2,
        "campaign_rationale": "首屏建立商品，第二屏可视化痛点和解决关系，末屏完成购买闭合。",
    }
    return value


def compact_route_aware_plan():
    full = route_aware_plan()
    output_keys = (
        "module_count_rationale", "module_count_candidates", "selling_point_clusters",
        "merge_decisions", "claim_coverage", "ratio_candidates", "ratio_rationale",
        "dimension_rationale",
    )
    compact_modules = []
    for item, carrier_item in zip(full["modules"], full["campaign_visual_carrier_sequence"]["sequence"]):
        spatial = item["module_spatial_structure_contract"]
        zone_briefs = spatial.get("zone_briefs") or [zone["content"] for zone in spatial["zones"]]
        compact_modules.append({
            "id": item["id"], "duty": item["duty"], "buyer_question": item["buyer_question"],
            "lead_conclusion": item["lead_conclusion"], "lead_claim_id": item["lead_claim_id"],
            "supporting_claim_ids": item.get("supporting_claim_ids", []),
            "selling_point_cluster_ids": item["selling_point_cluster_ids"],
            "reference_pattern_ids": item.get("reference_pattern_ids", []),
            "story_function": item["story_function"], "pain_ids": item["pain_ids"],
            "value_bridge_ids": item["value_bridge_ids"],
            "visual_proof_direction": item["visual_proof_direction"],
            "visual_evidence": item["visual_evidence"],
            "proof": item["visual_proof_contract"],
            "expression": item["module_visual_expression_contract"],
            "structure": {
                "structure_family": spatial["structure_family"],
                "zone_briefs": zone_briefs,
                "structure_difference_from_previous": spatial["structure_difference_from_previous"],
                "forbidden_fallbacks": spatial["forbidden_fallbacks"],
            },
            "visible_copy": item["visible_copy"],
            "typography": {
                "primary_mode": item["text_system"]["primary_mode"],
                "anchor_target": item["text_system"]["anchor_target"],
                "anchor_zone": item["text_system"]["anchor_zone"],
            },
            "composition_family": item["composition_family"], "camera_scale": item["camera_scale"],
            "variation_from_previous": item["variation_from_previous"],
            "static_packshot_primary": carrier_item["static_packshot_primary"],
        })
    return {
        "plan_format": "COMPACT_V1_1",
        "campaign_thesis": full["campaign_thesis"],
        "dominant_decision_type": full["dominant_decision_type"],
        "operating_strategy": full["operating_strategy"],
        "campaign_recall_contract": full["campaign_recall_contract"],
        "selling_point_depth_contract": full["selling_point_depth_contract"],
        "campaign_pain_solution_contract": full["campaign_pain_solution_contract"],
        "output_strategy": {key: full["output_strategy"][key] for key in output_keys},
        "reference_expression_system": full["reference_expression_system"],
        "style_constitution": full["style_constitution"],
        "series_visual_dna": full["series_visual_dna"],
        "modules": compact_modules,
    }


def compact_v12_plan():
    value = compact_route_aware_plan()
    value["plan_format"] = "COMPACT_V1_2"
    base = value["modules"]
    m01, m02, old_m03 = copy.deepcopy(base[0]), copy.deepcopy(base[1]), copy.deepcopy(base[2])
    m03 = copy.deepcopy(m02); m03["id"] = "M03"
    m04 = copy.deepcopy(m02); m04["id"] = "M04"
    m05 = copy.deepcopy(old_m03); m05["id"] = "M05"
    modules = [m01, m02, m03, m04, m05]
    archetypes = ["BENEFIT_OVERVIEW", "PAIN_TO_SOLUTION_BRIDGE", "DEDICATED_BENEFIT_PROOF", "USE_SCOPE_MATRIX", "PURCHASE_CLOSURE"]
    functions = ["HOOK", "PAIN_SOLUTION_COMBINED", "SOLUTION_PROOF", "USE_OR_RESULT", "PURCHASE_CLOSURE"]
    carriers = ["PRODUCT_HERO", "STATE_CONTRAST", "PROCESS_PATH", "USE_SCENE", "PURCHASE_CLOSURE"]
    anchors = ["top_left", "object_local", "center_right", "lower_left", "lower_right"]
    text_modes = ["centered_hero_headline", "object_label", "directional_annotation", "scene_caption", "closing_summary"]
    for index, (module, archetype, story_function, carrier, anchor) in enumerate(zip(modules, archetypes, functions, carriers, anchors), start=1):
        module["visual_archetype"] = archetype
        module["story_function"] = story_function
        module["pain_ids"] = ["P1"] if index == 2 else []
        module["value_bridge_ids"] = ["VB1"] if index >= 2 else []
        module["expression"]["primary_visual_carrier"] = carrier
        module["typography"]["anchor_zone"] = anchor
        module["typography"]["primary_mode"] = text_modes[index - 1]
        module["composition_family"] = ["hero", "pain_bridge", "macro_proof", "use_matrix", "purchase_closure"][index - 1]
        module["variation_from_previous"] = ["首屏建立价值舞台"] if index == 1 else [f"第{index}屏改变证据关系与空间重心"]
        module["static_packshot_primary"] = index == 1
    m03["structure"].update({"structure_family": "MACRO_DIAGRAM", "zone_briefs": ["产品作用主体", "局部主证据"]})
    m04["structure"].update({"structure_family": "SELECTION_MATRIX", "zone_briefs": ["使用结果主场景", "不同使用范围", "适用结论"]})
    m05["structure"].update({"structure_family": "FRAMED_LIFESTYLE_PLUS_CARDS", "zone_briefs": ["完整商品结果场景", "核心利益回忆", "购买收口小场景"]})
    value["modules"] = modules
    value["user_selling_point_coverage_ledger"] = []
    value["campaign_recall_contract"].update({
        "proof_module_ids_by_claim": {"F1": ["M02", "M03", "M04"]},
    })
    depth = value["selling_point_depth_contract"]["claim_depth"][0]
    depth.update({
        "priority": "PRIMARY",
        "required_decision_jobs": ["VALUE_OVERVIEW", "DEDICATED_EXPRESSION", "RESULT_OR_EXPERIENCE", "RECALL"],
        "scheduled_module_ids": ["M01", "M03", "M04", "M05"],
        "dedicated_module_ids": ["M03"],
        "module_jobs": [
            {"module_id": "M01", "job": "VALUE_OVERVIEW"},
            {"module_id": "M03", "job": "DEDICATED_EXPRESSION"},
            {"module_id": "M04", "job": "RESULT_OR_EXPERIENCE"},
            {"module_id": "M05", "job": "RECALL"},
        ],
    })
    strategy = value["output_strategy"]
    strategy["module_count_candidates"] = [
        {"candidate_mode": "COMPACT_COVERAGE", "count": 4, "coverage_tradeoff": "只能提及全部信息，一级卖点缺少完整使用结果。", "selling_point_fit": "一级卖点只有总览和独立表达。", "story_obligation_fit": "保留痛点桥接但节奏拥挤。", "primary_selling_point_depth_fit": "缺少完整四段式履约。", "evidence_boundary_fit": "事实安全但说服不足。", "decision": "REJECTED"},
        {"candidate_mode": "BALANCED_EXPRESSION", "count": 5, "coverage_tradeoff": "完整覆盖总览、痛点、独立证明、使用结果与收口。", "selling_point_fit": "一级卖点完成四段式履约。", "story_obligation_fit": "痛点先于证明且收口完整。", "primary_selling_point_depth_fit": "满足深度门槛。", "evidence_boundary_fit": "全部表达保持在事实证据内。", "decision": "SELECTED"},
        {"candidate_mode": "FULL_SALES", "count": 6, "coverage_tradeoff": "可增加辅助场景但当前事实可能重复。", "selling_point_fit": "深度充足但边际价值低。", "story_obligation_fit": "完整但略冗长。", "primary_selling_point_depth_fit": "超过必要深度。", "evidence_boundary_fit": "仍可安全表达。", "decision": "REJECTED"},
    ]
    strategy["module_count_formula"] = {
        "base_narrative_jobs": 3, "primary_depth_expansion": 2, "supporting_jobs": 0,
        "shared_proof_savings": 0, "computed_balanced_minimum": 5,
        "shared_proof_rationale": "单一一级卖点不计算共享节省。",
    }
    strategy["selling_point_clusters"][0]["assigned_module_ids"] = [m["id"] for m in modules]
    strategy["claim_coverage"][0]["module_ids"] = [m["id"] for m in modules]
    return value


def fail_judgment(module_record, issue="Typography is not attached to the planned visual object."):
    planned = module_record["plan"]
    presence_policy = planned.get("module_visual_expression_contract", {}).get("product_presence_policy", "REQUIRED_DOMINANT")
    observed_presence = {
        "REQUIRED_DOMINANT": "DOMINANT",
        "REQUIRED_SUPPORTING": "SUPPORTING",
        "IDENTITY_TOKEN_ONLY": "IDENTITY_TOKEN_ONLY",
        "ABSENT_PREFERRED": "ABSENT",
        "ABSENT_ALLOWED": "ABSENT",
        "OPTIONAL": "SUPPORTING",
    }.get(presence_policy, "DOMINANT")
    checks = {name: {"pass": True, "visible_evidence": "visible"} for name in CHECKS}
    checks["typography_contract_match"] = {"pass": False, "visible_evidence": issue}
    return {
        "module_id": module_record["id"],
        "status": "MATERIAL_FAIL",
        "audit_complete": True,
        "checks": checks,
        "observations": {
            "ocr_text": [item["text"] for item in planned["visible_copy"]],
            "unauthorized_ocr_text": [],
            "forbidden_text_hits": [],
            "effective_visual_payloads": ["product", "airflow", "contact result"],
            "visible_proof_relations": ["product action visibly causes a result"],
            "hidden_copy_observation": "The product-action-result relation remains understandable when copy is hidden.",
            "product_specificity_observation": "Verified product silhouette and controls remain recognizable.",
            "planned_elements_visible": ["product", "airflow", "contact result"],
            "planned_elements_missing": [],
            "reference_pattern_observation": "The planned expression grammar is visible.",
            "copy_binding_observation": "Copy exists but is not attached strongly enough to its visual target.",
            "typography_primary_mode_observed": planned["text_system"]["primary_mode"],
            "typography_anchor_zone_observed": planned["text_system"]["anchor_zone"],
            "typography_anchor_target_observation": "The intended visual target is identifiable.",
            "typography_hierarchy_observation": "Product remains more prominent than copy.",
            "typography_neighbor_difference_observation": "Typography differs from the neighboring screen.",
            "product_prominence_percent": 42,
            "product_presence_observed": observed_presence,
            "unplanned_full_product_seen": False,
            "identity_binding_without_product_observed": "The approved product-specific material, action and campaign visual DNA remain visible.",
            "headline_rank": 2,
            "evidence_is_primary_visual": True,
            "depth_layers": 3,
            "type_roles_seen": 3,
            "unequal_information_groups_seen": 3,
            "visual_tension_seen": True,
            "mobile_scan_order": ["headline", "proof", "product"],
            "commercial_closure_visible": True,
            "background_competition": "LOW",
            "independent_brand_logo_count": 1 if module_record["order"] == 1 else 0,
            "independent_brand_logo_source_fidelity": "MATCHES_AUTHORIZED_SOURCE" if module_record["order"] == 1 else "NOT_APPLICABLE",
            "independent_brand_logo_observation": "M01 has one source-faithful independent logo." if module_record["order"] == 1 else "No independent logo is visible.",
            "visual_carrier_observed": planned.get("module_visual_expression_contract", {}).get("primary_visual_carrier", "PRODUCT_HERO"),
            "claim_visible_without_copy": "FULL",
            "copy_dependency": "LOW",
            "pain_state_visible": True,
            "pain_consequence_visible": True,
            "product_solution_bridge_visible": True,
            "action_or_state_change_visible": True,
            "icon_only_dependency": False,
            "static_packshot_only": False,
            "generic_product_swap_possible": False,
            "visual_semantic_observation": "The product-specific action and result are visible without copy.",
            "structure_family_observed": planned["module_spatial_structure_contract"]["structure_family"],
            "structural_zone_count": planned["module_spatial_structure_contract"]["zone_count"],
            "structural_relationship_observed": planned["module_spatial_structure_contract"]["structural_relationship"],
            "full_bleed_single_scene": planned["module_spatial_structure_contract"]["structural_relationship"] == "FULL_BLEED_SINGLE_SCENE",
            "dominant_zone_count_observed": planned["module_spatial_structure_contract"]["dominant_zone_count"],
            "secondary_panel_count_observed": planned["module_spatial_structure_contract"]["secondary_panel_count"],
            "mini_scene_count_observed": planned["module_spatial_structure_contract"]["mini_scene_count"],
            "previous_structure_similarity": "NOT_APPLICABLE" if module_record["order"] == 1 else "LOW",
            "same_full_bleed_template_as_previous": False,
            "spatial_structure_observation": "The approved meaning zones and their relationship are visibly distinct.",
        },
        "material_failures": [{
            "check": "typography_contract_match",
            "visible_evidence": issue,
            "root_cause": "Typography was composed as a detached layer instead of following the approved anchor.",
            "required_change": "Rebind typography to the approved visual object while preserving passed proof layers.",
        }],
        "passed_layers": ["identity", "facts", "visual proof"],
    }


class RegressionTests(unittest.TestCase):
    def test_v11_compact_plan_is_expanded_and_records_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, identity_path = root / "input.json", root / "identity.json"
            plan_path, session_path = root / "plan.json", root / "session.json"
            compact = compact_route_aware_plan()
            input_path.write_text(json.dumps(route_aware_input(), ensure_ascii=False), encoding="utf-8")
            identity_path.write_text(json.dumps(identity(), ensure_ascii=False), encoding="utf-8")
            plan_path.write_text(json.dumps(compact, ensure_ascii=False), encoding="utf-8")

            harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())
            harness.cmd_lock_identity(type("Args", (), {"session": str(session_path), "identity": str(identity_path)})())
            result = harness.cmd_compile_plan(type("Args", (), {"session": str(session_path), "plan": str(plan_path)})())
            saved = json.loads(session_path.read_text(encoding="utf-8"))

            self.assertEqual(saved["version"], "2.1.0")
            self.assertEqual(saved["state"], "AWAITING_PLAN_APPROVAL")
            self.assertEqual(saved["plan"]["modules"][0]["independent_logo_policy"], "REQUIRED_IF_AUTHORIZED")
            self.assertIn("campaign_visual_carrier_sequence", saved["plan"])
            self.assertIn("typography_rhythm", saved["plan"])
            self.assertEqual(saved["planning_metrics"]["authoring_format"], "COMPACT_V1_1")
            self.assertLess(saved["planning_metrics"]["authoring_plan_bytes"], saved["planning_metrics"]["compiled_plan_bytes"])
            self.assertIn("planning_metrics", result)
            self.assertIn("Skill v2.1.0", result["approval_markdown"])

    def test_v11_route_aware_count_comparison_requires_all_three_modes(self):
        current = session()
        current["input"] = route_aware_input()
        value = route_aware_plan()
        value["output_strategy"]["module_count_candidates"] = value["output_strategy"]["module_count_candidates"][:2]
        with self.assertRaisesRegex(HarnessError, "exactly compact"):
            harness.validate_plan(current, value)

    def test_unverified_adaptive_profile_rejects_900x1200(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = raw_input()
            value["platform_profile"].update({
                "profile_name": "legacy_900_3_4",
                "canvas_width_px": 900,
                "module_height_px": 1200,
                "safe_margin_px": 45,
            })
            input_path, session_path = root / "input.json", root / "session.json"
            input_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(HarnessError, "1440x1920"):
                harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())

    def test_explicit_user_profile_is_not_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = raw_input()
            value["platform_profile"].update({
                "profile_name": "USER_APPROVED_900_3_4",
                "selection_mode": "USER_SPECIFIED",
                "canvas_width_px": 900,
                "module_height_px": 1200,
                "safe_margin_px": 45,
            })
            input_path, session_path = root / "input.json", root / "session.json"
            input_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            result = harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())
            self.assertEqual(result["state"], "AWAITING_IDENTITY")

    def test_approval_packet_contains_mandatory_spatial_structure(self):
        packet = harness._approval_packet(plan())
        self.assertIn("空间结构", packet["required_storyboard_columns"])
        self.assertEqual(packet["decision"]["design_dimensions_px"], "1440x1920")
        self.assertTrue(all(item["空间结构"] for item in packet["storyboard"]))

    def test_legacy_heavy_rhythm_ledgers_are_rejected_together(self):
        value = plan()
        value["visual_performance_rhythm"] = {"legacy": True}
        value["spatial_structure_rhythm"] = {"legacy": True}
        with self.assertRaisesRegex(HarnessError, "visual_performance_rhythm, spatial_structure_rhythm"):
            harness.validate_plan(session(), value)

    def test_v1_approval_markdown_contains_all_mandatory_tables(self):
        current = session()
        current["plan"] = plan()
        markdown = harness._approval_markdown(current)
        self.assertIn("| 采用路由 | 确认的产品事实 |", markdown)
        self.assertIn("| 屏数方案 | 屏数 | 一级卖点深度 |", markdown)
        self.assertIn("| 比例方案 | 单屏比例 | 构图适配 |", markdown)
        self.assertIn("| 模块 | 页面职责 | 主结论 | 画面如何证明 | 商品出镜策略 | 空间结构 |", markdown)
        self.assertNotIn("构图与景别", markdown)

    def test_unverified_adaptive_plan_rejects_ad_hoc_4_by_5_candidate(self):
        value = plan()
        value["output_strategy"]["ratio_candidates"][1]["label"] = "4:5"
        with self.assertRaisesRegex(HarnessError, "controlled internal options 3:4 and 9:16"):
            harness.validate_plan(session(), value)

    def test_repeated_module_performance_payloads_exceed_lightweight_budget(self):
        value = plan()
        for item in value["modules"]:
            item["module_visual_performance_contract"] = performance_contract(item["order"])
            item["performance_override_reason"] = "该屏确有无法由普通职责推导的特殊视觉强度与层级要求。"
        with self.assertRaisesRegex(HarnessError, "lightweight planning allows at most"):
            harness.validate_plan(session(), value)

    def test_internal_evidence_provenance_cannot_become_page_duty(self):
        value = plan()
        value["modules"][1]["duty"] = "包装可见宣称与来源边界"
        with self.assertRaisesRegex(HarnessError, "leaks internal evidence/compliance provenance"):
            harness.validate_plan(session(), value)

    def test_trust_only_screen_requires_independent_documented_evidence(self):
        value = plan()
        value["modules"][1]["story_function"] = "TRUST_OR_RISK_REMOVAL"
        with self.assertRaisesRegex(HarnessError, "without independent documented evidence"):
            harness.validate_plan(session(), value)

    def test_record_generation_normalizes_wrong_ratio_without_stretching(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "wrong-ratio.png"
            Image.new("RGB", (881, 1785), "navy").save(source)
            session_path = root / "session.json"
            session_path.write_text(json.dumps({
                "version": "0.8.0",
                "state": "AWAITING_GENERATED_MODULE",
                "active_token": "token-1",
                "current_index": 0,
                "modules": [{
                    "id": "M01", "status": "GENERATING", "cycle_id": 1,
                    "cycle_attempt_count": 0, "attempts": [], "plan": module(1),
                }],
            }, ensure_ascii=False), encoding="utf-8")

            harness.cmd_record_generation(type("Args", (), {
                "session": str(session_path), "token": "token-1", "image": str(source),
            })())
            saved = json.loads(session_path.read_text(encoding="utf-8"))
            attempt = saved["modules"][0]["attempts"][0]
            self.assertEqual((attempt["source_width_px"], attempt["source_height_px"]), (881, 1785))
            self.assertEqual((attempt["width_px"], attempt["height_px"]), (1440, 1920))
            self.assertEqual(attempt["format_normalization"], "HYBRID_CROP_WITH_BLURRED_EDGE_EXTENSION")
            self.assertAlmostEqual(attempt["bounded_crop_fraction"], 0.12, places=2)
            with Image.open(attempt["image"]) as normalized:
                self.assertEqual(normalized.size, (1440, 1920))
            self.assertEqual(saved["state"], "AWAITING_PIXEL_AUDIT")

    def test_pixel_audit_allows_small_non_claim_pain_scene_caption_as_advisory(self):
        planned = route_aware_plan()["modules"][1]
        module_record = {"id": "M02", "order": 2, "plan": planned}
        value = fail_judgment(module_record)
        value["status"] = "PASS"
        value["checks"] = {name: {"pass": True, "visible_evidence": "visible"} for name in CHECKS}
        value["material_failures"] = []
        extra = "潮湿衣物容易积味"
        value["observations"]["ocr_text"].append(extra)
        value["observations"]["unauthorized_ocr_text"] = [extra]
        value["observations"]["advisory_context_copy"] = [extra]
        value["observations"]["advisory_context_copy_observation"] = "The short caption only names the visible damp-clothes situation and adds no product claim."
        validate_module_judgment(value, module_record)

    def test_pixel_audit_keeps_claim_bearing_extra_copy_material(self):
        planned = route_aware_plan()["modules"][1]
        module_record = {"id": "M02", "order": 2, "plan": planned}
        value = fail_judgment(module_record)
        value["status"] = "PASS"
        value["checks"] = {name: {"pass": True, "visible_evidence": "visible"} for name in CHECKS}
        value["material_failures"] = []
        extra = "99.99%除菌"
        value["observations"]["ocr_text"].append(extra)
        value["observations"]["advisory_context_copy"] = [extra]
        value["observations"]["advisory_context_copy_observation"] = "This is presented as a visible extra caption."
        with self.assertRaisesRegex(HarnessError, "cannot be advisory copy"):
            validate_module_judgment(value, module_record)

    def test_pixel_audit_allows_consecutive_step_indices_as_advisory_marks(self):
        planned = route_aware_plan()["modules"][1]
        module_record = {"id": "M02", "order": 2, "plan": planned}
        value = fail_judgment(module_record)
        value["status"] = "PASS"
        value["checks"] = {name: {"pass": True, "visible_evidence": "visible"} for name in CHECKS}
        value["material_failures"] = []
        marks = ["01", "02", "03"]
        value["observations"]["ocr_text"].extend(marks)
        value["observations"]["unauthorized_ocr_text"] = marks
        value["observations"]["advisory_visual_marks"] = marks
        value["observations"]["advisory_visual_marks_observation"] = "The three small indices only organize the visible brushing sequence."
        validate_module_judgment(value, module_record)

    def test_pixel_audit_allows_stylized_molecule_like_rhetoric_but_rejects_evidence_impersonation(self):
        planned = route_aware_plan()["modules"][1]
        module_record = {"id": "M02", "order": 2, "plan": planned}
        value = fail_judgment(module_record)
        value["status"] = "PASS"
        value["checks"] = {name: {"pass": True, "visible_evidence": "visible"} for name in CHECKS}
        value["material_failures"] = []
        value["observations"]["conceptual_visualization_risk"] = "MINOR_NON_MISLEADING_VARIATION"
        value["observations"]["conceptual_visualization_observation"] = "Unlabeled translucent nodes are clearly decorative and do not claim an exact structure."
        validate_module_judgment(value, module_record)
        value["observations"]["conceptual_visualization_risk"] = "MISLEADING_EVIDENCE"
        with self.assertRaisesRegex(HarnessError, "impersonate exact structure"):
            validate_module_judgment(value, module_record)

    def test_prompt_preserves_non_claim_sequence_markers_and_conceptual_graphics(self):
        current = session()
        planned = route_aware_plan()["modules"][1]
        planned["module_visual_expression_contract"]["visualization_mode"] = "CONCEPTUAL_NON_DIAGNOSTIC"
        current["modules"][0] = {"id": "M02", "order": 2, "plan": planned, "accepted_asset": None}
        prompt = compile_prompt(current, current["modules"][0])
        self.assertIn("01/02/03", prompt)
        self.assertIn("不代表具体分子结构", prompt)

    def test_assembly_rejects_correct_width_with_wrong_height(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "wrong-height.png"
            Image.new("RGB", (1440, 1800), "white").save(source)
            with self.assertRaisesRegex(HarnessError, "1440x1920"):
                assemble_vertical([str(source)], str(root / "long.png"), profile())

    def test_photo_only_route_builds_operating_strategy_without_user_selling_points(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, session_path = root / "input.json", root / "session.json"
            input_path.write_text(json.dumps(route_aware_input(), ensure_ascii=False), encoding="utf-8")
            harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())
            saved = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["input"]["intake_route"], "PHOTO_TO_PRODUCT_STRATEGY")
            saved["identity"] = identity()
            harness.validate_plan(saved, route_aware_plan())

    def test_route_aware_sales_plan_requires_visible_pain_solution_contract(self):
        current = session()
        current["input"] = route_aware_input()
        value = route_aware_plan()
        del value["campaign_pain_solution_contract"]
        with self.assertRaisesRegex(HarnessError, "campaign_pain_solution_contract"):
            harness.validate_plan(current, value)

    def test_visualizable_claim_cannot_be_copy_only(self):
        current = session()
        current["input"] = route_aware_input()
        value = route_aware_plan()
        expression = value["modules"][1]["module_visual_expression_contract"]
        expression["expression_mode"] = "COPY_ONLY_JUSTIFIED"
        expression["copy_only_justification"] = "希望用文字说明节省视觉制作空间，但核心关系本身可以画面表达。"
        value["campaign_visual_carrier_sequence"]["sequence"][1]["expression_mode"] = "COPY_ONLY_JUSTIFIED"
        with self.assertRaisesRegex(HarnessError, "copy-only expression"):
            harness.validate_plan(current, value)

    def test_sales_page_must_compare_compact_balanced_and_full_candidates(self):
        current = session()
        current["input"] = route_aware_input()
        value = route_aware_plan()
        value["output_strategy"]["module_count_candidates"] = value["output_strategy"]["module_count_candidates"][:2]
        with self.assertRaisesRegex(HarnessError, "compact, balanced and full-sales"):
            harness.validate_plan(current, value)

    def test_deep_selling_point_cannot_be_counted_as_sold_through_on_one_screen(self):
        current = session()
        current["input"] = route_aware_input()
        value = route_aware_plan()
        depth = value["selling_point_depth_contract"]["claim_depth"][0]
        depth["required_decision_jobs"] = ["DEDICATED_EXPRESSION"]
        depth["scheduled_module_ids"] = ["M02"]
        with self.assertRaisesRegex(HarnessError, "DEEP selling point"):
            harness.validate_plan(current, value)

    def test_packaging_only_claim_cannot_expand_into_invented_mechanism(self):
        current = session()
        current["input"] = route_aware_input()
        value = route_aware_plan()
        depth = value["selling_point_depth_contract"]["claim_depth"][0]
        depth["evidence_ceiling"] = "PACKAGING_CLAIM_ONLY"
        depth["required_decision_jobs"] = ["DEDICATED_EXPRESSION", "MECHANISM_OR_REASON"]
        with self.assertRaisesRegex(HarnessError, "cannot be expanded into a mechanism"):
            harness.validate_plan(current, value)

    def test_user_selling_point_route_cannot_drop_supplied_points(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, session_path = root / "input.json", root / "session.json"
            value = route_aware_input("USER_SELLING_POINT_LED")
            value["user_supplied_selling_points"] = []
            input_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(HarnessError, "requires at least one concrete"):
                harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())

    def test_recall_contract_rejects_identity_only_closure(self):
        current = session()
        current["input"] = route_aware_input()
        value = route_aware_plan()
        value["modules"][-1]["lead_claim_id"] = "NO_FACT_CLOSURE"
        with self.assertRaisesRegex(HarnessError, "claim F1 is assigned to M03"):
            harness.validate_plan(current, value)

    def test_reference_board_must_be_decomposed_and_methods_derived_from_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, session_path = root / "input.json", root / "session.json"
            value = raw_input(with_reference=True)
            value["reference_materials"][0]["analyzed_units"] = []
            input_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(HarnessError, "decomposed"):
                harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())

            value = raw_input(with_reference=True)
            value["reference_materials"][0]["observed_expression_methods"] = ["只有泛化风格标签"]
            input_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(HarnessError, "derived exactly"):
                harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())

    def test_material_conflict_blocks_planning_until_batched_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, session_path = root / "input.json", root / "session.json"
            input_path.write_text(json.dumps(raw_input(with_conflict=True), ensure_ascii=False), encoding="utf-8")
            harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())
            saved = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "AWAITING_CONFLICT_RESOLUTION")
            identity_path = root / "identity.json"
            identity_path.write_text(json.dumps(identity(), ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(HarnessError):
                harness.cmd_lock_identity(type("Args", (), {"session": str(session_path), "identity": str(identity_path)})())
            resolution_path = root / "resolution.json"
            resolution_path.write_text(json.dumps({
                "confirmation_text": "以包装标注5000mAh为准",
                "resolutions": [{"conflict_id": "C1", "retained_fact_ids": ["F3"], "rejected_fact_ids": ["F2"]}],
            }, ensure_ascii=False), encoding="utf-8")
            harness.cmd_resolve_conflicts(type("Args", (), {"session": str(session_path), "resolution": str(resolution_path)})())
            saved = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "AWAITING_IDENTITY")
            self.assertEqual(saved["planning_fact_ids"], ["F1", "F3"])

    def test_screen_count_must_be_selected_from_distinct_selling_point_candidates(self):
        value = plan()
        value["output_strategy"]["module_count_candidates"][0]["count"] = 3
        with self.assertRaisesRegex(HarnessError, "distinct counts"):
            harness.validate_plan(session(), value)

    def test_normal_sales_screen_cannot_turn_visual_first_into_no_text(self):
        with self.assertRaisesRegex(HarnessError, "text-free"):
            harness.validate_plan(session(), plan(no_text=True))

    def test_analyzed_reference_must_feed_concrete_scheduled_expression_pattern(self):
        current = session(with_reference=True)
        ignored = plan(with_reference=False)
        with self.assertRaisesRegex(HarnessError, "explicitly adopted or rejected"):
            harness.validate_plan(current, ignored)
        harness.validate_plan(current, plan(with_reference=True))

    def test_compiled_prompt_preserves_plan_reference_and_auxiliary_copy_bindings(self):
        current = session(with_reference=True)
        current["plan"] = plan(with_reference=True)
        current["modules"] = [{"id": "M01", "order": 1, "plan": current["plan"]["modules"][0], "accepted_asset": None}]
        prompt = compile_prompt(current, current["modules"][0])
        prompt_preflight(prompt)
        self.assertIn("REFERENCE EXPRESSION GRAMMAR TO ADAPT", prompt)
        self.assertIn("COPY IS AUXILIARY, NOT ABSENT", prompt)
        self.assertIn("bind each approved text unit", prompt)
        self.assertIn("TYPOGRAPHY LAYOUT CONTRACT", prompt)
        self.assertIn("Place the primary group in zone: top_left", prompt)
        self.assertIn("【视觉表现合同】", prompt)
        self.assertIn("【画面空间结构合同】", prompt)
        self.assertNotIn("对应包装正标位置", prompt)
        copy_section = prompt.split("仅允许出现以下宣传文字：", 1)[1].split("文字排版要顺应", 1)[0]
        self.assertNotIn("贴合", copy_section)
        self.assertNotIn("承担", copy_section)
        self.assertIn("商品视觉占比不得低于约 30%", prompt)
        self.assertIn("首屏必须恰好出现一次清晰、独立的品牌Logo", prompt)
        self.assertIn("当前商品参考图 front", prompt)

    def test_spatial_rhythm_rejects_consecutive_full_bleed_single_scenes(self):
        current = session()
        value = plan()
        second = value["modules"][1]["module_spatial_structure_contract"]
        second.update({
            "structure_family": "FULL_BLEED_HERO",
            "zone_count": 1,
            "zones": [{"role": "单一场景", "geometry": "全幅连续摄影场景", "content": "商品与通勤环境", "visual_weight_percent": 100}],
            "structural_relationship": "FULL_BLEED_SINGLE_SCENE",
            "full_bleed_single_scene_allowed": True,
            "dominant_zone_count": 1,
            "secondary_panel_count": 0,
        })
        with self.assertRaisesRegex(HarnessError, "full-bleed single-scene repetition"):
            harness.validate_plan(current, value)

    def test_pixel_audit_rejects_composite_structure_collapsing_to_full_bleed(self):
        planned = module(2)
        module_record = {"id": "M02", "order": 2, "plan": planned}
        value = fail_judgment(module_record)
        value["status"] = "PASS"
        value["checks"] = {name: {"pass": True, "visible_evidence": "visible"} for name in CHECKS}
        value["material_failures"] = []
        value["observations"].update({
            "structure_family_observed": "FULL_BLEED_HERO",
            "structural_zone_count": 1,
            "structural_relationship_observed": "FULL_BLEED_SINGLE_SCENE",
            "full_bleed_single_scene": True,
            "secondary_panel_count_observed": 0,
        })
        with self.assertRaisesRegex(HarnessError, "spatial structure family|collapsed into one full-bleed"):
            validate_module_judgment(value, module_record)

    def test_series_master_is_omitted_when_current_spatial_grammar_differs(self):
        current = session()
        current["modules"] = [
            {"id": "M01", "order": 1, "plan": module(1), "accepted_asset": "m01.png"},
            {"id": "M02", "order": 2, "plan": module(2), "accepted_asset": None},
        ]
        current["current_index"] = 1
        references, master = harness.generation_references(current)
        self.assertIsNone(master)
        self.assertNotIn("m01.png", references)

    def test_typography_rhythm_rejects_repeated_default_anchor_and_sequence_drift(self):
        value = plan()
        value["typography_rhythm"]["anchor_zone_sequence"][1] = "top_left"
        with self.assertRaisesRegex(HarnessError, "exactly match module order"):
            harness.validate_plan(session(), value)

        value = plan()
        value["modules"][1]["text_system"]["anchor_zone"] = "top_left"
        value["typography_rhythm"]["anchor_zone_sequence"][1] = "top_left"
        with self.assertRaisesRegex(HarnessError, "repeats a composition/typography placement pair|too many consecutive"):
            harness.validate_plan(session(), value)

    def test_module_feedback_is_scoped_and_does_not_pollute_later_prompts(self):
        current = session()
        current["plan"] = plan()
        current["modules"] = [
            {"id": item["id"], "order": item["order"], "plan": item, "accepted_asset": None}
            for item in current["plan"]["modules"]
        ]
        current["feedback_constraints"] = {
            "global": {"preserve": ["GLOBAL_PRODUCT_IDENTITY"], "must_not_regress": []},
            "by_module": {
                "M01": {"preserve": [], "must_not_regress": ["M01_ONLY_DO_NOT_CENTER"]},
                "M02": {"preserve": ["M02_KEEP_OBJECT_LABEL"], "must_not_regress": []},
            },
        }
        prompt = compile_prompt(current, current["modules"][1])
        self.assertIn("GLOBAL_PRODUCT_IDENTITY", prompt)
        self.assertIn("M02_KEEP_OBJECT_LABEL", prompt)
        self.assertNotIn("M01_ONLY_DO_NOT_CENTER", prompt)

    def test_pixel_audit_hard_fails_when_approved_plan_elements_are_missing(self):
        current = session()
        module_record = current["modules"][0]
        checks = {name: {"pass": True, "visible_evidence": "可见"} for name in CHECKS}
        judgment = {
            "module_id": "M01", "status": "PASS", "audit_complete": True, "checks": checks,
            "observations": {
                "ocr_text": ["一握即凉", "强风×冷感"], "unauthorized_ocr_text": [], "forbidden_text_hits": [],
                "effective_visual_payloads": ["产品", "气流", "手腕接触"],
                "visible_proof_relations": ["进风到出风到发丝反馈"],
                "hidden_copy_observation": "遮字仍可理解", "product_specificity_observation": "真实冷感部件可识别",
                "planned_elements_visible": ["真实产品", "气流路径"],
                "planned_elements_missing": ["冷感部件接触手腕"],
                "reference_pattern_observation": "无参考要求", "copy_binding_observation": "短文案贴近对应部件",
                "typography_primary_mode_observed": "offset_editorial_headline",
                "typography_anchor_zone_observed": "top_left",
                "typography_anchor_target_observation": "Headline attaches to the product silhouette.",
                "typography_hierarchy_observation": "Product remains primary; copy is auxiliary.",
                "typography_neighbor_difference_observation": "Establishes the campaign baseline.",
                "product_prominence_percent": 42,
                "headline_rank": 2,
                "evidence_is_primary_visual": True,
                "depth_layers": 3,
                "type_roles_seen": 3,
                "unequal_information_groups_seen": 3,
                "visual_tension_seen": True,
                "mobile_scan_order": ["核心标题", "功效证据", "商品"],
                "commercial_closure_visible": True,
                "background_competition": "LOW",
                "independent_brand_logo_count": 1,
                "independent_brand_logo_source_fidelity": "MATCHES_AUTHORIZED_SOURCE",
                "independent_brand_logo_observation": "首屏有一个与front来源一致的独立品牌标志。",
                "visual_carrier_observed": "PRODUCT_HERO",
                "claim_visible_without_copy": "FULL", "copy_dependency": "LOW",
                "pain_state_visible": True, "pain_consequence_visible": True,
                "product_solution_bridge_visible": True, "action_or_state_change_visible": True,
                "icon_only_dependency": False, "static_packshot_only": False,
                "generic_product_swap_possible": False,
                "visual_semantic_observation": "真实商品、气流和接触反馈仍可见。",
                "structure_family_observed": "FULL_BLEED_HERO",
                "structural_zone_count": 1,
                "structural_relationship_observed": "FULL_BLEED_SINGLE_SCENE",
                "full_bleed_single_scene": True,
                "dominant_zone_count_observed": 1,
                "secondary_panel_count_observed": 0,
                "mini_scene_count_observed": 0,
                "previous_structure_similarity": "NOT_APPLICABLE",
                "same_full_bleed_template_as_previous": False,
                "spatial_structure_observation": "首屏为计划中的单一英雄舞台。",
            },
            "material_failures": [], "passed_layers": [],
        }
        with self.assertRaisesRegex(HarnessError, "omitted approved plan elements"):
            validate_module_judgment(judgment, module_record)

    def test_pixel_audit_hard_fails_when_product_prominence_misses_contract(self):
        module_record = session()["modules"][0]
        value = fail_judgment(module_record)
        value["status"] = "PASS"
        value["checks"] = {name: {"pass": True, "visible_evidence": "可见"} for name in CHECKS}
        value["material_failures"] = []
        value["observations"]["product_prominence_percent"] = 18
        with self.assertRaisesRegex(HarnessError, "Product prominence"):
            validate_module_judgment(value, module_record)

    def test_first_screen_logo_is_a_deterministic_hard_gate(self):
        module_record = session()["modules"][0]
        value = fail_judgment(module_record)
        value["status"] = "PASS"
        value["checks"] = {name: {"pass": True, "visible_evidence": "visible"} for name in CHECKS}
        value["material_failures"] = []
        value["observations"]["independent_brand_logo_count"] = 0
        value["observations"]["independent_brand_logo_source_fidelity"] = "NOT_APPLICABLE"
        with self.assertRaisesRegex(HarnessError, "exactly one independent brand logo"):
            validate_module_judgment(value, module_record)

    def test_pixel_audit_rejects_text_and_icons_substituting_for_visual_meaning(self):
        planned = route_aware_plan()["modules"][1]
        module_record = {"id": "M02", "order": 2, "plan": planned}
        value = fail_judgment(module_record)
        value["status"] = "PASS"
        value["checks"] = {name: {"pass": True, "visible_evidence": "visible"} for name in CHECKS}
        value["material_failures"] = []
        value["observations"].update({
            "visual_carrier_observed": "STATE_CONTRAST",
            "claim_visible_without_copy": "NO",
            "copy_dependency": "HIGH",
            "pain_state_visible": False,
            "pain_consequence_visible": False,
            "product_solution_bridge_visible": False,
            "action_or_state_change_visible": False,
            "icon_only_dependency": True,
            "static_packshot_only": True,
            "generic_product_swap_possible": True,
            "visual_semantic_observation": "Only a packshot, headline and icons remain when copy is considered.",
        })
        with self.assertRaisesRegex(HarnessError, "disappears when promotional copy is hidden|Icons or labels"):
            validate_module_judgment(value, module_record)

    def test_positive_flow_keeps_approved_plan_locked_into_generation_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            identity_path = root / "identity.json"
            plan_path = root / "plan.json"
            session_path = root / "session.json"
            request_path = root / "request.json"
            input_path.write_text(json.dumps(raw_input(with_reference=True), ensure_ascii=False), encoding="utf-8")
            identity_path.write_text(json.dumps(identity(), ensure_ascii=False), encoding="utf-8")
            plan_path.write_text(json.dumps(plan(with_reference=True), ensure_ascii=False), encoding="utf-8")

            harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())
            harness.cmd_lock_identity(type("Args", (), {"session": str(session_path), "identity": str(identity_path)})())
            harness.cmd_compile_plan(type("Args", (), {"session": str(session_path), "plan": str(plan_path)})())
            approval_file = root / "plan-approval.md"
            self.assertTrue(approval_file.exists())
            self.assertIn("空间结构", approval_file.read_text(encoding="utf-8"))
            approval_sha = json.loads(session_path.read_text(encoding="utf-8"))["approval_document"]["sha256"]
            harness.cmd_authorize(type("Args", (), {
                "session": str(session_path), "approval_text": "确认三屏与三比四方案",
                "approved_module_count": 3, "approved_aspect_ratio": "3:4",
                "approval_document_sha256": approval_sha,
            })())
            result = harness.cmd_generate_next(type("Args", (), {"session": str(session_path), "out": str(request_path)})())
            request = json.loads(request_path.read_text(encoding="utf-8"))
            saved = json.loads(session_path.read_text(encoding="utf-8"))

            self.assertEqual(saved["state"], "AWAITING_GENERATED_MODULE")
            self.assertTrue(request["context_contract"]["compiled_prompt_locked"])
            self.assertEqual(request["context_contract"]["approved_plan_fingerprint"], harness.fingerprint(saved["plan"]))
            self.assertEqual(request["output_surface"]["aspect_ratio"], "3:4")
            self.assertEqual((request["output_surface"]["width_px"], request["output_surface"]["height_px"]), (1440, 1920))
            self.assertTrue(request["output_surface"]["format_canvas_locked"])
            self.assertEqual(request["reference_images"][0], request["format_canvas"])
            self.assertNotIn(request["format_canvas"], request["product_reference_images"])
            with Image.open(request["format_canvas"]) as format_canvas:
                self.assertEqual(format_canvas.size, (1440, 1920))
            self.assertIn("输出比例硬锁", result["prompt"])
            self.assertIn("APPROVED PLAN CONTRACT", result["prompt"])
            self.assertIn("REFERENCE EXPRESSION GRAMMAR TO ADAPT", result["prompt"])

    def test_second_failed_attempt_accepts_with_residuals_and_advances_without_third_render(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, identity_path = root / "input.json", root / "identity.json"
            plan_path, session_path = root / "plan.json", root / "session.json"
            request_path, judgment_path = root / "request.json", root / "judgment.json"
            repair_path = root / "repair.json"
            input_path.write_text(json.dumps(raw_input(), ensure_ascii=False), encoding="utf-8")
            identity_path.write_text(json.dumps(identity(), ensure_ascii=False), encoding="utf-8")
            plan_path.write_text(json.dumps(plan(), ensure_ascii=False), encoding="utf-8")

            harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())
            harness.cmd_lock_identity(type("Args", (), {"session": str(session_path), "identity": str(identity_path)})())
            harness.cmd_compile_plan(type("Args", (), {"session": str(session_path), "plan": str(plan_path)})())
            approval_sha = json.loads(session_path.read_text(encoding="utf-8"))["approval_document"]["sha256"]
            harness.cmd_authorize(type("Args", (), {
                "session": str(session_path), "approval_text": "approve plan",
                "approved_module_count": 3, "approved_aspect_ratio": "3:4",
                "approval_document_sha256": approval_sha,
            })())

            first = harness.cmd_generate_next(type("Args", (), {"session": str(session_path), "out": str(request_path)})())
            first_image = root / "first.png"
            Image.new("RGB", (1440, 1920), "white").save(first_image)
            harness.cmd_record_generation(type("Args", (), {
                "session": str(session_path), "token": first["token"], "image": str(first_image),
            })())
            saved = json.loads(session_path.read_text(encoding="utf-8"))
            judgment_path.write_text(json.dumps(fail_judgment(saved["modules"][0]), ensure_ascii=False), encoding="utf-8")
            harness.cmd_audit_current(type("Args", (), {"session": str(session_path), "judgment": str(judgment_path)})())
            self.assertEqual(json.loads(session_path.read_text(encoding="utf-8"))["state"], "REPAIR_REQUIRED")

            repair_path.write_text(json.dumps({
                "module_id": "M01",
                "material_failures": ["Typography contract mismatch"],
                "passed_layers": ["identity", "facts", "proof"],
                "root_cause": "Copy was placed as a generic headline.",
                "unified_strategy": "Rebind copy to the product silhouette and preserve proof geometry.",
                "expected_visible_change": "Typography moves into the planned anchor zone and follows the object.",
            }, ensure_ascii=False), encoding="utf-8")
            harness.cmd_prepare_repair(type("Args", (), {"session": str(session_path), "repair_plan": str(repair_path)})())
            second = harness.cmd_generate_next(type("Args", (), {"session": str(session_path), "out": str(request_path)})())
            second_image = root / "second.png"
            Image.new("RGB", (1440, 1920), "white").save(second_image)
            harness.cmd_record_generation(type("Args", (), {
                "session": str(session_path), "token": second["token"], "image": str(second_image),
            })())
            saved = json.loads(session_path.read_text(encoding="utf-8"))
            judgment_path.write_text(json.dumps(fail_judgment(saved["modules"][0], "Repair still violates the anchor contract."), ensure_ascii=False), encoding="utf-8")
            harness.cmd_audit_current(type("Args", (), {"session": str(session_path), "judgment": str(judgment_path)})())

            saved = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "AUTHORIZED")
            self.assertEqual(saved["current_index"], 1)
            self.assertEqual(saved["modules"][0]["status"], "COMPLETE_WITH_RESIDUALS")
            self.assertEqual(Path(saved["modules"][0]["accepted_asset"]).resolve(), second_image.resolve())
            self.assertEqual(saved["modules"][0]["cycle_attempt_count"], 2)
            self.assertEqual(len(saved["modules"][0]["attempts"]), 2)
            self.assertTrue(saved["modules"][0]["residual_issues"])
            next_request = harness.cmd_generate_next(type("Args", (), {"session": str(session_path), "out": str(request_path)})())
            self.assertEqual(next_request["module_id"], "M02")


    def test_v093_compact_spatial_blueprint_is_runtime_expanded(self):
        modules = [
            {"id": "M01", "story_function": "FIRST_SCREEN_VALUE", "module_spatial_structure_contract": {
                "structure_family": "FULL_BLEED_HERO", "zone_briefs": ["完整商品与核心利益场景"],
                "structure_difference_from_previous": "首屏英雄舞台", "forbidden_fallbacks": ["纯标题", "通用棚拍", "装饰代替证据"]}},
            {"id": "M02", "story_function": "SOLUTION_PROOF", "module_spatial_structure_contract": {
                "structure_family": "MACRO_DIAGRAM", "zone_briefs": ["商品局部证据", "作用路径与结果"],
                "structure_difference_from_previous": "切换为局部与路径", "forbidden_fallbacks": ["纯标题", "通用棚拍", "装饰代替证据"]}},
            {"id": "M03", "story_function": "PURCHASE_CLOSURE", "module_spatial_structure_contract": {
                "structure_family": "FRAMED_LIFESTYLE_PLUS_CARDS", "zone_briefs": ["完整商品结果场景", "适用场景与购买理由"],
                "structure_difference_from_previous": "切换为结果框景", "forbidden_fallbacks": ["纯标题", "通用棚拍", "装饰代替证据"]}},
        ]
        validate_spatial_contract({"modules": modules})
        resolved = resolve_spatial_contract(modules[1])
        self.assertEqual(resolved["structural_relationship"], "NESTED")
        self.assertEqual(resolved["zone_count"], 2)

    def test_v093_purchase_closure_rejects_table_wall(self):
        modules = [{"id": "M01", "story_function": "PURCHASE_CLOSURE", "module_spatial_structure_contract": {
            "structure_family": "SPECIFICATION_BOARD", "zone_briefs": ["商品", "参数表"],
            "structure_difference_from_previous": "收尾", "forbidden_fallbacks": ["纯标题", "通用棚拍", "装饰代替证据"]}}]
        with self.assertRaisesRegex(HarnessError, "table wall"):
            validate_spatial_contract({"modules": modules})

    def test_v12_rejects_scalar_where_prompt_list_is_required(self):
        value = compact_v12_plan()
        value["modules"][0]["variation_from_previous"] = "建立首屏"
        with self.assertRaisesRegex(HarnessError, "variation_from_previous.*list"):
            normalize_plan(session(), value)

    def test_v12_compact_plan_compiles_with_dynamic_depth_and_fulfillment_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, identity_path = root / "input.json", root / "identity.json"
            plan_path, session_path = root / "plan.json", root / "session.json"
            input_path.write_text(json.dumps(route_aware_input(), ensure_ascii=False), encoding="utf-8")
            identity_path.write_text(json.dumps(identity(), ensure_ascii=False), encoding="utf-8")
            plan_path.write_text(json.dumps(compact_v12_plan(), ensure_ascii=False), encoding="utf-8")
            harness.cmd_start(type("Args", (), {"input": str(input_path), "session": str(session_path)})())
            harness.cmd_lock_identity(type("Args", (), {"session": str(session_path), "identity": str(identity_path)})())
            result = harness.cmd_compile_plan(type("Args", (), {"session": str(session_path), "plan": str(plan_path)})())
            saved = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["plan"]["plan_format"], "COMPACT_V1_2")
            self.assertEqual(saved["plan"]["output_strategy"]["module_count"], 5)
            self.assertIn("| 一级卖点 | 优先级 | 证据等级 |", result["approval_markdown"])

    def test_v12_primary_claim_cannot_borrow_dedicated_depth_as_support(self):
        value = route_aware_plan()
        value["plan_format"] = "COMPACT_V1_2"
        depth = value["selling_point_depth_contract"]["claim_depth"][0]
        depth.update({
            "priority": "PRIMARY",
            "required_decision_jobs": ["VALUE_OVERVIEW", "DEDICATED_EXPRESSION", "RESULT_OR_EXPERIENCE", "RECALL"],
            "scheduled_module_ids": ["M01", "M02", "M03"],
            "dedicated_module_ids": ["M02"],
            "module_jobs": [
                {"module_id": "M01", "job": "VALUE_OVERVIEW"},
                {"module_id": "M02", "job": "DEDICATED_EXPRESSION"},
                {"module_id": "M02", "job": "RESULT_OR_EXPERIENCE"},
                {"module_id": "M03", "job": "RECALL"},
            ],
        })
        value["modules"][1]["lead_claim_id"] = "F2"
        value["modules"][1]["supporting_claim_ids"] = ["F1"]
        with self.assertRaisesRegex(HarnessError, "supporting presence is not depth"):
            validate_sales_depth_contract(value, {"F1", "F2"})

    def test_v12_dynamic_count_is_derived_after_primary_depth(self):
        value = route_aware_plan()
        value["selling_point_depth_contract"]["primary_claim_ids"] = ["F1", "F2", "F3"]
        value["output_strategy"]["module_count_formula"] = {
            "base_narrative_jobs": 3, "primary_depth_expansion": 6,
            "supporting_jobs": 1, "shared_proof_savings": 1,
            "computed_balanced_minimum": 9,
            "shared_proof_rationale": "仅总览共享，三个一级卖点仍各有独立主证据。",
        }
        value["output_strategy"]["module_count_candidates"] = [
            {"candidate_mode": "COMPACT_COVERAGE", "count": 7, "decision": "REJECTED"},
            {"candidate_mode": "BALANCED_EXPRESSION", "count": 8, "decision": "SELECTED"},
            {"candidate_mode": "FULL_SALES", "count": 11, "decision": "REJECTED"},
        ]
        with self.assertRaisesRegex(HarnessError, "below the primary-selling-point depth floor"):
            validate_dynamic_count_formula(value)

    def test_v12_user_selling_point_ledger_cannot_silently_drop_a_point(self):
        value = route_aware_plan()
        supplied = [
            {"id": "U1", "text": "卖点一"},
            {"id": "U2", "text": "卖点二"},
        ]
        value["user_selling_point_coverage_ledger"] = [{
            "selling_point_id": "U1", "status": "ACTIVE", "atomic_claim_ids": ["F1"],
            "planned_module_ids": ["M01"], "reason": "直接保留",
        }]
        with self.assertRaisesRegex(HarnessError, "every user-supplied point exactly once"):
            validate_user_selling_point_ledger(value, supplied, {"F1", "F2"})

    def test_v12_cross_category_archetype_schedule_is_not_a_fixed_category_template(self):
        sequence = ["BENEFIT_OVERVIEW", "PAIN_SCENE", "DEDICATED_BENEFIT_PROOF", "SOURCE_ACTION_RESULT", "USE_SCOPE_MATRIX", "PURCHASE_CLOSURE"]
        for category in ("清洁家居", "数码家电", "美妆个护", "食品宠物", "家居家具"):
            modules = []
            for index, archetype in enumerate(sequence, start=1):
                modules.append({
                    "id": f"M{index:02d}", "category_fixture": category,
                    "story_function": "PAIN_ARTICULATION" if index == 2 else "PURCHASE_CLOSURE" if index == 6 else "SOLUTION_PROOF",
                    "visual_archetype": archetype,
                })
            validate_visual_archetypes({"modules": modules})

    def test_v13_conceptual_proof_can_omit_product_and_must_visualize_change(self):
        value = session()
        planned = value["modules"][0]["plan"]
        planned.pop("module_visual_performance_contract", None)
        planned["story_function"] = "SOLUTION_PROOF"
        planned["visual_archetype"] = "DEDICATED_BENEFIT_PROOF"
        planned["module_visual_expression_contract"] = {
            "expression_mode": "IMAGE_PLUS_COPY",
            "claim_visualizability": "VISUALIZABLE",
            "primary_visual_carrier": "STATE_CONTRAST",
            "visual_scene_sentence": "把问题对象、接触过程和减少后的结果状态做成连续主画面。",
            "visual_semantic_payload": "遮住文字仍能看出问题对象经历作用并明显减少。",
            "required_visual_relations": ["问题对象聚集到接触再到减少"],
            "copy_responsibility": "文字只命名画面已经呈现的对象和结果",
            "copy_only_justification": "",
            "forbidden_substitutes": ["纯文字解释", "纯图标解释", "装饰氛围", "通用商品摆拍", "等大卡片平铺"],
            "product_presence_policy": "ABSENT_ALLOWED",
            "evidence_subject_policy": "CLAIM_OBJECT_DOMINANT",
            "visualization_mode": "CONCEPTUAL_NON_DIAGNOSTIC",
            "transformation_required": True,
            "transformation_stages": ["问题对象聚集", "发生接触", "对象减少并离开作用面"],
            "truth_boundary": "概念示意，不冒充实验、显微观察、检测数值或真实内部机理",
        }
        prompt = compile_prompt(value, value["modules"][0])
        self.assertIn("本屏允许并优先不出现商品", prompt)
        self.assertIn("商品缺席不构成失败", prompt)
        self.assertIn("概念性科学画面", prompt)
        self.assertIn("问题对象聚集；发生接触；对象减少并离开作用面", prompt)
        self.assertNotIn("商品视觉占比不得低于约 30%", prompt)

    def test_v13_conceptual_proof_rejects_labeled_icon_without_transformation(self):
        module_value = {
            "id": "M03", "story_function": "SOLUTION_PROOF",
            "visual_archetype": "DEDICATED_BENEFIT_PROOF",
            "expression": {
                "claim_visualizability": "VISUALIZABLE",
                "product_presence_policy": "ABSENT_ALLOWED",
                "evidence_subject_policy": "CLAIM_OBJECT_DOMINANT",
                "visualization_mode": "CONCEPTUAL_NON_DIAGNOSTIC",
                "transformation_required": False,
                "transformation_stages": [],
            },
        }
        with self.assertRaisesRegex(HarnessError, "at least two visible transformation stages"):
            validate_visual_archetypes({"modules": [module_value]})

    def test_v20_routes_middle_proof_screens_to_product_absence(self):
        compact = compact_v12_plan()
        for module in compact["modules"]:
            module["expression"].pop("product_presence_policy", None)
        normalized = normalize_plan(session(), compact)
        policies = {
            item["id"]: item["product_presence_decision"]["policy"]
            for item in normalized["modules"]
        }
        self.assertEqual(policies["M01"], "REQUIRED_DOMINANT")
        self.assertEqual(policies["M03"], "ABSENT_PREFERRED")
        self.assertEqual(policies["M04"], "IDENTITY_TOKEN_ONLY")
        self.assertEqual(policies["M05"], "REQUIRED_DOMINANT")
        self.assertIn("M03", normalized["campaign_product_presence_rhythm"]["absence_favored_module_ids"])

    def test_v20_preserves_explicit_presence_policy(self):
        compact = compact_v12_plan()
        compact["modules"][2]["product_presence_decision"] = {
            "policy": "REQUIRED_SUPPORTING",
            "unique_job_if_present": "连接当前动作与商品",
            "primary_subject_without_product": "动作结果",
            "identity_binding_without_product": ["商品专属作用对象"],
            "absence_reason": "",
        }
        normalized = normalize_plan(session(), compact)
        self.assertEqual(normalized["modules"][2]["product_presence_decision"]["policy"], "REQUIRED_SUPPORTING")

    def test_v20_absent_preferred_prompt_forbids_hidden_packshots(self):
        value = session()
        planned = value["modules"][0]["plan"]
        planned.pop("module_visual_performance_contract", None)
        planned["module_visual_expression_contract"] = {
            "expression_mode": "IMAGE_PLUS_COPY",
            "claim_visualizability": "VISUALIZABLE",
            "primary_visual_carrier": "STATE_CONTRAST",
            "visual_scene_sentence": "以来源、材质与结果变化承担当前页面的全部主视觉语义。",
            "visual_semantic_payload": "遮住文字仍能看出来源、材质与结果之间的关系。",
            "required_visual_relations": ["来源到材质再到结果"],
            "copy_responsibility": "文字只命名画面已有关系",
            "copy_only_justification": "",
            "forbidden_substitutes": ["纯文字解释", "纯图标解释", "装饰氛围", "通用商品摆拍", "等大卡片平铺"],
            "product_presence_policy": "ABSENT_PREFERRED",
            "evidence_subject_policy": "CLAIM_OBJECT_DOMINANT",
            "visualization_mode": "DIRECT_OBSERVATION",
            "transformation_required": False,
            "transformation_stages": [],
            "truth_boundary": "只呈现当前事实允许的来源、材质和结果",
        }
        planned["product_presence_decision"] = {
            "policy": "ABSENT_PREFERRED",
            "unique_job_if_present": "NONE",
            "primary_subject_without_product": "来源、材质与结果",
            "identity_binding_without_product": ["当前商品专属材质", "系列色彩与图形DNA"],
            "absence_reason": "避免重复包装露出挤压来源证据",
        }
        prompt = compile_prompt(value, value["modules"][0])
        self.assertIn("禁止把商品藏在角落、背景、虚化层、边缘卡片或装饰性小图中", prompt)
        self.assertIn("商品出镜节奏合同", prompt)
        self.assertIn("来源、材质与结果", prompt)


if __name__ == "__main__":
    unittest.main()
