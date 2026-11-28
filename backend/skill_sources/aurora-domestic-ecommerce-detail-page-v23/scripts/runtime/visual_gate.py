from __future__ import annotations

import re

from .performance_contract import resolve_performance_contract
from .spatial_contract import resolve_spatial_contract
from .state import HarnessError, require_fields


CHECKS = (
    "identity",
    "facts",
    "role",
    "proof",
    "proof_integrity",
    "legibility",
    "text_integration",
    "series_continuity",
    "page_distinctness",
    "spatial_structure_match",
    "spatial_neighbor_difference",
    "integrity",
    "ocr_whitelist_match",
    "internal_metadata_absent",
    "hidden_copy_comprehension",
    "visual_payload_sufficiency",
    "product_specificity",
    "proof_relation_visible",
    "commercial_expression",
    "feedback_non_regression",
    "approved_plan_fidelity",
    "reference_grammar_application",
    "auxiliary_copy_binding",
    "typography_contract_match",
    "typography_neighbor_difference",
    "product_prominence",
    "headline_hierarchy",
    "evidence_primary_visual",
    "depth_performance",
    "visual_tension",
    "information_hierarchy",
    "mobile_scan_stops",
    "background_competition",
    "commercial_closure",
    "independent_brand_logo",
    "semantic_visual_expression",
    "visual_carrier_fidelity",
    "copy_dependency_control",
    "pain_solution_expression",
    "static_packshot_regression",
)


FORBIDDEN_OCR_PATTERNS = (
    re.compile(r"\bM\d{2,}\b", re.IGNORECASE),
    re.compile(r"上一屏|下一屏|页面职责|买家问题|主结论|承接|引向"),
    re.compile(r"构图家族|证据等级|文字模式|Logo策略|模块编号|页码|屏号"),
    re.compile(r"对应包装|正标位置|卖点对应|证据区|限定语|来源说明|绑定位置"),
    re.compile(r"以包装标[示识]为准|购买前请核对|购买前以实际|当前仅能确认|缺少检测报告|待核验|待验证|未确认"),
)

AUDIT_BOILERPLATE_PATTERNS = (
    re.compile(r"实际像素与.*一致"),
    re.compile(r"符合(?:要求|合约|计划)$"),
    re.compile(r"已通过检查$"),
    re.compile(r"未发现问题$"),
)

CONTEXT_COPY_HIGH_RISK_PATTERNS = (
    re.compile(r"\d|%|％|倍|小时|天"),
    re.compile(r"除菌|杀菌|除螨|真菌|抗菌|抑菌|无菌|消毒"),
    re.compile(r"安全|健康|孕婴|婴幼儿|不伤|温和|天然|成分|含量"),
    re.compile(r"认证|正品|专利|检测|报告|功效|有效|成功率|第一"),
)


def _validate_concrete_check_evidence(checks: dict, label: str) -> None:
    evidence = []
    for name, result in checks.items():
        text = str(result.get("visible_evidence", "")).strip()
        if len(text) < 8:
            raise HarnessError(f"{label} check {name} lacks concrete visible evidence")
        if any(pattern.search(text) for pattern in AUDIT_BOILERPLATE_PATTERNS):
            raise HarnessError(f"{label} check {name} uses template audit evidence instead of a pixel observation")
        evidence.append(_normalize_text(text))
    if evidence and len(set(evidence)) < max(3, int(len(evidence) * 0.7)):
        raise HarnessError(f"{label} repeats boilerplate evidence across too many checks")


def _normalize_text(value: object) -> str:
    return re.sub(r"[\s，。；：、!！?？\-—_·•]+", "", str(value or "")).lower()


def _matches_whitelist(text: str, whitelist: list) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return True
    for item in whitelist:
        allowed = _normalize_text(item)
        if normalized == allowed or normalized in allowed or allowed in normalized:
            return True
    return False


def _eligible_advisory_context_copy(observations: dict, module: dict) -> list[str]:
    """Allow a small amount of non-claim scene copy without spending the repair slot."""
    advisory = observations.get("advisory_context_copy", [])
    if not advisory:
        return []
    if not isinstance(advisory, list):
        raise HarnessError("advisory_context_copy must be a list")
    story_function = module["plan"].get("story_function")
    rationale = str(observations.get("advisory_context_copy_observation", "")).strip()
    if story_function not in ("PAIN_ARTICULATION", "PAIN_SOLUTION_COMBINED"):
        raise HarnessError("Advisory context copy is limited to pain-articulation modules")
    if len(advisory) > 4 or sum(len(str(item).strip()) for item in advisory) > 80:
        raise HarnessError("Advisory context copy exceeds the small scene-caption allowance")
    if len(rationale) < 8:
        raise HarnessError("Advisory context copy needs a concrete non-claim rationale")
    ocr_text = observations.get("ocr_text", [])
    eligible = []
    for item in advisory:
        text = str(item).strip()
        if not text or len(text) > 28:
            raise HarnessError("Each advisory scene caption must be short and concrete")
        if not any(_matches_whitelist(text, [ocr]) for ocr in ocr_text):
            raise HarnessError("Advisory context copy must be visibly present in OCR observations")
        if any(pattern.search(text) for pattern in FORBIDDEN_OCR_PATTERNS):
            raise HarnessError("Internal workflow copy can never be advisory")
        if any(pattern.search(text) for pattern in CONTEXT_COPY_HIGH_RISK_PATTERNS):
            raise HarnessError("Product, efficacy, safety, numeric or trust claims cannot be advisory copy")
        eligible.append(text)
    return eligible


def _eligible_advisory_visual_marks(observations: dict) -> list[str]:
    """Allow harmless sequence indices without turning them into promotional copy."""
    advisory = observations.get("advisory_visual_marks", [])
    if not advisory:
        return []
    if not isinstance(advisory, list):
        raise HarnessError("advisory_visual_marks must be a list")
    rationale = str(observations.get("advisory_visual_marks_observation", "")).strip()
    if len(advisory) > 12 or len(advisory) < 2:
        raise HarnessError("Advisory visual marks must form a small visible sequence")
    if len(rationale) < 8:
        raise HarnessError("Advisory visual marks need a concrete organizational rationale")
    ocr_text = observations.get("ocr_text", [])
    values = []
    eligible = []
    for item in advisory:
        text = str(item).strip()
        match = re.fullmatch(r"0*(\d{1,2})", text)
        if not match:
            raise HarnessError("Only simple numeric sequence indices qualify as advisory visual marks")
        value = int(match.group(1))
        if value < 1 or value > 12:
            raise HarnessError("Advisory sequence indices must stay between 1 and 12")
        if not any(_matches_whitelist(text, [ocr]) for ocr in ocr_text):
            raise HarnessError("Advisory visual marks must be visibly present in OCR observations")
        values.append(value)
        eligible.append(text)
    if values != list(range(1, len(values) + 1)):
        raise HarnessError("Advisory numeric marks must be a consecutive sequence starting at 1")
    return eligible


def validate_module_judgment(value: dict, module: dict) -> None:
    module_id = module["id"]
    require_fields(value, ("module_id", "status", "checks", "audit_complete", "observations"), "module judgment")
    if value["module_id"] != module_id:
        raise HarnessError("Judgment does not target the current module")
    if value["status"] not in ("PASS", "MATERIAL_FAIL"):
        raise HarnessError("Judgment status must be PASS or MATERIAL_FAIL")
    if value["audit_complete"] is not True:
        raise HarnessError("Pixel audit must be complete")

    missing = [name for name in CHECKS if name not in value["checks"]]
    if missing:
        raise HarnessError("Judgment missing checks: " + ", ".join(missing))
    failures = value.get("material_failures", [])
    if module.get("plan", {}).get("authoring_plan_format") == "COMPACT_V1_2":
        _validate_concrete_check_evidence(value["checks"], f"module {module_id}")
    failed_checks = [name for name, result in value["checks"].items() if not result.get("pass", False)]

    observations = value["observations"]
    require_fields(
        observations,
        (
            "effective_visual_payloads", "visible_proof_relations",
            "hidden_copy_observation", "product_specificity_observation",
            "planned_elements_visible", "reference_pattern_observation", "copy_binding_observation",
            "typography_primary_mode_observed", "typography_anchor_zone_observed",
            "typography_anchor_target_observation", "typography_hierarchy_observation",
            "typography_neighbor_difference_observation",
            "product_prominence_percent", "headline_rank", "evidence_is_primary_visual",
            "depth_layers", "type_roles_seen", "unequal_information_groups_seen",
            "visual_tension_seen", "mobile_scan_order", "commercial_closure_visible",
            "background_competition", "independent_brand_logo_count",
            "independent_brand_logo_source_fidelity", "independent_brand_logo_observation",
            "structure_family_observed", "structural_zone_count", "structural_relationship_observed",
            "full_bleed_single_scene", "dominant_zone_count_observed",
            "secondary_panel_count_observed", "mini_scene_count_observed",
            "previous_structure_similarity", "same_full_bleed_template_as_previous",
            "spatial_structure_observation",
        ),
        "pixel audit observations",
    )
    for optional_empty_key in ("ocr_text", "unauthorized_ocr_text", "forbidden_text_hits", "planned_elements_missing"):
        if optional_empty_key not in observations or not isinstance(observations[optional_empty_key], list):
            raise HarnessError(f"pixel audit observations missing required list field: {optional_empty_key}")

    expression = module["plan"].get("module_visual_expression_contract")
    if expression:
        require_fields(
            observations,
            (
                "visual_carrier_observed", "claim_visible_without_copy", "copy_dependency",
                "pain_state_visible", "pain_consequence_visible", "product_solution_bridge_visible",
                "action_or_state_change_visible", "icon_only_dependency", "static_packshot_only",
                "generic_product_swap_possible", "visual_semantic_observation",
            ),
            "v0.9 semantic pixel observations",
        )

    allowed_copy = [item.get("text", "") for item in module["plan"].get("visible_copy", [])]
    advisory_context_copy = _eligible_advisory_context_copy(observations, module)
    advisory_visual_marks = _eligible_advisory_visual_marks(observations)
    advisory_whitelist = advisory_context_copy + advisory_visual_marks
    unauthorized = [
        text for text in observations.get("unauthorized_ocr_text", [])
        if not _matches_whitelist(text, advisory_whitelist)
    ]
    unauthorized.extend(
        text for text in observations.get("ocr_text", [])
        if not _matches_whitelist(text, allowed_copy)
        and not _matches_whitelist(text, advisory_whitelist)
    )
    forbidden_hits = list(observations.get("forbidden_text_hits", []))
    for text in observations.get("ocr_text", []):
        if any(pattern.search(str(text)) for pattern in FORBIDDEN_OCR_PATTERNS):
            forbidden_hits.append(str(text))

    minimum_payload = module["plan"]["visual_proof_contract"]["minimum_visual_payload"]
    payloads = [str(item).strip() for item in observations.get("effective_visual_payloads", []) if str(item).strip()]
    relations = [str(item).strip() for item in observations.get("visible_proof_relations", []) if str(item).strip()]
    hard_failures = []
    if unauthorized:
        hard_failures.append("OCR contains text outside the approved visible-copy whitelist")
    if forbidden_hits:
        hard_failures.append("Rendered pixels contain internal workflow metadata")
    conceptual_risk = observations.get("conceptual_visualization_risk", "NOT_PRESENT")
    if conceptual_risk not in ("NOT_PRESENT", "CLEARLY_STYLIZED", "MINOR_NON_MISLEADING_VARIATION", "MISLEADING_EVIDENCE"):
        raise HarnessError("Unknown conceptual_visualization_risk")
    if conceptual_risk != "NOT_PRESENT" and len(str(observations.get("conceptual_visualization_observation", "")).strip()) < 8:
        raise HarnessError("Conceptual visualization risk needs a concrete pixel observation")
    if conceptual_risk == "MISLEADING_EVIDENCE":
        hard_failures.append("Conceptual graphics impersonate exact structure, testing, microscopy or unsupported scientific evidence")
    if len(payloads) < minimum_payload:
        hard_failures.append("Effective visual payload is below the approved minimum")
    if not relations:
        hard_failures.append("No visible product-action-result proof relation was recorded")
    if not str(observations.get("hidden_copy_observation", "")).strip():
        hard_failures.append("Hidden-copy comprehension was not demonstrated")
    if not str(observations.get("product_specificity_observation", "")).strip():
        hard_failures.append("Product specificity was not demonstrated")
    if expression:
        if observations.get("visual_carrier_observed") != expression["primary_visual_carrier"]:
            hard_failures.append("Observed visual carrier does not match the approved semantic carrier")
        if not str(observations.get("visual_semantic_observation", "")).strip():
            hard_failures.append("No hidden-copy visual meaning was observed")
        visualizability = expression["claim_visualizability"]
        if visualizability in ("VISUALIZABLE", "PARTIALLY_VISUALIZABLE"):
            if observations.get("claim_visible_without_copy") == "NO":
                hard_failures.append("A visualizable claim disappears when promotional copy is hidden")
            if observations.get("copy_dependency") == "HIGH":
                hard_failures.append("A visualizable claim depends primarily on copy")
            if observations.get("icon_only_dependency") is True:
                hard_failures.append("Icons or labels substitute for the required visual meaning")
            if observations.get("static_packshot_only") is True:
                hard_failures.append("A static packshot plus copy cannot carry a visualizable claim")
        carrier = expression["primary_visual_carrier"]
        if carrier in ("ACTION_CONTACT", "STATE_CONTRAST", "PROCESS_PATH", "RESULT_SCENE") and observations.get("action_or_state_change_visible") is not True:
            hard_failures.append("The planned action, contrast, process or result carrier shows no visible state change")
        story_function = module["plan"].get("story_function")
        if story_function in ("PAIN_ARTICULATION", "PAIN_SOLUTION_COMBINED"):
            if observations.get("pain_state_visible") is not True or observations.get("pain_consequence_visible") is not True:
                hard_failures.append("The pain module lacks a visible problem state or consequence")
            if observations.get("product_solution_bridge_visible") is not True:
                hard_failures.append("The pain module does not visibly bridge the problem to the product solution")
        presence_policy = expression.get("product_presence_policy", "REQUIRED_DOMINANT")
        if story_function in ("SOLUTION_PROOF", "MECHANISM_PROOF", "MATERIAL_PROOF", "USE_OR_RESULT") and observations.get("generic_product_swap_possible") is True and presence_policy not in ("OPTIONAL", "ABSENT_ALLOWED", "IDENTITY_TOKEN_ONLY", "ABSENT_PREFERRED"):
            hard_failures.append("The proof could sell another product after swapping only the packshot")
        presence_decision = module["plan"].get("product_presence_decision")
        if presence_decision:
            require_fields(
                observations,
                ("product_presence_observed", "unplanned_full_product_seen", "identity_binding_without_product_observed"),
                "v2.0 product-presence pixel observations",
            )
            observed_presence = observations.get("product_presence_observed")
            if presence_policy == "REQUIRED_DOMINANT" and observed_presence != "DOMINANT":
                hard_failures.append("The screen that must establish or close product recognition lacks a dominant complete product")
            if presence_policy == "REQUIRED_SUPPORTING" and observed_presence != "SUPPORTING":
                hard_failures.append("The supporting product anchor is absent or has become the dominant subject")
            if presence_policy == "IDENTITY_TOKEN_ONLY":
                if observed_presence != "IDENTITY_TOKEN_ONLY" or observations.get("unplanned_full_product_seen") is True:
                    hard_failures.append("An identity-token-only screen contains a complete product/package or lacks the approved identity token")
            if presence_policy == "ABSENT_PREFERRED":
                if observed_presence != "ABSENT" or observations.get("unplanned_full_product_seen") is True:
                    hard_failures.append("A product-absence screen contains an unplanned complete product, package, corner packshot or background packshot")
            if presence_policy in ("IDENTITY_TOKEN_ONLY", "ABSENT_ALLOWED", "ABSENT_PREFERRED"):
                if not str(observations.get("identity_binding_without_product_observed", "")).strip():
                    hard_failures.append("Product attribution without a full packshot was not visibly demonstrated")
        if expression.get("transformation_required") and observations.get("action_or_state_change_visible") is not True:
            hard_failures.append("The required problem-to-action-to-result transformation is not visibly expressed")
        if expression.get("evidence_subject_policy") in ("CLAIM_OBJECT_DOMINANT", "ACTION_RESULT_DOMINANT") and observations.get("evidence_is_primary_visual") is not True:
            hard_failures.append("The claim object or transformation is not the dominant visual evidence")
    if observations.get("planned_elements_missing"):
        hard_failures.append("Generated pixels omitted approved plan elements")
    if not observations.get("planned_elements_visible"):
        hard_failures.append("Approved plan fidelity was not demonstrated")
    if module["plan"].get("reference_pattern_ids") and not str(observations.get("reference_pattern_observation", "")).strip():
        hard_failures.append("Approved reference-expression grammar was not visibly applied")
    if module["plan"].get("visible_copy") and not str(observations.get("copy_binding_observation", "")).strip():
        hard_failures.append("Auxiliary copy was not visibly bound to the planned object, relation or result")

    spatial = resolve_spatial_contract(module["plan"])
    if spatial:
        if observations.get("structure_family_observed") != spatial["structure_family"]:
            hard_failures.append("Observed spatial structure family does not match the approved contract")
        if observations.get("structural_relationship_observed") != spatial["structural_relationship"]:
            hard_failures.append("Observed spatial relationship does not match the approved contract")
        if observations.get("structural_zone_count", 0) < spatial["zone_count"]:
            hard_failures.append("Observed meaning-bearing zones are below the approved spatial minimum")
        if observations.get("dominant_zone_count_observed", 0) < spatial["dominant_zone_count"]:
            hard_failures.append("Observed dominant zones are below the approved spatial contract")
        if observations.get("secondary_panel_count_observed", 0) < spatial["secondary_panel_count"]:
            hard_failures.append("Observed secondary panels are below the approved spatial contract")
        if observations.get("mini_scene_count_observed", 0) < spatial["mini_scene_count"]:
            hard_failures.append("Observed mini-scenes are below the approved spatial contract")
        if not spatial["full_bleed_single_scene_allowed"] and observations.get("full_bleed_single_scene") is True:
            hard_failures.append("A required composite structure collapsed into one full-bleed scene")
        if module.get("order", 1) > 1:
            if observations.get("previous_structure_similarity") == "HIGH":
                hard_failures.append("The module is structurally too similar to the preceding screen")
            if observations.get("same_full_bleed_template_as_previous") is True:
                hard_failures.append("The module repeats the preceding full-bleed poster template")
        if not str(observations.get("spatial_structure_observation", "")).strip():
            hard_failures.append("Spatial structure was not visibly demonstrated")
    text_system = module["plan"]["text_system"]
    if observations.get("typography_primary_mode_observed") != text_system["primary_mode"]:
        hard_failures.append("Observed primary typography mode does not match the approved typography contract")
    if observations.get("typography_anchor_zone_observed") != text_system["anchor_zone"]:
        hard_failures.append("Observed typography anchor zone does not match the approved typography contract")
    if not str(observations.get("typography_anchor_target_observation", "")).strip():
        hard_failures.append("Typography was not visibly attached to the approved visual anchor")
    if not str(observations.get("typography_hierarchy_observation", "")).strip():
        hard_failures.append("Typography hierarchy was not visibly demonstrated")
    if not str(observations.get("typography_neighbor_difference_observation", "")).strip():
        hard_failures.append("Required typography difference from the neighboring screen was not demonstrated")

    performance = resolve_performance_contract(
        module["plan"],
        order=module.get("order", 1),
        module_count=max(module.get("order", 1), 1),
    )
    prominence = observations.get("product_prominence_percent")
    if not isinstance(prominence, (int, float)) or isinstance(prominence, bool):
        hard_failures.append("Product prominence percentage was not measured")
    elif performance["product_prominence_min_percent"] > 0 and prominence < performance["product_prominence_min_percent"]:
        hard_failures.append("Product prominence is below the approved visual-performance minimum")
    headline_rank = observations.get("headline_rank")
    if performance["headline_must_enter_top_three"]:
        if not isinstance(headline_rank, int) or isinstance(headline_rank, bool):
            hard_failures.append("Required headline visual rank was not measured")
        elif headline_rank > performance["headline_rank_max"]:
            hard_failures.append("Headline falls below the approved visual hierarchy")
    if performance["evidence_must_be_primary_visual"] and observations.get("evidence_is_primary_visual") is not True:
        hard_failures.append("The decisive selling-point evidence is not a primary visual")
    depth_layers = observations.get("depth_layers")
    if not isinstance(depth_layers, int) or isinstance(depth_layers, bool) or depth_layers < performance["depth_layers_min"]:
        hard_failures.append("Visible depth layers are below the approved minimum")
    visible_copy_count = len([item for item in module["plan"].get("visible_copy", []) if str(item.get("text", "")).strip()])
    required_type_roles = min(performance["type_role_target"], max(1, visible_copy_count))
    required_unequal_groups = min(performance["unequal_information_groups_min"], max(1, visible_copy_count + 1))
    type_roles = observations.get("type_roles_seen")
    if not isinstance(type_roles, int) or isinstance(type_roles, bool) or type_roles < required_type_roles:
        hard_failures.append("Typography roles are below the approved visual-hierarchy target")
    unequal_groups = observations.get("unequal_information_groups_seen")
    if not isinstance(unequal_groups, int) or isinstance(unequal_groups, bool) or unequal_groups < required_unequal_groups:
        hard_failures.append("Information groups remain too equal or too few to form hierarchy")
    if performance["visual_tension_required"] and observations.get("visual_tension_seen") is not True:
        hard_failures.append("Approved scale, action or state tension is not visible")
    scan_order = observations.get("mobile_scan_order")
    if not isinstance(scan_order, list) or len([item for item in scan_order if str(item).strip()]) < performance["mobile_scan_stops_min"]:
        hard_failures.append("Mobile scan stops are below the approved minimum")
    if performance["commercial_closure_required"] and observations.get("commercial_closure_visible") is not True:
        hard_failures.append("The visual does not close back to the product benefit or purchase reason")
    logo_count = observations.get("independent_brand_logo_count")
    logo_fidelity = observations.get("independent_brand_logo_source_fidelity")
    if module.get("order", 1) == 1:
        if logo_count != 1:
            hard_failures.append("The first screen must contain exactly one independent brand logo")
        if logo_fidelity != "MATCHES_AUTHORIZED_SOURCE":
            hard_failures.append("The first-screen independent logo does not visibly match the authorized source")
    else:
        if logo_count != 0:
            hard_failures.append("Screens after M01 must not contain an independent brand logo")
        if logo_fidelity != "NOT_APPLICABLE":
            hard_failures.append("Later-screen logo fidelity must be NOT_APPLICABLE when no independent logo is present")
    competition_rank = {"LOW": 0, "LOW_TO_MEDIUM": 1, "MEDIUM": 2, "HIGH": 3}
    observed_competition = observations.get("background_competition")
    if observed_competition not in competition_rank:
        hard_failures.append("Background competition was not classified")
    elif competition_rank[observed_competition] > competition_rank[performance["background_competition_max"]]:
        hard_failures.append("Background competition exceeds the approved ceiling")

    if value["status"] == "PASS" and (failures or failed_checks or hard_failures):
        raise HarnessError("PASS judgment violates hard pixel gates: " + "; ".join(hard_failures or failed_checks))
    if value["status"] == "MATERIAL_FAIL" and not failures:
        raise HarnessError("MATERIAL_FAIL requires visible material failures")


def validate_long_page_judgment(value: dict, plan: dict | None = None) -> None:
    require_fields(value, ("status", "checks", "audit_complete"), "long-page judgment")
    if value["status"] not in ("PASS", "PASS_WITH_RESIDUALS"):
        raise HarnessError("Long-page status must be PASS or PASS_WITH_RESIDUALS")
    if value["audit_complete"] is not True:
        raise HarnessError("Long-page pixel audit must be complete")
    if plan and plan.get("plan_format") == "COMPACT_V1_2":
        _validate_concrete_check_evidence(value["checks"], "long-page")
    required = (
        "story_order", "repetition", "density_rhythm", "visual_continuity",
        "layout_variation", "typography_rhythm", "proof_integrity",
        "brand_continuity", "lower_page_quality", "seams", "purchase_closure",
        "internal_metadata_absent", "visual_payload_rhythm", "feedback_non_regression",
        "first_screen_value_clarity", "pain_solution_continuity", "selling_point_recall",
        "visual_performance_curve", "spatial_structure_rhythm", "full_bleed_repetition",
        "series_master_layout_boundary", "internal_copy_isolation",
    )
    if plan and plan.get("campaign_pain_solution_contract"):
        required += (
            "pain_module_presence", "pain_before_solution", "visual_carrier_diversity",
            "static_packshot_repetition", "copy_only_justification_integrity",
        )
    if plan and plan.get("campaign_product_presence_rhythm"):
        required += (
            "product_presence_rhythm", "product_identity_without_full_product",
            "meaningful_product_return_points",
        )
    missing = [name for name in required if name not in value["checks"]]
    if missing:
        raise HarnessError("Long-page judgment missing checks: " + ", ".join(missing))
    failed = [name for name in required if not value["checks"][name].get("pass", False)]
    if value["status"] == "PASS" and failed:
        raise HarnessError("PASS long-page judgment contains failed checks: " + ", ".join(failed))
    if plan and plan.get("plan_format") == "COMPACT_V1_2":
        fulfillment = value.get("claim_fulfillment")
        primary = set(plan["selling_point_depth_contract"]["primary_claim_ids"])
        if not isinstance(fulfillment, list) or {item.get("claim_id") for item in fulfillment} != primary:
            raise HarnessError("Long-page audit must account for every primary claim in claim_fulfillment")
        known_modules = {item["id"] for item in plan["modules"]}
        for item in fulfillment:
            require_fields(item, ("claim_id", "overview_visible", "dedicated_visible", "use_or_result_visible", "recall_visible", "observed_module_ids", "visible_evidence"), "claim fulfillment audit")
            if not all(item[key] is True for key in ("overview_visible", "dedicated_visible", "use_or_result_visible", "recall_visible")):
                raise HarnessError(f"Primary claim {item['claim_id']} is not fully sold through in the assembled page")
            if not set(item["observed_module_ids"]).issubset(known_modules) or len(set(item["observed_module_ids"])) < 3:
                raise HarnessError("Primary-claim fulfillment must cite at least three real planned modules")
            if len(str(item["visible_evidence"]).strip()) < 20:
                raise HarnessError("Primary-claim fulfillment needs concrete assembled-pixel evidence")
