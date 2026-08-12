import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness  # noqa: E402
from runtime.prompt_compiler import compile_prompt, prompt_preflight  # noqa: E402
from runtime.state import HarnessError  # noqa: E402
from runtime.visual_gate import CHECKS, validate_module_judgment  # noqa: E402


def profile():
    return {
        "target_platform": "淘宝移动端",
        "profile_name": "3:4 working master",
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


def identity():
    return {
        "canonical_name": "手持制冷风扇", "category": "小家电",
        "reference_image_ids": ["front", "rear"],
        "invariant_features": ["真实轮廓", "真实按键和进出风口"],
        "allowed_states": ["手持", "桌面使用"], "uncertain_features": [],
        "forbidden_mutations": ["不得改成普通圆形风扇"],
    }


def module(order, cluster_ids=("SP1",), reference_pattern_ids=(), copy_density="low"):
    visible_copy = [
        {"text": "一握即凉", "role": "偏置短标题", "anchor": "冷感部件"},
        {"text": "强风×冷感", "role": "关系标签", "anchor": "气流路径"},
    ]
    if copy_density == "none":
        visible_copy = []
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
                "spatial_tokens": "前景产品后景环境", "invariants": ["真实产品", "蓝白色彩"],
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
            "target_platform": "淘宝移动端", "profile_name": "3:4 working master", "selection_mode": "ADAPTIVE_PLANNED",
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


def fail_judgment(module_record, issue="Typography is not attached to the planned visual object."):
    planned = module_record["plan"]
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
        },
        "material_failures": [{"check": "typography_contract_match", "visible_evidence": issue}],
        "passed_layers": ["identity", "facts", "visual proof"],
    }


class RegressionTests(unittest.TestCase):
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
            },
            "material_failures": [], "passed_layers": [],
        }
        with self.assertRaisesRegex(HarnessError, "omitted approved plan elements"):
            validate_module_judgment(judgment, module_record)

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
            harness.cmd_authorize(type("Args", (), {
                "session": str(session_path), "approval_text": "确认三屏与三比四方案",
                "approved_module_count": 3, "approved_aspect_ratio": "3:4",
            })())
            result = harness.cmd_generate_next(type("Args", (), {"session": str(session_path), "out": str(request_path)})())
            request = json.loads(request_path.read_text(encoding="utf-8"))
            saved = json.loads(session_path.read_text(encoding="utf-8"))

            self.assertEqual(saved["state"], "AWAITING_GENERATED_MODULE")
            self.assertTrue(request["context_contract"]["compiled_prompt_locked"])
            self.assertEqual(request["context_contract"]["approved_plan_fingerprint"], harness.fingerprint(saved["plan"]))
            self.assertIn("APPROVED PLAN CONTRACT", result["prompt"])
            self.assertIn("REFERENCE EXPRESSION GRAMMAR TO ADAPT", result["prompt"])

    def test_second_failed_attempt_stops_instead_of_rerendering_or_auto_accepting(self):
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
            harness.cmd_authorize(type("Args", (), {
                "session": str(session_path), "approval_text": "approve plan",
                "approved_module_count": 3, "approved_aspect_ratio": "3:4",
            })())

            first = harness.cmd_generate_next(type("Args", (), {"session": str(session_path), "out": str(request_path)})())
            first_image = root / "first.png"
            first_image.write_bytes(b"first")
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
            second_image.write_bytes(b"second")
            harness.cmd_record_generation(type("Args", (), {
                "session": str(session_path), "token": second["token"], "image": str(second_image),
            })())
            saved = json.loads(session_path.read_text(encoding="utf-8"))
            judgment_path.write_text(json.dumps(fail_judgment(saved["modules"][0], "Repair still violates the anchor contract."), ensure_ascii=False), encoding="utf-8")
            harness.cmd_audit_current(type("Args", (), {"session": str(session_path), "judgment": str(judgment_path)})())

            saved = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "REPAIR_EXHAUSTED")
            self.assertEqual(saved["modules"][0]["status"], "REPAIR_EXHAUSTED")
            self.assertIsNone(saved["modules"][0]["accepted_asset"])
            self.assertEqual(saved["modules"][0]["cycle_attempt_count"], 2)
            self.assertEqual(len(saved["modules"][0]["attempts"]), 2)
            with self.assertRaises(HarnessError):
                harness.cmd_generate_next(type("Args", (), {"session": str(session_path), "out": str(request_path)})())


if __name__ == "__main__":
    unittest.main()
