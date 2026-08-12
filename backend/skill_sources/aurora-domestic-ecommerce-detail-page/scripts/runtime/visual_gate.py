from __future__ import annotations

import re

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
)


FORBIDDEN_OCR_PATTERNS = (
    re.compile(r"\bM\d{2,}\b", re.IGNORECASE),
    re.compile(r"上一屏|下一屏|页面职责|买家问题|主结论|承接|引向"),
    re.compile(r"构图家族|证据等级|文字模式|Logo策略|模块编号|页码|屏号"),
)


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
        ),
        "pixel audit observations",
    )
    for optional_empty_key in ("ocr_text", "unauthorized_ocr_text", "forbidden_text_hits", "planned_elements_missing"):
        if optional_empty_key not in observations or not isinstance(observations[optional_empty_key], list):
            raise HarnessError(f"pixel audit observations missing required list field: {optional_empty_key}")

    allowed_copy = [item.get("text", "") for item in module["plan"].get("visible_copy", [])]
    unauthorized = list(observations.get("unauthorized_ocr_text", []))
    unauthorized.extend(
        text for text in observations.get("ocr_text", [])
        if not _matches_whitelist(text, allowed_copy)
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
    if len(payloads) < minimum_payload:
        hard_failures.append("Effective visual payload is below the approved minimum")
    if not relations:
        hard_failures.append("No visible product-action-result proof relation was recorded")
    if not str(observations.get("hidden_copy_observation", "")).strip():
        hard_failures.append("Hidden-copy comprehension was not demonstrated")
    if not str(observations.get("product_specificity_observation", "")).strip():
        hard_failures.append("Product specificity was not demonstrated")
    if observations.get("planned_elements_missing"):
        hard_failures.append("Generated pixels omitted approved plan elements")
    if not observations.get("planned_elements_visible"):
        hard_failures.append("Approved plan fidelity was not demonstrated")
    if module["plan"].get("reference_pattern_ids") and not str(observations.get("reference_pattern_observation", "")).strip():
        hard_failures.append("Approved reference-expression grammar was not visibly applied")
    if module["plan"].get("visible_copy") and not str(observations.get("copy_binding_observation", "")).strip():
        hard_failures.append("Auxiliary copy was not visibly bound to the planned object, relation or result")
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

    if value["status"] == "PASS" and (failures or failed_checks or hard_failures):
        raise HarnessError("PASS judgment violates hard pixel gates: " + "; ".join(hard_failures or failed_checks))
    if value["status"] == "MATERIAL_FAIL" and not failures:
        raise HarnessError("MATERIAL_FAIL requires visible material failures")


def validate_long_page_judgment(value: dict) -> None:
    require_fields(value, ("status", "checks", "audit_complete"), "long-page judgment")
    if value["status"] not in ("PASS", "PASS_WITH_RESIDUALS"):
        raise HarnessError("Long-page status must be PASS or PASS_WITH_RESIDUALS")
    if value["audit_complete"] is not True:
        raise HarnessError("Long-page pixel audit must be complete")
    required = (
        "story_order", "repetition", "density_rhythm", "visual_continuity",
        "layout_variation", "typography_rhythm", "proof_integrity",
        "brand_continuity", "lower_page_quality", "seams", "purchase_closure",
        "internal_metadata_absent", "visual_payload_rhythm", "feedback_non_regression",
    )
    missing = [name for name in required if name not in value["checks"]]
    if missing:
        raise HarnessError("Long-page judgment missing checks: " + ", ".join(missing))
    failed = [name for name in required if not value["checks"][name].get("pass", False)]
    if value["status"] == "PASS" and failed:
        raise HarnessError("PASS long-page judgment contains failed checks: " + ", ".join(failed))
