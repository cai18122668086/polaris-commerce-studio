from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from runtime.assembly import assemble_vertical
from runtime.image_format import ensure_format_canvas, image_dimensions, normalize_generated_image
from runtime.prompt_compiler import compile_prompt
from runtime.performance_contract import resolve_performance_contract
from runtime.plan_normalizer import COMPACT_PLAN_FORMAT, normalize_plan
from runtime.sales_depth_contract import validate_sales_depth_contract, validate_formula_split_contract
from runtime.sales_architecture import (
    validate_dynamic_count_formula,
    validate_user_selling_point_ledger,
    validate_visual_archetypes,
)
from runtime.story_contract import validate_story_contract
from runtime.spatial_contract import resolve_spatial_contract, validate_spatial_contract
from runtime.state import (
    HarnessError,
    allowed_actions,
    atomic_write_json,
    atomic_write_text,
    current_module,
    load_json,
    require_fields,
    require_state,
)
from runtime.visual_gate import validate_long_page_judgment, validate_module_judgment


VERSION = "2.3.0"
COMPATIBLE_SESSION_VERSIONS = {"1.0", "1.1", "2.0.1", "2.2.1", VERSION}

INTERNAL_REVIEW_PROFILE_NAME = "INTERNAL_REVIEW_1440_3_4"
INTERNAL_REVIEW_RATIO = {"width_units": 3, "height_units": 4, "label": "3:4"}
INTERNAL_REVIEW_WIDTH_PX = 1440
INTERNAL_REVIEW_HEIGHT_PX = 1920
UNVERIFIED_ADAPTIVE_RATIO_OPTIONS = {"3:4", "9:16"}

FORBIDDEN_PIXEL_FACING_PLAN_PHRASES = (
    "包装可见", "作为包装宣称", "包装宣称来源", "来源边界", "证据边界",
    "风险核对", "风险澄清", "核对提醒", "当前证据不足", "未提供检测",
    "以实际商品页为准", "以实际包装为准", "以包装标示为准", "以包装标识为准",
    "购买前以实际规格", "购买前请核对", "包装标示", "包装标识", "当前仅能确认",
    "缺少检测报告", "待验证", "待核验", "未确认", "来源说明", "风险提示",
)


COMPLETE_STATUSES = {"COMPLETE", "COMPLETE_WITH_RESIDUALS"}


def _unique_strings(values) -> list[str]:
    result = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def validate_operating_input(raw: dict, fact_ids: set[str]) -> None:
    """Validate only the new route-aware contract; legacy inputs remain readable."""
    if "operating_analysis" not in raw:
        return
    route = raw.get("intake_route")
    if route not in ("USER_SELLING_POINT_LED", "PHOTO_TO_PRODUCT_STRATEGY"):
        raise HarnessError("Route-aware input must select a supported intake_route")
    supplied = raw.get("user_supplied_selling_points")
    if not isinstance(supplied, list):
        raise HarnessError("user_supplied_selling_points must be a list")
    if route == "USER_SELLING_POINT_LED" and not supplied:
        raise HarnessError("USER_SELLING_POINT_LED requires at least one concrete user-supplied selling point")
    if route == "PHOTO_TO_PRODUCT_STRATEGY" and supplied:
        raise HarnessError("PHOTO_TO_PRODUCT_STRATEGY cannot hide user-supplied selling points")
    supplied_ids = []
    for point in supplied:
        require_fields(point, ("id", "text", "source_ref", "fact_ids"), "user-supplied selling point")
        supplied_ids.append(point["id"])
        unknown = set(point["fact_ids"]) - fact_ids
        if unknown:
            raise HarnessError(f"User selling point {point['id']} refers to unknown atomic facts: {sorted(unknown)}")
    if len(supplied_ids) != len(set(supplied_ids)):
        raise HarnessError("User-supplied selling-point IDs must be unique")

    atomic_keys = []
    for fact in raw["verified_facts"]:
        require_fields(fact, ("atomic_key", "atomicity"), f"route-aware atomic fact {fact.get('id', '<unknown>')}")
        if fact["atomicity"] != "ONE_INDEPENDENT_PROPOSITION":
            raise HarnessError("Route-aware facts must each contain one independently coverable proposition")
        atomic_keys.append(fact["atomic_key"])
    if len(atomic_keys) != len(set(atomic_keys)):
        raise HarnessError("Atomic fact keys must be unique; split or deduplicate compound meanings")

    analysis = raw["operating_analysis"]
    require_fields(
        analysis,
        (
            "route_reason", "confirmed_fact_ids", "buyer_hypotheses", "pain_hypotheses",
            "value_bridges", "positioning_candidates", "selected_positioning_id",
            "assumption_disclosure",
        ),
        "operating analysis",
    )
    if "evidence_gaps" not in analysis or not isinstance(analysis["evidence_gaps"], list):
        raise HarnessError("operating_analysis.evidence_gaps must be a list; it may be empty")
    if set(analysis["confirmed_fact_ids"]) != fact_ids:
        raise HarnessError("operating_analysis.confirmed_fact_ids must account for every atomic verified fact")
    buyers = analysis["buyer_hypotheses"]
    pains = analysis["pain_hypotheses"]
    bridges = analysis["value_bridges"]
    candidates = analysis["positioning_candidates"]
    if not buyers or not pains or not bridges or not candidates:
        raise HarnessError("Operating analysis requires buyer, pain, value-bridge and positioning reasoning")
    buyer_ids = [item.get("id") for item in buyers]
    pain_ids = [item.get("id") for item in pains]
    if len(buyer_ids) != len(set(buyer_ids)) or any(not item for item in buyer_ids):
        raise HarnessError("Buyer-hypothesis IDs must be unique and non-empty")
    if len(pain_ids) != len(set(pain_ids)) or any(not item for item in pain_ids):
        raise HarnessError("Pain-hypothesis IDs must be unique and non-empty")
    for bridge in bridges:
        require_fields(
            bridge,
            ("id", "fact_ids", "pain_id", "feature", "buyer_benefit", "purchase_reason", "visual_route", "claim_permission"),
            "evidence-to-value bridge",
        )
        if set(bridge["fact_ids"]) - fact_ids:
            raise HarnessError(f"Value bridge {bridge['id']} uses unknown facts")
        if bridge["pain_id"] not in set(pain_ids):
            raise HarnessError(f"Value bridge {bridge['id']} uses an unknown pain hypothesis")
    candidate_ids = [item.get("id") for item in candidates]
    selected = [item for item in candidates if item.get("decision") == "SELECTED"]
    if len(candidate_ids) != len(set(candidate_ids)) or any(not item for item in candidate_ids):
        raise HarnessError("Positioning-candidate IDs must be unique and non-empty")
    if len(selected) != 1 or selected[0]["id"] != analysis["selected_positioning_id"]:
        raise HarnessError("Exactly one positioning candidate must be selected and match selected_positioning_id")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generation_references(session: dict) -> Tuple[List[str], Optional[str]]:
    """Return product evidence plus a series master only when it cannot collapse layout diversity."""
    master = None
    modules = session.get("modules", [])
    if session.get("current_index", 0) > 0 and modules:
        candidate = modules[0].get("accepted_asset")
        current_index = session.get("current_index", 0)
        current_plan = modules[current_index].get("plan", {}) if current_index < len(modules) else {}
        first_plan = modules[0].get("plan", {})
        current_spatial = resolve_spatial_contract(current_plan)
        first_spatial = resolve_spatial_contract(first_plan)
        same_spatial_grammar = (
            current_spatial.get("structure_family") == first_spatial.get("structure_family")
            and current_spatial.get("structural_relationship") == first_spatial.get("structural_relationship")
        )
        if candidate and same_spatial_grammar:
            master = candidate

    # The previous implementation encoded one cat-food SKU's role names here.
    # Preserve the user's identity-lock order instead, then use generic evidence
    # hints that work for every category.
    identity_order = {
        image_id: index
        for index, image_id in enumerate(session["identity"]["reference_image_ids"])
    }
    generic_role_priority = (
        "front", "identity", "hero", "overall", "product",
        "side", "back", "label", "detail", "component", "package", "scale", "scene",
    )

    def candidate_key(item: dict) -> tuple:
        role = item.get("role", "").lower()
        role_rank = next(
            (index for index, token in enumerate(generic_role_priority) if token in role),
            len(generic_role_priority),
        )
        return (identity_order.get(item["id"], 999), role_rank, item["id"])
    allowed_ids = set(session["identity"]["reference_image_ids"])
    candidates = [
        item for item in session["input"]["product_images"]
        if item["id"] in allowed_ids
    ]
    candidates.sort(key=candidate_key)

    references: List[str] = []
    if master:
        references.append(master)
    for item in candidates:
        if item["path"] not in references:
            references.append(item["path"])
        if len(references) == 5:
            break
    return references, master


def continuity_edge_reference(session: dict, session_path: str | Path) -> Optional[str]:
    """Create a small, non-layout-locking handoff strip from the accepted prior screen."""
    current_index = session.get("current_index", 0)
    modules = session.get("modules", [])
    if current_index <= 0 or current_index >= len(modules):
        return None
    previous = modules[current_index - 1].get("accepted_asset")
    if not previous or not Path(previous).is_file():
        return None
    try:
        from PIL import Image
        with Image.open(previous) as image:
            image = image.convert("RGB")
            strip_height = max(48, int(round(image.height * 0.08)))
            strip = image.crop((0, image.height - strip_height, image.width, image.height))
            out = Path(session_path).resolve().parent / "edge-states" / f"M{current_index + 1:02d}-incoming.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            strip.save(out, format="PNG", optimize=True)
            strip.close()
        return str(out)
    except Exception:
        return None


def save(session_path: str, session: dict, event: str) -> None:
    session.setdefault("events", []).append({"at": now(), "event": event, "state": session["state"]})
    session["updated_at"] = now()
    atomic_write_json(session_path, session)


def _seconds_between_events(session: dict) -> list[dict]:
    events = session.get("events", [])
    result = []
    for previous, current in zip(events, events[1:]):
        try:
            start = datetime.fromisoformat(previous["at"])
            end = datetime.fromisoformat(current["at"])
        except (KeyError, TypeError, ValueError):
            continue
        result.append({
            "from": previous.get("event"),
            "to": current.get("event"),
            "seconds": round((end - start).total_seconds(), 3),
        })
    return result


def _planning_elapsed_seconds(session: dict) -> Optional[float]:
    locked = next((item for item in reversed(session.get("events", [])) if item.get("event") == "identity_locked"), None)
    if not locked:
        return None
    try:
        return round((datetime.now(timezone.utc) - datetime.fromisoformat(locked["at"])).total_seconds(), 3)
    except (KeyError, TypeError, ValueError):
        return None


def cmd_start(args: argparse.Namespace) -> dict:
    raw = load_json(args.input)
    require_fields(raw, ("product_name", "category", "target_buyer", "product_images", "verified_facts", "platform_profile"), "input")
    profile = raw["platform_profile"]
    require_fields(profile, ("target_platform", "profile_name", "selection_mode", "selection_rationale", "source", "aspect_ratio", "canvas_width_px", "module_height_px", "safe_margin_px", "slice_height_px", "verification_status"), "platform profile")
    if profile["selection_mode"] not in ("ADAPTIVE_PLANNED", "USER_SPECIFIED", "PLATFORM_VERIFIED"):
        raise HarnessError("Platform profile must be deliberately selected before session start")
    if len(profile["selection_rationale"].strip()) < 20:
        raise HarnessError("Platform-profile selection requires a product-specific ratio and dimension rationale")
    ratio = profile["aspect_ratio"]
    require_fields(ratio, ("width_units", "height_units", "label"), "platform aspect ratio")
    if ratio["label"] != f"{ratio['width_units']}:{ratio['height_units']}":
        raise HarnessError("Platform aspect-ratio label does not match its numeric units")
    if profile["canvas_width_px"] * ratio["height_units"] != profile["module_height_px"] * ratio["width_units"]:
        raise HarnessError("Platform-profile dimensions do not match the declared aspect ratio")
    if (
        profile["selection_mode"] == "ADAPTIVE_PLANNED"
        and profile["verification_status"] != "VERIFIED_CURRENT_BACKEND"
    ):
        expected = (
            profile["profile_name"] == INTERNAL_REVIEW_PROFILE_NAME
            and ratio == INTERNAL_REVIEW_RATIO
            and profile["canvas_width_px"] == INTERNAL_REVIEW_WIDTH_PX
            and profile["module_height_px"] == INTERNAL_REVIEW_HEIGHT_PX
        )
        if not expected:
            raise HarnessError(
                "Platform-unverified ADAPTIVE_PLANNED work must use the internal-review master "
                "INTERNAL_REVIEW_1440_3_4 at 1440x1920, 3:4. Use USER_SPECIFIED only for an "
                "explicit user-approved profile, or PLATFORM_VERIFIED for a current backend rule."
            )
    raw.setdefault("coverage_directive", "MAXIMIZE_USER_SUPPLIED_RELEVANT_FACTS")
    raw.setdefault("question_budget", 0)
    if raw["coverage_directive"] != "MAXIMIZE_USER_SUPPLIED_RELEVANT_FACTS":
        raise HarnessError("Detail-page runs must maximize relevant user-supplied fact coverage")
    if raw["question_budget"] != 0:
        raise HarnessError("Default clarification-question budget must be zero")
    raw.setdefault("conflict_policy", "BLOCK_PLAN_AND_BATCH_ASK")
    raw.setdefault("source_conflicts", [])
    raw.setdefault("reference_materials", [])
    raw.setdefault("conflict_scan", {
        "status": "CLEAR" if not raw["source_conflicts"] else "CONFLICTS_FOUND",
        "scanned_topics": ["identity", "specification", "formula", "performance", "audience", "compliance"],
        "conflict_ids": [item.get("id") for item in raw["source_conflicts"]],
    })
    if raw["conflict_policy"] != "BLOCK_PLAN_AND_BATCH_ASK":
        raise HarnessError("Conflict policy must block planning and batch the necessary user confirmation")
    scan = raw["conflict_scan"]
    require_fields(scan, ("status", "scanned_topics"), "conflict scan")
    declared_conflict_ids = [item.get("id") for item in raw["source_conflicts"]]
    if len(declared_conflict_ids) != len(set(declared_conflict_ids)) or any(not item for item in declared_conflict_ids):
        raise HarnessError("Source conflict IDs must be unique and non-empty")
    if set(scan.get("conflict_ids", [])) != set(declared_conflict_ids):
        raise HarnessError("conflict_scan.conflict_ids must exactly match source_conflicts")
    expected_scan_status = "CONFLICTS_FOUND" if raw["source_conflicts"] else "CLEAR"
    if scan["status"] != expected_scan_status:
        raise HarnessError("Conflict scan status does not match the declared source conflicts")
    known_fact_ids = {item["id"] for item in raw["verified_facts"]}
    validate_operating_input(raw, known_fact_ids)
    known_reference_unit_ids = set()
    for reference in raw["reference_materials"]:
        require_fields(reference, ("id", "path", "category", "analysis_status", "observed_expression_methods"), "reference material")
        if "analyzed_units" not in reference or not isinstance(reference["analyzed_units"], list) or not reference["analyzed_units"]:
            raise HarnessError(f"Reference {reference.get('id', '<unknown>')} must be decomposed into at least one individual analyzed unit")
        if reference["analysis_status"] != "ANALYZED":
            raise HarnessError(f"Reference {reference['id']} must be decomposed before session start")
        unit_methods = []
        for unit in reference["analyzed_units"]:
            require_fields(
                unit,
                ("id", "source_region", "page_duty", "visual_carrier", "composition_logic", "typography_logic", "observed_expression_method"),
                f"analyzed reference unit for {reference['id']}",
            )
            if unit["id"] in known_reference_unit_ids:
                raise HarnessError(f"Analyzed reference unit ID must be globally unique: {unit['id']}")
            known_reference_unit_ids.add(unit["id"])
            unit_methods.append(unit["observed_expression_method"])
        if set(unit_methods) != set(reference["observed_expression_methods"]):
            raise HarnessError(
                f"Reference {reference['id']} observed_expression_methods must be derived exactly from its individual analyzed units"
            )
    for conflict in raw["source_conflicts"]:
        require_fields(conflict, ("id", "topic", "alternative_fact_ids", "why_material", "status"), "source conflict")
        alternatives = conflict["alternative_fact_ids"]
        if len(alternatives) < 2 or len(alternatives) != len(set(alternatives)):
            raise HarnessError(f"Conflict {conflict['id']} must contain at least two distinct fact alternatives")
        unknown = set(alternatives) - known_fact_ids
        if unknown:
            raise HarnessError(f"Conflict {conflict['id']} refers to unknown facts: {sorted(unknown)}")
        if conflict["status"] not in ("UNRESOLVED", "RESOLVED"):
            raise HarnessError(f"Conflict {conflict['id']} has an invalid status")
    for fact in raw["verified_facts"]:
        if "risk_route" not in fact:
            fact["risk_route"] = (
                "USER_CONFIRMED_FACT" if fact["source_class"] == "USER_FACT"
                else "DOCUMENTED_FACT"
            )
        fact.setdefault("display_intent", "SHOW_IF_RELEVANT")
    unresolved = [item for item in raw["source_conflicts"] if item["status"] == "UNRESOLVED"]
    if any(item["status"] == "RESOLVED" and not item.get("resolution") for item in raw["source_conflicts"]):
        raise HarnessError("Resolved source conflicts must preserve their user-confirmed resolution")
    session = {
        "version": VERSION,
        "state": "AWAITING_CONFLICT_RESOLUTION" if unresolved else "AWAITING_IDENTITY",
        "created_at": now(),
        "updated_at": now(),
        "input": raw,
        "identity": None,
        "plan": None,
        "approval": None,
        "modules": [],
        "current_index": 0,
        "active_token": None,
        "assembly": None,
        "long_page_audit": None,
        "final": None,
        "feedback_constraints": {
            "global": {"preserve": [], "must_not_regress": []},
            "by_module": {},
        },
        "planning_fact_ids": sorted(known_fact_ids),
        "conflict_checkpoint": {
            "required": bool(unresolved),
            "conflict_ids": [item["id"] for item in unresolved],
            "instruction": "Ask one batched question listing the exact conflicting values and wait for the user's decision before identity lock or full planning.",
        },
        "events": [],
    }
    save(args.session, session, "session_started")
    return summary(session)


def cmd_resolve_conflicts(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AWAITING_CONFLICT_RESOLUTION")
    resolution = load_json(args.resolution)
    require_fields(resolution, ("confirmation_text", "resolutions"), "conflict resolution")
    if not str(resolution["confirmation_text"]).strip():
        raise HarnessError("Conflict resolution must preserve the user's confirmation words")
    conflicts = {item["id"]: item for item in session["input"].get("source_conflicts", []) if item["status"] == "UNRESOLVED"}
    supplied = {item.get("conflict_id"): item for item in resolution["resolutions"]}
    if set(supplied) != set(conflicts):
        raise HarnessError("One batched resolution must cover every unresolved conflict exactly once")
    rejected_fact_ids = set()
    for conflict_id, item in supplied.items():
        require_fields(item, ("conflict_id", "retained_fact_ids", "rejected_fact_ids"), "conflict resolution item")
        conflict = conflicts[conflict_id]
        retained = set(item["retained_fact_ids"])
        rejected = set(item["rejected_fact_ids"])
        alternatives = set(conflict["alternative_fact_ids"])
        if not retained or retained & rejected or retained | rejected != alternatives:
            raise HarnessError(f"Resolution for {conflict_id} must retain at least one alternative and account for all others")
        conflict["status"] = "RESOLVED"
        conflict["resolution"] = {
            "confirmation_text": resolution["confirmation_text"],
            "retained_fact_ids": sorted(retained),
            "rejected_fact_ids": sorted(rejected),
        }
        rejected_fact_ids.update(rejected)
    all_fact_ids = {item["id"] for item in session["input"]["verified_facts"]}
    session["planning_fact_ids"] = sorted(all_fact_ids - rejected_fact_ids)
    session["conflict_checkpoint"] = {"required": False, "conflict_ids": [], "resolved_at": now()}
    session["state"] = "AWAITING_IDENTITY"
    save(args.session, session, "conflicts_resolved")
    return summary(session)


def cmd_lock_identity(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AWAITING_IDENTITY")
    if any(item.get("status") == "UNRESOLVED" for item in session["input"].get("source_conflicts", [])):
        raise HarnessError("Identity lock is forbidden until every material source conflict is user-resolved")
    identity = load_json(args.identity)
    require_fields(identity, ("canonical_name", "category", "reference_image_ids", "invariant_features", "allowed_states", "forbidden_mutations"), "identity")
    if "uncertain_features" not in identity or not isinstance(identity["uncertain_features"], list):
        raise HarnessError("identity uncertain_features must be present as an array; it may be empty when no uncertainty remains")
    known_ids = {item["id"] for item in session["input"]["product_images"]}
    unknown = set(identity["reference_image_ids"]) - known_ids
    if unknown:
        raise HarnessError(f"Identity refers to unknown product images: {sorted(unknown)}")
    logo_source = identity.get("brand_logo_source")
    if not isinstance(logo_source, dict):
        raise HarnessError("Identity requires brand_logo_source for the mandatory first-screen independent logo")
    require_fields(
        logo_source,
        ("image_id", "authorization_basis", "readability", "usage"),
        "brand logo source",
    )
    if logo_source["image_id"] not in known_ids:
        raise HarnessError("Brand logo source must name a supplied current-product image")
    if logo_source["authorization_basis"] != "USER_SUPPLIED_CURRENT_PRODUCT":
        raise HarnessError("Brand logo source must be authorized by the user-supplied current-product evidence")
    if logo_source["readability"] != "READABLE":
        raise HarnessError("The first-screen logo hard gate requires a readable source brand mark")
    if logo_source["usage"] != "FIRST_SCREEN_INDEPENDENT_LOGO":
        raise HarnessError("Brand logo source usage must be FIRST_SCREEN_INDEPENDENT_LOGO")
    session["identity"] = identity
    session["state"] = "IDENTITY_LOCKED"
    save(args.session, session, "identity_locked")
    return summary(session)


def _collect_plan_mapping_errors(session: dict, plan: dict) -> list[str]:
    """Report common cross-ledger mapping faults in one pass instead of one retry at a time."""
    errors: list[str] = []
    modules = [item for item in plan.get("modules", []) if isinstance(item, dict)]
    module_by_id = {item.get("id"): item for item in modules if item.get("id")}
    known_module_ids = set(module_by_id)
    strategy = plan.get("output_strategy", {}) if isinstance(plan.get("output_strategy"), dict) else {}
    clusters = strategy.get("selling_point_clusters", [])
    cluster_by_id = {
        item.get("id"): item for item in clusters if isinstance(item, dict) and item.get("id")
    }
    for cluster_id, cluster in cluster_by_id.items():
        assigned = cluster.get("assigned_module_ids")
        if not isinstance(assigned, list):
            errors.append(f"selling-point cluster {cluster_id} needs assigned_module_ids")
            continue
        unknown = set(assigned) - known_module_ids
        if unknown:
            errors.append(f"selling-point cluster {cluster_id} cites unknown modules {sorted(unknown)}")
        for module_id in set(assigned) & known_module_ids:
            if cluster_id not in module_by_id[module_id].get("selling_point_cluster_ids", []):
                errors.append(f"cluster {cluster_id} assigns {module_id}, but that module does not declare it")

    for item in strategy.get("claim_coverage", []):
        if not isinstance(item, dict):
            errors.append("claim_coverage contains a non-object item")
            continue
        claim_id = item.get("claim_id", "?")
        module_ids = item.get("module_ids")
        if not isinstance(module_ids, list):
            errors.append(f"claim {claim_id} needs a module_ids list")
            continue
        unknown = set(module_ids) - known_module_ids
        if unknown:
            errors.append(f"claim {claim_id} cites unknown modules {sorted(unknown)}")
        disposition = item.get("disposition")
        defer_code = item.get("defer_reason_code")
        if disposition == "DEFERRED":
            if module_ids:
                errors.append(f"deferred claim {claim_id} cannot be assigned to modules")
            if defer_code not in {
                "CONFLICTING_FACT", "HIGH_RISK_UNDOCUMENTED", "UNSUPPORTED_INVENTION", "IMMATERIAL_DUPLICATE"
            }:
                errors.append(f"deferred claim {claim_id} needs an allowed defer reason")
            continue
        if defer_code != "NOT_DEFERRED":
            errors.append(f"selected claim {claim_id} must use NOT_DEFERRED")
        if not module_ids:
            errors.append(f"selected claim {claim_id} needs at least one assigned module")
        for module_id in set(module_ids) & known_module_ids:
            module = module_by_id[module_id]
            used = {module.get("lead_claim_id"), *module.get("supporting_claim_ids", [])}
            if claim_id not in used:
                errors.append(f"claim {claim_id} is assigned to {module_id}, but that module does not use it")
        if disposition == "LEAD" and module_ids and not any(
            module_by_id[module_id].get("lead_claim_id") == claim_id
            for module_id in set(module_ids) & known_module_ids
        ):
            errors.append(f"lead claim {claim_id} is not the lead claim of an assigned module")
    return _unique_strings(errors)


def validate_plan(session: dict, plan: dict) -> None:
    if any(item.get("status") == "UNRESOLVED" for item in session["input"].get("source_conflicts", [])):
        raise HarnessError("Full planning is forbidden while product-source conflicts remain unresolved")
    require_fields(plan, ("campaign_thesis", "dominant_decision_type", "output_strategy", "reference_expression_system", "style_constitution", "series_visual_dna", "typography_rhythm", "modules"), "plan")
    legacy_ledgers = [
        name for name in ("visual_performance_rhythm", "spatial_structure_rhythm")
        if name in plan
    ]
    if legacy_ledgers:
        raise HarnessError(
            "v1.0 lightweight planning derives performance and spatial rhythm at runtime; "
            f"remove duplicated legacy ledgers: {', '.join(legacy_ledgers)}"
        )
    mapping_errors = _collect_plan_mapping_errors(session, plan)
    if mapping_errors:
        raise HarnessError(
            f"Plan mapping preflight found {len(mapping_errors)} issue(s):\n- "
            + "\n- ".join(mapping_errors)
        )
    route_aware = "operating_analysis" in session["input"]
    if route_aware:
        require_fields(plan, ("operating_strategy", "campaign_recall_contract", "campaign_pain_solution_contract", "campaign_visual_carrier_sequence", "selling_point_depth_contract"), "route-aware plan")
    strategy = plan["output_strategy"]
    # v1.0 makes the series-master inheritance boundary a runtime invariant.
    # A plan may document it, but cannot weaken it or repeat a large manual ledger.
    require_fields(
        strategy,
        (
            "target_platform", "profile_name", "selection_mode", "module_count",
            "module_count_rationale", "module_count_candidates", "selling_point_clusters", "merge_decisions", "claim_coverage",
            "aspect_ratio", "ratio_candidates", "canvas_width_px", "module_height_px", "safe_margin_px",
            "slice_height_px", "ratio_rationale", "dimension_rationale",
            "uniform_dimensions", "verification_status",
        ),
        "output strategy",
    )
    if strategy["selection_mode"] not in ("ADAPTIVE_PLANNED", "USER_SPECIFIED", "PLATFORM_VERIFIED"):
        raise HarnessError("Output strategy must be deliberately planned; implicit engineered defaults are forbidden")
    if len(strategy["module_count_rationale"].strip()) < 20:
        raise HarnessError("Module-count rationale must explain the product-specific grouping decision")
    if len(strategy["module_count_candidates"]) < 2:
        raise HarnessError("Module count must be selected after comparing selling-point coverage options")
    for candidate in strategy["module_count_candidates"]:
        required_candidate_fields = ("count", "coverage_tradeoff", "selling_point_fit", "decision", "story_obligation_fit") if route_aware else ("count", "coverage_tradeoff", "selling_point_fit", "decision")
        require_fields(candidate, required_candidate_fields, "module-count candidate")
    candidate_counts = [item.get("count") for item in strategy["module_count_candidates"]]
    if len(candidate_counts) != len(set(candidate_counts)):
        raise HarnessError("Module-count candidates must compare distinct counts")
    if strategy["module_count"] not in candidate_counts:
        raise HarnessError("Selected module_count must match one evaluated selling-point candidate")
    selected_candidates = [item for item in strategy["module_count_candidates"] if item["decision"] == "SELECTED"]
    if len(selected_candidates) != 1 or selected_candidates[0]["count"] != strategy["module_count"]:
        raise HarnessError("Exactly one module-count candidate must be selected and match module_count")
    if route_aware:
        expected_modes = {"COMPACT_COVERAGE", "BALANCED_EXPRESSION", "FULL_SALES"}
        actual_modes = {item.get("candidate_mode") for item in strategy["module_count_candidates"]}
        if len(strategy["module_count_candidates"]) != 3 or actual_modes != expected_modes:
            raise HarnessError(
                "Route-aware planning must compare exactly compact, balanced and full-sales candidates "
                "(COMPACT_COVERAGE, BALANCED_EXPRESSION, FULL_SALES)"
            )
    if len(strategy["ratio_candidates"]) != 2:
        raise HarnessError("Output strategy must compare exactly two plausible aspect-ratio options")
    ratio_labels = []
    for candidate in strategy["ratio_candidates"]:
        require_fields(candidate, ("label", "composition_fit", "mobile_reading_tradeoff", "decision"), "ratio candidate")
        ratio_labels.append(candidate["label"])
    if len(set(ratio_labels)) != 2:
        raise HarnessError("Ratio candidates must compare two distinct ratios")
    selected_ratios = [item for item in strategy["ratio_candidates"] if item["decision"] == "SELECTED"]
    if len(selected_ratios) != 1 or selected_ratios[0]["label"] != strategy["aspect_ratio"]["label"]:
        raise HarnessError("Exactly one ratio candidate must be selected and match aspect_ratio")
    if (
        strategy["selection_mode"] == "ADAPTIVE_PLANNED"
        and strategy["verification_status"] != "VERIFIED_CURRENT_BACKEND"
        and set(ratio_labels) != UNVERIFIED_ADAPTIVE_RATIO_OPTIONS
    ):
        raise HarnessError(
            "Unverified adaptive planning must compare the controlled internal options 3:4 and 9:16; "
            "4:5, 9:10 and other ad-hoc ratios require USER_SPECIFIED or PLATFORM_VERIFIED evidence"
        )
    if len(strategy["ratio_rationale"].strip()) < 20:
        raise HarnessError("Aspect-ratio rationale must explain the product, mobile-reading and composition decision")
    if len(strategy["dimension_rationale"].strip()) < 20:
        raise HarnessError("Dimension rationale must explain the working-master and delivery relationship")
    if not strategy["merge_decisions"] or not all(str(item).strip() for item in strategy["merge_decisions"]):
        raise HarnessError("Output strategy must record at least one explicit merge or separation decision")
    if strategy["uniform_dimensions"] is not True:
        raise HarnessError("All generated detail modules must use one approved width, height and aspect ratio")

    profile = session["input"]["platform_profile"]
    profile_pairs = (
        ("profile_name", "profile_name"),
        ("canvas_width_px", "canvas_width_px"),
        ("module_height_px", "module_height_px"),
        ("safe_margin_px", "safe_margin_px"),
        ("slice_height_px", "slice_height_px"),
        ("verification_status", "verification_status"),
    )
    for strategy_key, profile_key in profile_pairs:
        if strategy[strategy_key] != profile[profile_key]:
            raise HarnessError(f"Output strategy {strategy_key} does not match the selected platform profile")
    if strategy["target_platform"] != profile["target_platform"]:
        raise HarnessError("Output strategy target_platform does not match the selected platform profile")
    if strategy["selection_mode"] != profile["selection_mode"]:
        raise HarnessError("Output strategy selection_mode does not match the selected platform profile")
    ratio = strategy["aspect_ratio"]
    require_fields(ratio, ("width_units", "height_units", "label"), "aspect ratio")
    expected_label = f"{ratio['width_units']}:{ratio['height_units']}"
    if ratio["label"] != expected_label:
        raise HarnessError("Aspect-ratio label does not match its numeric units")
    if ratio != profile["aspect_ratio"]:
        raise HarnessError("Output strategy aspect ratio does not match the selected platform profile")
    if strategy["canvas_width_px"] * ratio["height_units"] != strategy["module_height_px"] * ratio["width_units"]:
        raise HarnessError("Approved pixel dimensions do not exactly match the declared aspect ratio")
    dna = plan["series_visual_dna"]
    require_fields(
        dna,
        ("brand_anchor_system", "palette_tokens", "typography_tokens", "graphic_tokens", "photography_tokens", "product_tokens", "spatial_tokens", "invariants"),
        "series visual DNA",
    )
    if len(dna["invariants"]) < 2:
        raise HarnessError("Series visual DNA requires at least two campaign invariants")
    typography_rhythm = plan["typography_rhythm"]
    require_fields(
        typography_rhythm,
        (
            "campaign_rule", "primary_mode_sequence", "anchor_zone_sequence",
            "centered_hero_max", "consecutive_anchor_repeat_limit",
        ),
        "typography rhythm",
    )
    if "exceptions" not in typography_rhythm or not isinstance(typography_rhythm["exceptions"], list):
        raise HarnessError("Typography rhythm exceptions must be a list, using an empty list when none")
    if not isinstance(typography_rhythm["centered_hero_max"], int) or typography_rhythm["centered_hero_max"] < 0:
        raise HarnessError("Typography rhythm centered_hero_max must be a non-negative integer")
    if not plan["modules"]:
        raise HarnessError("A detail page requires at least one purposeful module")
    if strategy["module_count"] != len(plan["modules"]):
        raise HarnessError("Planned module_count must exactly equal the storyboard module count")
    fact_ids = set(session.get("planning_fact_ids") or [item["id"] for item in session["input"]["verified_facts"]])
    facts_by_id = {item["id"]: item for item in session["input"]["verified_facts"]}
    performance_overrides = [
        module for module in plan["modules"]
        if module.get("module_visual_performance_contract")
    ]
    override_budget = max(1, len(plan["modules"]) // 6)
    if len(performance_overrides) > override_budget:
        raise HarnessError(
            f"v1.0 lightweight planning allows at most {override_budget} deliberate visual-performance "
            "override(s) for this page; ordinary modules must use runtime-derived contracts"
        )
    for module in performance_overrides:
        reason = str(module.get("performance_override_reason", "")).strip()
        if len(reason) < 20:
            raise HarnessError(
                f"Module {module.get('id', '?')} uses a visual-performance override without a concrete "
                "performance_override_reason; remove the override or explain the exceptional need"
            )
    if route_aware:
        operating = plan["operating_strategy"]
        require_fields(
            operating,
            (
                "intake_route", "target_buyer", "primary_pain_id", "selected_positioning_id",
                "core_promise", "priority_claim_ids", "assumption_boundary",
            ),
            "operating strategy",
        )
        if "supporting_claim_ids" not in operating or not isinstance(operating["supporting_claim_ids"], list):
            raise HarnessError("operating_strategy.supporting_claim_ids must be a list; it may be empty")
        analysis = session["input"]["operating_analysis"]
        if operating["intake_route"] != session["input"]["intake_route"]:
            raise HarnessError("Plan operating route must match the route selected at intake")
        if operating["selected_positioning_id"] != analysis["selected_positioning_id"]:
            raise HarnessError("Plan must preserve the selected product positioning")
        pain_ids = {item["id"] for item in analysis["pain_hypotheses"]}
        if operating["primary_pain_id"] not in pain_ids:
            raise HarnessError("Plan primary pain must come from the operating analysis")
        priority_claim_ids = set(operating["priority_claim_ids"])
        supporting_claim_ids = set(operating["supporting_claim_ids"])
        if not priority_claim_ids or priority_claim_ids - fact_ids or supporting_claim_ids - fact_ids:
            raise HarnessError("Operating strategy claim priorities must use active verified facts")
        if priority_claim_ids & supporting_claim_ids:
            raise HarnessError("A claim cannot be both priority and supporting in the operating strategy")
    clusters = strategy["selling_point_clusters"]
    if not clusters:
        raise HarnessError("Selling-point clusters are required before module count can be chosen")
    cluster_ids = [item.get("id") for item in clusters]
    if len(cluster_ids) != len(set(cluster_ids)) or any(not item for item in cluster_ids):
        raise HarnessError("Selling-point cluster IDs must be unique and non-empty")
    clustered_fact_ids = []
    for cluster in clusters:
        require_fields(cluster, ("id", "buyer_question", "fact_ids", "purchase_role", "separation_policy", "assigned_module_ids"), "selling-point cluster")
        clustered_fact_ids.extend(cluster["fact_ids"])
    if len(clustered_fact_ids) != len(set(clustered_fact_ids)) or set(clustered_fact_ids) != fact_ids:
        raise HarnessError("Selling-point clusters must account for every active fact exactly once before screen-count planning")
    coverage = strategy["claim_coverage"]
    coverage_ids = [item.get("claim_id") for item in coverage]
    if len(coverage_ids) != len(set(coverage_ids)):
        raise HarnessError("Each verified fact must appear exactly once in claim_coverage")
    if set(coverage_ids) != fact_ids:
        missing = sorted(fact_ids - set(coverage_ids))
        unknown = sorted(set(coverage_ids) - fact_ids)
        raise HarnessError(f"claim_coverage must account for every verified fact; missing={missing}, unknown={unknown}")
    module_ids = []
    expected_order = 1
    previous_module = None
    for module in plan["modules"]:
        require_fields(
            module,
            ("id", "order", "duty", "buyer_question", "lead_conclusion", "lead_claim_id", "selling_point_cluster_ids", "visual_proof_direction", "visual_evidence", "visual_proof_contract", "module_spatial_structure_contract", "copy_intent", "composition_family", "camera_scale", "text_system", "reading_path", "copy_density", "visual_payload_density", "proof_relation_strength", "commercial_energy", "breathing_screen", "brand_anchor", "independent_logo_policy", "independent_logo_source_id", "inherited_dna_tokens", "variation_from_previous", "output"),
            "plan module",
        )
        for optional_empty_key in ("reference_pattern_ids", "visible_copy"):
            if optional_empty_key not in module or not isinstance(module[optional_empty_key], list):
                raise HarnessError(f"plan module missing required list field: {optional_empty_key}")
        for field_name in ("duty", "buyer_question", "lead_conclusion", "visual_proof_direction"):
            field_value = str(module.get(field_name, ""))
            leaked = [phrase for phrase in FORBIDDEN_PIXEL_FACING_PLAN_PHRASES if phrase in field_value]
            if leaked:
                raise HarnessError(
                    f"Module {module['id']} leaks internal evidence/compliance provenance into {field_name}: "
                    f"{', '.join(leaked)}. Keep provenance machine-side and write a buyer-facing sales conclusion."
                )
        if "形成清晰的产品绑定画面" in str(module["visual_proof_direction"]):
            raise HarnessError(
                f"Module {module['id']} uses a generic visual-proof placeholder; name the concrete objects, "
                "action/state relation and visible buyer takeaway"
            )
        require_fields(module["visual_evidence"], ("evidence_class", "proof_device", "visible_content", "forbidden_inventions"), f"visual evidence for {module['id']}")
        contract = module["visual_proof_contract"]
        require_fields(contract, ("buyer_takeaway", "visual_verb", "primary_subject", "supporting_subjects", "required_relations", "minimum_visual_payload", "visual_specificity_anchor", "allowed_metaphor", "hidden_copy_test"), f"visual proof contract for {module['id']}")
        expression_contract = module.get("module_visual_expression_contract", {})
        for label, value in (
            ("visual_proof_contract.buyer_takeaway", contract.get("buyer_takeaway")),
            ("visual_proof_contract.visual_verb", contract.get("visual_verb")),
            ("module_visual_expression_contract.visual_scene_sentence", expression_contract.get("visual_scene_sentence")),
            ("module_visual_expression_contract.visual_semantic_payload", expression_contract.get("visual_semantic_payload")),
        ):
            leaked = [phrase for phrase in FORBIDDEN_PIXEL_FACING_PLAN_PHRASES if phrase in str(value or "")]
            if leaked:
                raise HarnessError(
                    f"Module {module['id']} leaks internal provenance into prompt-facing {label}: "
                    f"{', '.join(leaked)}"
                )
        if contract["minimum_visual_payload"] < 3 and not module["breathing_screen"]:
            raise HarnessError(f"Module {module['id']} must require at least three effective visual payloads unless it is an explicit breathing screen")
        performance = resolve_performance_contract(module, order=module["order"], module_count=len(plan["modules"]))
        require_fields(
            performance,
            (
                "strategy_type", "target_energy", "product_dominance", "product_prominence_min_percent",
                "headline_dominance", "headline_must_enter_top_three", "headline_rank_max",
                "primary_evidence_anchor", "evidence_must_be_primary_visual", "depth_plan", "depth_layers_min",
                "visual_tension", "visual_tension_required", "background_competition_max", "information_density",
                "type_role_target", "unequal_information_groups_min", "mobile_scan_stops_min", "mobile_scan_order",
                "commercial_closure", "commercial_closure_required", "creative_permissions", "forbidden_regression",
            ),
            f"visual performance contract for {module['id']}",
        )
        allowed_strategies = {
            "FIRST_SCREEN_CORE_BENEFIT", "PAIN", "PAIN_SOLUTION_COMBINED", "EFFICACY_PROOF", "MECHANISM", "MATERIAL_INGREDIENT",
            "USE_SCENE", "PARAMETER_SPECIFICATION", "TRUST", "PURCHASE_CLOSURE", "OTHER_PRODUCT_PROOF",
        }
        if performance["strategy_type"] not in allowed_strategies:
            raise HarnessError(f"Module {module['id']} has an unsupported visual-performance strategy")
        if performance["target_energy"] not in ("MEDIUM", "MEDIUM_HIGH", "HIGH"):
            raise HarnessError(f"Module {module['id']} has an unsupported performance-energy target")
        if not 0 <= performance["product_prominence_min_percent"] <= 90:
            raise HarnessError(f"Module {module['id']} product-prominence threshold must be between 0 and 90 percent")
        if performance["headline_must_enter_top_three"] and performance["headline_rank_max"] > 3:
            raise HarnessError(f"Module {module['id']} headline must enter the top three visual ranks")
        if performance["headline_must_enter_top_three"] and not module["visible_copy"]:
            raise HarnessError(f"Module {module['id']} requires a dominant headline but has no approved visible copy")
        if performance["depth_layers_min"] < (2 if module["breathing_screen"] else 3):
            raise HarnessError(f"Module {module['id']} lacks the required visual depth")
        if performance["information_density"] == "LOW" and not module["breathing_screen"]:
            raise HarnessError(f"Module {module['id']} may use low information density only as an approved breathing screen")
        if performance["mobile_scan_stops_min"] < (2 if module["breathing_screen"] else 3):
            raise HarnessError(f"Module {module['id']} lacks enough mobile scan stops for its role")
        if len(performance["mobile_scan_order"]) < performance["mobile_scan_stops_min"]:
            raise HarnessError(f"Module {module['id']} scan order is shorter than its approved scan-stop minimum")
        if performance["background_competition_max"] not in ("LOW", "LOW_TO_MEDIUM", "MEDIUM"):
            raise HarnessError(f"Module {module['id']} has an unsupported background-competition ceiling")
        if len(performance["creative_permissions"]) < 2:
            raise HarnessError(f"Module {module['id']} needs at least two evidence-grounded creative permissions")
        if len(set(performance["forbidden_regression"])) < 5:
            raise HarnessError(f"Module {module['id']} must preserve the five core visual-performance anti-regressions")
        if module["copy_density"] in ("none", "low") and module["visual_payload_density"] == "low" and not module["breathing_screen"]:
            raise HarnessError(f"Module {module['id']} confuses low copy with low visual payload")
        if module["proof_relation_strength"] == "weak" and not module["breathing_screen"]:
            raise HarnessError(f"Module {module['id']} requires a visible proof relationship, not a weak decorative association")
        if module["commercial_energy"] == "restrained" and module["visual_payload_density"] == "low" and not module["breathing_screen"]:
            raise HarnessError(f"Module {module['id']} would become an underpowered concept poster")
        copy_limits = {"none": (0, 0), "low": (1, 3), "medium": (2, 5), "high": (3, 8)}
        minimum_copy, maximum_copy = copy_limits[module["copy_density"]]
        if not module["breathing_screen"] and module["copy_density"] == "none":
            raise HarnessError(f"Module {module['id']} may not interpret visual-first as text-free")
        if not minimum_copy <= len(module["visible_copy"]) <= maximum_copy:
            raise HarnessError(f"Module {module['id']} visible-copy whitelist exceeds its copy-density limit")
        copy_intent = module["copy_intent"]
        require_fields(copy_intent, ("policy", "why_text_is_needed", "text_to_visual_bindings", "hidden_copy_takeaway", "copy_adds"), f"copy intent for {module['id']}")
        if copy_intent["policy"] != "VISUAL_FIRST_WITH_AUXILIARY_COPY":
            raise HarnessError(f"Module {module['id']} must use imagery as primary proof and copy as auxiliary guidance")
        whitelist = [item["text"] for item in module["visible_copy"]]
        for item in module["visible_copy"]:
            copy_text = str(item.get("text", ""))
            leaked = [phrase for phrase in FORBIDDEN_PIXEL_FACING_PLAN_PHRASES if phrase in copy_text]
            role = str(item.get("role", "")).lower()
            if leaked:
                raise HarnessError(
                    f"Module {module['id']} visible copy leaks machine-side provenance or workflow language: "
                    f"{', '.join(leaked)}"
                )
        bound_copy = [item.get("text") for item in copy_intent["text_to_visual_bindings"]]
        if sorted(whitelist) != sorted(bound_copy):
            raise HarnessError(f"Every visible copy unit in {module['id']} must be bound to a visible object, relation or result")
        require_fields(
            module["text_system"],
            (
                "primary_mode", "anchor_target", "anchor_zone", "reading_direction",
                "placement_logic", "hierarchy", "max_lines", "container_style",
                "negative_space_reservation", "image_text_relationship",
                "composition_flexibility", "neighbor_difference",
            ),
            f"text system for {module['id']}",
        )
        if "supporting_mode" not in module["text_system"]:
            raise HarnessError(f"Text system for {module['id']} must declare supporting_mode, using null when absent")
        if not isinstance(module["text_system"]["max_lines"], int) or module["text_system"]["max_lines"] < 1:
            raise HarnessError(f"Text system for {module['id']} max_lines must be a positive integer")
        if module["text_system"]["composition_flexibility"] not in ("LOCKED", "NEGATIVE_SPACE_ONLY", "CONTROLLED_REFLOW"):
            raise HarnessError(f"Text system for {module['id']} has an unsupported composition_flexibility")
        if len(module["inherited_dna_tokens"]) < 2:
            raise HarnessError(f"Module {module['id']} must inherit at least two series visual-DNA tokens")
        expected_logo_policy = "REQUIRED_IF_AUTHORIZED" if module["order"] == 1 else "FORBIDDEN"
        if module["independent_logo_policy"] != expected_logo_policy:
            raise HarnessError(
                f"Module {module['id']} independent_logo_policy must be {expected_logo_policy}; "
                "independent brand logos are allowed only on the first screen"
            )
        expected_logo_source = session["identity"]["brand_logo_source"]["image_id"] if module["order"] == 1 else "NONE"
        if module["independent_logo_source_id"] != expected_logo_source:
            raise HarnessError(
                f"Module {module['id']} independent_logo_source_id must be {expected_logo_source}; "
                "M01 must bind the authorized logo source and later screens must use NONE"
            )
        if previous_module:
            same_composition = module["composition_family"] == previous_module["composition_family"]
            same_text = module["text_system"]["primary_mode"] == previous_module["text_system"]["primary_mode"]
            same_anchor = module["text_system"]["anchor_zone"] == previous_module["text_system"]["anchor_zone"]
            if (same_composition and same_text or same_text and same_anchor) and not module.get("repeat_justification", "").strip():
                raise HarnessError(
                    f"Module {module['id']} repeats a composition/typography placement pair from {previous_module['id']} without a transition justification"
                )
            if not module["variation_from_previous"]:
                raise HarnessError(f"Module {module['id']} must declare visible variation from the previous module")
        if module["order"] != expected_order:
            raise HarnessError("Module order must be continuous and start at 1")
        expected_order += 1
        module_ids.append(module["id"])
        unknown_clusters = set(module["selling_point_cluster_ids"]) - set(cluster_ids)
        if unknown_clusters or not module["selling_point_cluster_ids"]:
            raise HarnessError(f"Module {module['id']} must serve known selling-point clusters")
        used = {module["lead_claim_id"], *module.get("supporting_claim_ids", [])}
        unknown = used - fact_ids - {"NO_FACT_CLOSURE"}
        if unknown:
            raise HarnessError(f"Module {module['id']} uses unknown fact IDs: {sorted(unknown)}")
        if module.get("story_function") == "TRUST_OR_RISK_REMOVAL":
            documented = [
                fact_id for fact_id in used
                if fact_id in facts_by_id and facts_by_id[fact_id].get("source_class") == "DOCUMENTED_EVIDENCE"
            ]
            if not documented:
                raise HarnessError(
                    f"Module {module['id']} is a trust/risk-only screen without independent documented evidence; "
                    "defer the unsupported point or attach its qualifier to the relevant selling screen"
                )
        output = module["output"]
        if output["width_px"] != strategy["canvas_width_px"] or output["height_px"] != strategy["module_height_px"] or output["safe_margin_px"] != strategy["safe_margin_px"]:
            raise HarnessError(f"Module {module['id']} dimensions do not match the approved output strategy")
        previous_module = module
    if len(module_ids) != len(set(module_ids)):
        raise HarnessError("Module IDs must be unique")
    # Performance and spatial rhythm are resolved from compact per-module blueprints.
    first_performance = resolve_performance_contract(plan["modules"][0], 1, len(plan["modules"]))
    if first_performance["strategy_type"] != "FIRST_SCREEN_CORE_BENEFIT":
        raise HarnessError("The first module must use the core-benefit performance strategy")
    if first_performance["target_energy"] != "HIGH":
        raise HarnessError("The first module must remain a HIGH visual-performance peak")
    if len(plan["modules"]) > 1:
        last_performance = resolve_performance_contract(
            plan["modules"][-1], len(plan["modules"]), len(plan["modules"])
        )
        if last_performance["strategy_type"] != "PURCHASE_CLOSURE" or last_performance["target_energy"] != "HIGH":
            raise HarnessError("The final module must close the purchase story at HIGH visual performance")
    support_only = [
        module for module in plan["modules"]
        if module.get("story_function") == "TRUST_OR_RISK_REMOVAL"
    ]
    support_budget = max(1, len(plan["modules"]) // 5)
    if len(support_only) > support_budget:
        raise HarnessError(
            "Trust, qualification and risk-only screens exceed the sales-support budget; "
            "attach qualifiers to the claim screen or combine them with product/use information"
        )
    known_module_ids = set(module_ids)
    module_by_id = {item["id"]: item for item in plan["modules"]}
    validate_spatial_contract(plan)
    if route_aware:
        validate_sales_depth_contract(plan, fact_ids)
        validate_formula_split_contract(plan, fact_ids)
        validate_story_contract(plan, session["input"]["operating_analysis"])
        if plan.get("plan_format") == "COMPACT_V1_2":
            validate_user_selling_point_ledger(
                plan,
                session["input"].get("user_supplied_selling_points", []),
                fact_ids,
            )
            validate_dynamic_count_formula(plan)
            validate_visual_archetypes(plan)
        recall = plan["campaign_recall_contract"]
        require_fields(
            recall,
            (
                "must_remember_claim_ids", "first_screen_value_claim_ids",
                "proof_module_ids_by_claim", "closure_reinforcement_claim_ids", "buyer_recall_test",
            ),
            "campaign recall contract",
        )
        must_remember = set(recall["must_remember_claim_ids"])
        first_claims = set(recall["first_screen_value_claim_ids"])
        closure_claims = set(recall["closure_reinforcement_claim_ids"])
        if not must_remember or not first_claims or not closure_claims:
            raise HarnessError("Recall contract requires must-remember, first-screen and closing claim sets")
        if must_remember - priority_claim_ids or first_claims - must_remember or closure_claims - must_remember:
            raise HarnessError("Recall contract claim sets must remain within the priority verified claims")
        first_module_claims = {plan["modules"][0]["lead_claim_id"], *plan["modules"][0].get("supporting_claim_ids", [])}
        last_module_claims = {plan["modules"][-1]["lead_claim_id"], *plan["modules"][-1].get("supporting_claim_ids", [])}
        if first_claims - first_module_claims:
            raise HarnessError("First-screen value claims must be carried by the first module")
        if closure_claims - last_module_claims:
            raise HarnessError("Closing reinforcement claims must be carried by the final module")
        proof_map = recall["proof_module_ids_by_claim"]
        if set(proof_map) != must_remember:
            raise HarnessError("Recall proof map must account for every must-remember claim exactly once")
        claim_usage = {claim_id: set() for claim_id in must_remember}
        for module in plan["modules"]:
            used_claims = {module["lead_claim_id"], *module.get("supporting_claim_ids", [])}
            for claim_id in must_remember & used_claims:
                claim_usage[claim_id].add(module["id"])
        for claim_id, proof_modules in proof_map.items():
            declared = set(proof_modules)
            if not declared or declared - known_module_ids:
                raise HarnessError(f"Recall proof modules for {claim_id} must be valid planned modules")
            if declared - claim_usage[claim_id]:
                raise HarnessError(f"Recall proof modules for {claim_id} must actually carry that verified claim")
            minimum_recurrence = 1 if len(plan["modules"]) == 1 else 2
            if len(claim_usage[claim_id]) < minimum_recurrence:
                raise HarnessError(f"Must-remember claim {claim_id} is not reinforced across the campaign")
    centered_count = sum(item["text_system"]["primary_mode"] == "centered_hero_headline" for item in plan["modules"])
    natural_centered_limit = max(1, (len(plan["modules"]) + 2) // 3)
    if typography_rhythm["centered_hero_max"] > natural_centered_limit:
        raise HarnessError("Typography rhythm centered_hero_max is too permissive to guarantee campaign-level variation")
    if centered_count > typography_rhythm["centered_hero_max"]:
        raise HarnessError("Centered hero headline count exceeds the approved campaign typography rhythm")
    primary_sequence = [item["text_system"]["primary_mode"] for item in plan["modules"]]
    anchor_sequence = [item["text_system"]["anchor_zone"] for item in plan["modules"]]
    if primary_sequence != typography_rhythm["primary_mode_sequence"]:
        raise HarnessError("Typography rhythm primary_mode_sequence must exactly match module order")
    if anchor_sequence != typography_rhythm["anchor_zone_sequence"]:
        raise HarnessError("Typography rhythm anchor_zone_sequence must exactly match module order")
    repeat_limit = typography_rhythm["consecutive_anchor_repeat_limit"]
    if not isinstance(repeat_limit, int) or repeat_limit < 1:
        raise HarnessError("Typography rhythm consecutive_anchor_repeat_limit must be a positive integer")
    run = 1
    for index in range(1, len(anchor_sequence)):
        run = run + 1 if anchor_sequence[index] == anchor_sequence[index - 1] else 1
        if run > repeat_limit:
            raise HarnessError("Typography anchor zone repeats for too many consecutive modules")
    for cluster in clusters:
        assigned = set(cluster["assigned_module_ids"])
        if not assigned or assigned - known_module_ids:
            raise HarnessError(f"Selling-point cluster {cluster['id']} must be assigned to valid modules")
        for module_id in assigned:
            if cluster["id"] not in module_by_id[module_id]["selling_point_cluster_ids"]:
                raise HarnessError(f"Selling-point cluster {cluster['id']} is not declared by assigned module {module_id}")
    must_separate = [item for item in clusters if item["separation_policy"] == "MUST_SEPARATE"]
    for cluster in must_separate:
        other_assignments = set().union(*(
            set(item["assigned_module_ids"])
            for item in must_separate if item["id"] != cluster["id"]
        )) if len(must_separate) > 1 else set()
        if not (set(cluster["assigned_module_ids"]) - other_assignments):
            raise HarnessError(f"Selling-point cluster {cluster['id']} is marked MUST_SEPARATE but has no dedicated module")

    reference_system = plan["reference_expression_system"]
    require_fields(reference_system, ("anti_copy_rule",), "reference expression system")
    for optional_empty_key in ("coverage", "adopted_patterns"):
        if optional_empty_key not in reference_system or not isinstance(reference_system[optional_empty_key], list):
            raise HarnessError(f"reference expression system missing required list field: {optional_empty_key}")
    if reference_system["anti_copy_rule"] != "ADAPT_VISUAL_GRAMMAR_ONLY_NEVER_COPY_BRAND_COPY_OR_ASSET":
        raise HarnessError("Reference use must adapt expression grammar without copying brand, copy or assets")
    supplied_reference_items = {
        item["id"]: item for item in session["input"].get("reference_materials", [])
    }
    supplied_reference_units = {
        unit["id"]: {**unit, "reference_id": item["id"]}
        for item in supplied_reference_items.values()
        for unit in item.get("analyzed_units", [])
    }
    supplied_refs = set(supplied_reference_items)
    coverage_refs = {item.get("reference_id") for item in reference_system["coverage"]}
    if coverage_refs != supplied_refs:
        raise HarnessError("Every supplied reference material must be explicitly adopted or rejected")
    patterns = {item.get("id"): item for item in reference_system["adopted_patterns"]}
    if supplied_refs and len(patterns) < 1:
        raise HarnessError("Analyzed reference materials were supplied, so at least one expression pattern must be adapted")
    for pattern_id, pattern in patterns.items():
        require_fields(pattern, ("id", "source_reference_ids", "source_unit_ids", "observed_method", "adaptation_for_product", "scheduled_module_ids", "do_not_copy"), "reference expression pattern")
        if set(pattern["source_reference_ids"]) - supplied_refs:
            raise HarnessError(f"Reference pattern {pattern_id} cites unknown materials")
        cited_units = set(pattern["source_unit_ids"])
        if cited_units - set(supplied_reference_units):
            raise HarnessError(f"Reference pattern {pattern_id} cites unknown analyzed screen units")
        if {supplied_reference_units[unit_id]["reference_id"] for unit_id in cited_units} - set(pattern["source_reference_ids"]):
            raise HarnessError(f"Reference pattern {pattern_id} source units do not belong to its source references")
        observed_methods = {
            supplied_reference_units[unit_id]["observed_expression_method"]
            for unit_id in cited_units
        }
        if pattern["observed_method"] not in observed_methods:
            raise HarnessError(
                f"Reference pattern {pattern_id} must use an expression method actually recorded in its analyzed source material"
            )
        if set(pattern["scheduled_module_ids"]) - known_module_ids:
            raise HarnessError(f"Reference pattern {pattern_id} is scheduled to unknown modules")
    for item in reference_system["coverage"]:
        require_fields(item, ("reference_id", "disposition", "pattern_ids", "reason"), "reference coverage item")
        cited_patterns = set(item["pattern_ids"])
        if cited_patterns - set(patterns):
            raise HarnessError(f"Reference {item['reference_id']} cites unknown expression patterns")
        if item["disposition"] == "ADOPTED_GRAMMAR" and not cited_patterns:
            raise HarnessError(f"Adopted reference {item['reference_id']} must feed at least one expression pattern")
        if item["disposition"] == "REJECTED_IRRELEVANT" and cited_patterns:
            raise HarnessError(f"Rejected reference {item['reference_id']} cannot feed an expression pattern")
    known_pattern_ids = set(patterns)
    for module in plan["modules"]:
        if supplied_refs and not module["reference_pattern_ids"]:
            raise HarnessError(f"Module {module['id']} must inherit at least one analyzed reference-expression pattern")
        if set(module["reference_pattern_ids"]) - known_pattern_ids:
            raise HarnessError(f"Module {module['id']} cites unknown reference-expression patterns")
        for pattern_id in module["reference_pattern_ids"]:
            if module["id"] not in patterns[pattern_id]["scheduled_module_ids"]:
                raise HarnessError(f"Reference pattern {pattern_id} is not scheduled for module {module['id']}")
    for item in coverage:
        require_fields(item, ("claim_id", "disposition", "rationale", "defer_reason_code"), "claim coverage item")
        if "module_ids" not in item or not isinstance(item["module_ids"], list):
            raise HarnessError("claim coverage item missing required fields: module_ids")
        if not str(item["rationale"]).strip():
            raise HarnessError(f"Claim {item['claim_id']} requires a disposition rationale")
        referenced = set(item["module_ids"])
        if referenced - known_module_ids:
            raise HarnessError(f"Claim {item['claim_id']} refers to unknown modules: {sorted(referenced - known_module_ids)}")
        if item["disposition"] == "DEFERRED":
            if referenced:
                raise HarnessError(f"Deferred claim {item['claim_id']} cannot be assigned to a module")
            if item["defer_reason_code"] not in (
                "CONFLICTING_FACT", "HIGH_RISK_UNDOCUMENTED", "UNSUPPORTED_INVENTION", "IMMATERIAL_DUPLICATE"
            ):
                raise HarnessError(f"Deferred claim {item['claim_id']} needs an allowed defer reason")
            continue
        if item["defer_reason_code"] != "NOT_DEFERRED":
            raise HarnessError(f"Selected claim {item['claim_id']} must use NOT_DEFERRED")
        if not referenced:
            raise HarnessError(f"Selected claim {item['claim_id']} must be assigned to at least one module")
        for module_id in referenced:
            module = module_by_id[module_id]
            used = {module["lead_claim_id"], *module.get("supporting_claim_ids", [])}
            if item["claim_id"] not in used:
                raise HarnessError(f"Coverage assigns {item['claim_id']} to {module_id}, but that module does not use the claim")
        if item["disposition"] == "LEAD" and not any(module_by_id[module_id]["lead_claim_id"] == item["claim_id"] for module_id in referenced):
            raise HarnessError(f"Lead claim {item['claim_id']} is not the lead claim of any assigned module")


def cmd_compile_plan(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "IDENTITY_LOCKED")
    if session.get("conflict_checkpoint", {}).get("required"):
        raise HarnessError("Full planning is blocked until the user resolves the batched conflict checkpoint")
    compile_started = time.perf_counter()
    raw_plan = load_json(args.plan)
    plan = normalize_plan(session, raw_plan)
    validate_plan(session, plan)
    session["plan"] = plan
    session["modules"] = [
        {
            "id": item["id"], "order": item["order"], "plan": item,
            "status": "PENDING", "attempts": [], "accepted_asset": None,
            "repair_plan": None, "user_adjustment": None, "residual_issues": [],
            "cycle_id": 1, "cycle_attempt_count": 0, "repair_budget": 1,
            "cycle_base_asset": None, "revision_history": [],
        }
        for item in plan["modules"]
    ]
    session["current_index"] = 0
    session["state"] = "AWAITING_PLAN_APPROVAL"
    approval_markdown = _approval_markdown(session)
    approval_path = Path(args.session).with_name("plan-approval.md")
    atomic_write_text(approval_path, approval_markdown)
    session["approval_document"] = {
        "path": str(approval_path.resolve()),
        "sha256": hashlib.sha256(approval_markdown.encode("utf-8")).hexdigest(),
        "format": "MANDATORY_VERBATIM_MARKDOWN",
    }
    raw_bytes = len(json.dumps(raw_plan, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    compiled_bytes = len(json.dumps(plan, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    session["planning_metrics"] = {
        "authoring_format": raw_plan.get("plan_format", "FULL_V1_0"),
        "authoring_plan_bytes": raw_bytes,
        "compiled_plan_bytes": compiled_bytes,
        "runtime_derived_bytes": max(0, compiled_bytes - raw_bytes),
        "planning_elapsed_seconds": _planning_elapsed_seconds(session),
        "compiler_elapsed_seconds": round(time.perf_counter() - compile_started, 3),
    }
    save(args.session, session, "plan_compiled")
    return summary(session)


def cmd_authorize(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AWAITING_PLAN_APPROVAL")
    if not args.approval_text.strip():
        raise HarnessError("Approval text must preserve the user's explicit words")
    approval_document = session.get("approval_document") or {}
    if args.approval_document_sha256 != approval_document.get("sha256"):
        raise HarnessError(
            "Authorization must cite the exact compiler-generated plan-approval.md fingerprint; "
            "do not authorize from a handwritten or abbreviated plan summary"
        )
    strategy = session["plan"]["output_strategy"]
    if args.approved_module_count != strategy["module_count"]:
        raise HarnessError("Approved module count does not match the compiled plan")
    if args.approved_aspect_ratio != strategy["aspect_ratio"]["label"]:
        raise HarnessError("Approved aspect ratio does not match the compiled plan")
    session["approval"] = {
        "text": args.approval_text,
        "module_count": args.approved_module_count,
        "aspect_ratio": args.approved_aspect_ratio,
        "at": now(),
    }
    session["state"] = "AUTHORIZED"
    save(args.session, session, "plan_authorized")
    return summary(session)


def cmd_generate_next(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    if session.get("version") not in COMPATIBLE_SESSION_VERSIONS:
        raise HarnessError(
            f"Session version {session.get('version')} is not compatible with harness {VERSION}; restart and recompile the approved storyboard matrix"
        )
    require_state(session, "AUTHORIZED")
    module = current_module(session)
    if module["status"] not in ("PENDING", "REPAIR_PREPARED", "USER_ADJUSTMENT"):
        raise HarnessError(f"Current module is not ready to generate: {module['status']}")
    if module.get("cycle_attempt_count", 0) >= 2:
        raise HarnessError("Generation budget exhausted: one initial attempt plus one repair is the hard limit for this revision cycle")
    is_repair = module["status"] == "REPAIR_PREPARED"
    token = str(uuid.uuid4())
    references, series_master = generation_references(session)
    edge_reference = continuity_edge_reference(session, args.session)
    edit_target = (
        next(
            item["image"] for item in module["attempts"]
            if item.get("cycle_id", 1) == module.get("cycle_id", 1)
        )
        if is_repair else module.get("cycle_base_asset")
    )
    output = module["plan"]["output"]
    format_canvas = None
    request_references = list(references)
    if not edit_target:
        format_canvas = ensure_format_canvas(
            Path(args.session).resolve().parent / "format-canvases" /
            f"{int(output['width_px'])}x{int(output['height_px'])}.png",
            int(output["width_px"]),
            int(output["height_px"]),
        )
        request_references.insert(0, format_canvas)
    if edge_reference:
        insert_at = 1 if format_canvas else 0
        request_references.insert(insert_at, edge_reference)
    prompt = compile_prompt(
        session,
        module,
        repair=is_repair,
        format_canvas_lock=bool(format_canvas),
    )
    ratio_divisor = math.gcd(int(output["width_px"]), int(output["height_px"]))
    request = {
        "token": token,
        "module_id": module["id"],
        "attempt": len(module["attempts"]) + 1,
        "cycle_id": module.get("cycle_id", 1),
        "cycle_attempt": module.get("cycle_attempt_count", 0) + 1,
        "mode": "repair" if is_repair else ("user_adjustment" if module["status"] == "USER_ADJUSTMENT" else "initial"),
        "prompt": prompt,
        "reference_images": request_references,
        "product_reference_images": references,
        "continuity_edge_reference": edge_reference,
        "format_canvas": format_canvas,
        "output_surface": {
            "width_px": int(output["width_px"]),
            "height_px": int(output["height_px"]),
            "aspect_ratio": (
                f"{int(output['width_px']) // ratio_divisor}:"
                f"{int(output['height_px']) // ratio_divisor}"
            ),
            "format_canvas_locked": bool(format_canvas),
        },
        "edit_target": edit_target,
        "context_contract": {
            "canonical_product": session["identity"]["canonical_name"],
            "module_id": module["id"],
            "module_duty": module["plan"]["duty"],
            "single_conclusion": module["plan"].get(
                "lead_conclusion", module["plan"].get("conclusion")
            ),
            "identity_fingerprint": fingerprint(session["identity"]),
            "approved_plan_fingerprint": fingerprint(session["plan"]),
            "prompt_fingerprint": fingerprint(prompt),
            "series_master": series_master,
            "reference_count": len(request_references),
            "product_reference_count": len(references),
            "continuity_edge_reference": edge_reference,
            "format_canvas_locked": bool(format_canvas),
            "compiled_prompt_locked": True,
        },
    }
    atomic_write_json(args.out, request)
    session["active_token"] = token
    session["state"] = "AWAITING_GENERATED_MODULE"
    module["status"] = "AWAITING_GENERATION"
    save(args.session, session, f"generation_requested:{module['id']}")
    return {"request": str(Path(args.out).resolve()), **request}


def cmd_record_generation(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AWAITING_GENERATED_MODULE")
    if args.token != session.get("active_token"):
        raise HarnessError("Stale or incorrect generation token")
    image = Path(args.image)
    if not image.is_file():
        raise HarnessError(f"Generated image does not exist: {image}")
    module = current_module(session)
    output = module["plan"]["output"]
    normalized = normalize_generated_image(
        image,
        int(output["width_px"]),
        int(output["height_px"]),
    )
    module["cycle_attempt_count"] = module.get("cycle_attempt_count", 0) + 1
    module["attempts"].append({
        "number": len(module["attempts"]) + 1,
        "cycle_id": module.get("cycle_id", 1),
        "cycle_attempt": module["cycle_attempt_count"],
        "image": normalized["path"], "token": args.token,
        "source_image": normalized["source_path"],
        "source_width_px": normalized["source_width_px"],
        "source_height_px": normalized["source_height_px"],
        "width_px": normalized["width_px"],
        "height_px": normalized["height_px"],
        "format_normalization": normalized["mode"],
        "relative_ratio_error": normalized["relative_ratio_error"],
        "bounded_crop_fraction": normalized.get("bounded_crop_fraction", 0.0),
        "recorded_at": now(), "judgment": None,
    })
    module["status"] = "AWAITING_AUDIT"
    session["active_token"] = None
    session["state"] = "AWAITING_PIXEL_AUDIT"
    save(args.session, session, f"generation_recorded:{module['id']}")
    return summary(session)


def advance_after_acceptance(session: dict) -> None:
    if all(module["status"] in COMPLETE_STATUSES for module in session["modules"]):
        session["state"] = "AWAITING_ASSEMBLY"
        return
    next_index = next(i for i, module in enumerate(session["modules"]) if module["status"] not in COMPLETE_STATUSES)
    session["current_index"] = next_index
    session["state"] = "AUTHORIZED"


def cmd_audit_current(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AWAITING_PIXEL_AUDIT")
    module = current_module(session)
    attempt = module["attempts"][-1]
    expected = module["plan"]["output"]
    actual_width, actual_height = image_dimensions(attempt["image"])
    if (actual_width, actual_height) != (expected["width_px"], expected["height_px"]):
        raise HarnessError(
            "Recorded module dimensions changed after generation binding: "
            f"expected {expected['width_px']}x{expected['height_px']}, "
            f"found {actual_width}x{actual_height}"
        )
    judgment = load_json(args.judgment)
    validate_module_judgment(judgment, module)
    attempt["judgment"] = judgment
    if judgment["status"] == "PASS":
        module["accepted_asset"] = attempt["image"]
        module["status"] = "COMPLETE"
        module["residual_issues"] = judgment.get("residual_issues", [])
        advance_after_acceptance(session)
    elif module.get("cycle_attempt_count", 0) == 1:
        module["status"] = "REPAIR_REQUIRED"
        session["state"] = "REPAIR_REQUIRED"
    else:
        module["accepted_asset"] = attempt["image"]
        module["status"] = "COMPLETE_WITH_RESIDUALS"
        module["residual_issues"] = [item.get("visible_evidence", str(item)) for item in judgment["material_failures"]]
        advance_after_acceptance(session)
    save(args.session, session, f"pixel_audited:{module['id']}:{judgment['status']}")
    return summary(session)


def cmd_prepare_repair(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "REPAIR_REQUIRED")
    repair = load_json(args.repair_plan)
    require_fields(repair, ("module_id", "material_failures", "passed_layers", "root_cause", "unified_strategy", "expected_visible_change"), "repair plan")
    module = current_module(session)
    if module.get("cycle_attempt_count", 0) != 1:
        raise HarnessError("Automatic repair can be prepared only after the first failed attempt in the current cycle")
    if repair["module_id"] != module["id"]:
        raise HarnessError("Repair plan does not target current module")
    module["repair_plan"] = repair
    module["status"] = "REPAIR_PREPARED"
    session["state"] = "AUTHORIZED"
    save(args.session, session, f"repair_prepared:{module['id']}")
    return summary(session)


def cmd_apply_user_adjustment(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AUTHORIZED", "REPAIR_EXHAUSTED", "AWAITING_ASSEMBLY", "AWAITING_USER_FINAL_REVIEW", "FINALIZED")
    adjustment = load_json(args.adjustment)
    require_fields(adjustment, ("module_id", "verbatim_instruction", "change_scope", "change_kind", "change_only", "preserve", "must_not_regress"), "user adjustment")
    global_flags = ("changes_identity", "changes_facts", "changes_target_buyer", "changes_campaign_style", "changes_module_sequence")
    if adjustment.get("change_scope") != "local" or any(adjustment.get(flag) for flag in global_flags):
        raise HarnessError("This is a global change; replan or restart instead of reopening one module")
    try:
        index = next(i for i, module in enumerate(session["modules"]) if module["id"] == adjustment["module_id"])
    except StopIteration as exc:
        raise HarnessError("Unknown module in user adjustment") from exc
    module = session["modules"][index]
    base_asset = module.get("accepted_asset") or (module.get("attempts") or [{}])[-1].get("image")
    if not base_asset:
        raise HarnessError("A local adjustment requires an existing generated module")
    module["prior_accepted_asset"] = module.get("accepted_asset")
    module["accepted_asset"] = None
    module.setdefault("revision_history", []).append({
        "cycle_id": module.get("cycle_id", 1),
        "instruction": adjustment["verbatim_instruction"],
        "attempt_count": module.get("cycle_attempt_count", 0),
        "closed_at": now(),
    })
    module["cycle_id"] = module.get("cycle_id", 1) + 1
    module["cycle_attempt_count"] = 0
    module["cycle_base_asset"] = base_asset
    module["repair_plan"] = None
    module["user_adjustment"] = adjustment
    module["status"] = "USER_ADJUSTMENT"
    ledger = session.setdefault("feedback_constraints", {"global": {"preserve": [], "must_not_regress": []}, "by_module": {}})
    module_ledger = ledger.setdefault("by_module", {}).setdefault(module["id"], {"preserve": [], "must_not_regress": []})
    for key in ("preserve", "must_not_regress"):
        module_ledger[key] = _unique_strings(module_ledger.get(key, []) + adjustment[key])
    session["current_index"] = index
    session["assembly"] = None
    session["long_page_audit"] = None
    session["final"] = None
    session["state"] = "AUTHORIZED"
    save(args.session, session, f"user_adjustment_applied:{module['id']}")
    return summary(session)


def cmd_assemble(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AWAITING_ASSEMBLY")
    paths = [module["accepted_asset"] for module in session["modules"]]
    if not all(paths):
        raise HarnessError("All modules must have accepted assets")
    session["assembly"] = assemble_vertical(paths, args.output, session["input"]["platform_profile"])
    session["state"] = "AWAITING_LONG_PAGE_AUDIT"
    save(args.session, session, "long_page_assembled")
    return session["assembly"]


def cmd_audit_long_page(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AWAITING_LONG_PAGE_AUDIT")
    judgment = load_json(args.judgment)
    validate_long_page_judgment(judgment, session.get("plan"))
    session["long_page_audit"] = judgment
    session["state"] = "AWAITING_USER_FINAL_REVIEW"
    save(args.session, session, f"long_page_audited:{judgment['status']}")
    return summary(session)


def cmd_finalize(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AWAITING_USER_FINAL_REVIEW")
    if not args.approval_text.strip():
        raise HarnessError("Final approval text is required")
    residuals = [{"module_id": module["id"], "issues": module["residual_issues"]} for module in session["modules"] if module["residual_issues"]]
    manifest = {
        "skill": "aurora-domestic-ecommerce-detail-page",
        "version": VERSION,
        "product_name": session["input"]["product_name"],
        "platform_profile": session["input"]["platform_profile"],
        "approval": {"text": args.approval_text, "at": now()},
        "long_page": session["assembly"]["long_page"],
        "modules": [{"id": module["id"], "order": module["order"], "asset": module["accepted_asset"]} for module in session["modules"]],
        "slices": session["assembly"]["slices"],
        "residual_issues": residuals,
        "backend_confirmation_required": session["input"]["platform_profile"]["verification_status"] != "VERIFIED_CURRENT_BACKEND",
    }
    atomic_write_json(args.output, manifest)
    session["final"] = {"manifest": str(Path(args.output).resolve()), "approval": manifest["approval"]}
    session["state"] = "FINALIZED"
    save(args.session, session, "finalized")
    return manifest


STRUCTURE_FAMILY_LABELS = {
    "FULL_BLEED_HERO": "全幅英雄主视觉",
    "SPLIT_PANEL": "不等宽左右分区",
    "STACKED_BANDS": "上下分层结构",
    "NESTED_INFO_BOARD": "主视觉嵌套信息板",
    "PROCESS_STRIP_PLUS_RESULT": "步骤条＋结果主场景",
    "CENTRAL_OBJECT_ORBIT": "中心商品＋环绕证据",
    "FRAMED_LIFESTYLE_PLUS_CARDS": "大场景＋辅助情境面板",
    "PRODUCT_PAIR_PLUS_TABLE": "产品并置＋规格区",
    "MACRO_DIAGRAM": "局部微距＋关系示意",
    "PORTRAIT_STRIP_PLUS_PAIN_ARRAY": "人群条带＋痛点阵列",
    "ASYMMETRIC_EDITORIAL": "不对称编辑式分区",
    "COMPARISON_SPLIT": "同条件对比双区",
    "SELECTION_MATRIX": "需求到选项矩阵",
    "SPECIFICATION_BOARD": "商品绑定规格板",
}


def _as_compact_text(value, limit: int = 4) -> str:
    if value in (None, "", []):
        return "—"
    if isinstance(value, dict):
        values = [_as_compact_text(item, limit=limit) for item in value.values()]
    elif isinstance(value, (list, tuple, set)):
        values = [_as_compact_text(item, limit=limit) for item in value]
    else:
        return str(value).replace("\n", " ").strip()
    values = [item for item in values if item and item != "—"]
    if len(values) > limit:
        return "；".join(values[:limit]) + f"；等{len(values)}项"
    return "；".join(values) or "—"


def _md_cell(value) -> str:
    return _as_compact_text(value).replace("|", "／")


def _spatial_structure_summary(module: dict) -> str:
    contract = resolve_spatial_contract(module)
    zone_text = "；".join(
        str(zone.get("content") or zone.get("role") or "").strip()
        for zone in contract["zones"]
        if str(zone.get("content") or zone.get("role") or "").strip()
    )
    family = STRUCTURE_FAMILY_LABELS.get(contract["structure_family"], contract["structure_family"])
    return f"{family}：{zone_text}"


def _approval_packet(plan: dict) -> dict:
    strategy = plan["output_strategy"]
    modules = []
    for module in plan["modules"]:
        text_system = module.get("text_system", {})
        expression = module.get("module_visual_expression_contract", {})
        visual_proof = module["visual_proof_direction"]
        presence = expression.get("product_presence_policy")
        subject = expression.get("evidence_subject_policy")
        mode = expression.get("visualization_mode")
        stages = expression.get("transformation_stages") or []
        proof_details = [visual_proof]
        if presence in ("OPTIONAL", "ABSENT_ALLOWED"):
            proof_details.append("商品可缺席")
        if subject in ("CLAIM_OBJECT_DOMINANT", "ACTION_RESULT_DOMINANT"):
            proof_details.append("功效对象/变化为主视觉")
        if mode == "CONCEPTUAL_NON_DIAGNOSTIC":
            proof_details.append("概念性非实验可视化")
        if stages:
            proof_details.append("变化：" + "→".join(str(item) for item in stages))
        presence_decision = module.get("product_presence_decision") or {}
        presence_labels = {
            "REQUIRED_DOMINANT": "完整商品主导",
            "REQUIRED_SUPPORTING": "完整商品辅助",
            "IDENTITY_TOKEN_ONLY": "仅商品身份线索",
            "OPTIONAL": "商品可选",
            "ABSENT_ALLOWED": "允许商品缺席",
            "ABSENT_PREFERRED": "优先商品缺席",
        }
        presence_summary = presence_labels.get(presence, presence or "—")
        if presence in ("IDENTITY_TOKEN_ONLY", "ABSENT_ALLOWED", "ABSENT_PREFERRED"):
            presence_summary += "；主角：" + str(presence_decision.get("primary_subject_without_product") or "卖点证据")
        modules.append({
            "module": module["id"],
            "page_duty": module["duty"],
            "main_conclusion": module["lead_conclusion"],
            "visual_proof": "；".join(proof_details),
            "商品出镜策略": presence_summary,
            "空间结构": _spatial_structure_summary(module),
            "copy_method": " / ".join(filter(None, [
                str(text_system.get("primary_mode", "")).strip(),
                str(text_system.get("anchor_zone", "")).strip(),
            ])),
            "sequence_relation": _as_compact_text(
                "方法=" + str((module.get("transition_contract") or {}).get("method_id", "")) + "；接缝=" + str((module.get("transition_contract") or {}).get("visual_handoff_type", "")) + "；来源→目标=" + str((module.get("transition_contract") or {}).get("source_region_previous", "")) + "→" + str((module.get("transition_contract") or {}).get("target_region_current", "")) + "；几何=" + str((module.get("transition_contract") or {}).get("handoff_geometry", ""))
                if module.get("transition_contract") else
                (module.get("transition_contract") or {}).get("outgoing_carrier")
                or module["variation_from_previous"]
            ),
        })
    return {
        "required_storyboard_columns": [
            "模块", "页面职责", "主结论", "画面如何证明", "商品出镜策略", "空间结构", "文字如何进入画面", "与前后屏关系"
        ],
        "decision": {
            "target_platform": strategy["target_platform"],
            "module_count": strategy["module_count"],
            "aspect_ratio": strategy["aspect_ratio"]["label"],
            "design_dimensions_px": f"{strategy['canvas_width_px']}x{strategy['module_height_px']}",
            "safe_margin_px": strategy["safe_margin_px"],
            "slice_height_px": strategy["slice_height_px"],
            "verification_status": strategy["verification_status"],
        },
        "module_count_candidates": strategy["module_count_candidates"],
        "ratio_candidates": strategy["ratio_candidates"],
        "storyboard": modules,
    }


def _approval_markdown(session: dict) -> str:
    plan = session["plan"]
    input_data = session["input"]
    strategy = plan["output_strategy"]
    packet = _approval_packet(plan)
    analysis = input_data.get("operating_analysis", {})
    facts_by_id = {item["id"]: item for item in input_data.get("verified_facts", [])}
    confirmed_ids = analysis.get("confirmed_fact_ids") or session.get("planning_fact_ids", [])
    confirmed_facts = [facts_by_id[item]["text"] for item in confirmed_ids if item in facts_by_id]
    supplied_points = [item.get("text", "") for item in input_data.get("user_supplied_selling_points", [])]
    buyer_pain = [
        f"{item.get('buyer', '')}：{item.get('scenario', '')}"
        for item in analysis.get("buyer_hypotheses", [])
    ] + [item.get("pain", "") for item in analysis.get("pain_hypotheses", [])]
    selected_positioning_id = analysis.get("selected_positioning_id")
    selected_positioning = next((
        item.get("thesis", "") for item in analysis.get("positioning_candidates", [])
        if item.get("id") == selected_positioning_id
    ), plan.get("campaign_thesis", ""))

    lines = [
        f"方案已通过 Skill v{VERSION} 编译，当前停在生图前审批节点。",
        "",
        "| 采用路由 | 确认的产品事实 | 用户指定卖点 | 推演人群与痛点 | 推荐定位 | 待验证假设 |",
        "|---|---|---|---|---|---|",
        "| " + " | ".join([
            _md_cell(input_data.get("intake_route", "—")),
            _md_cell(confirmed_facts),
            _md_cell(supplied_points),
            _md_cell(buyer_pain),
            _md_cell(selected_positioning),
            _md_cell(analysis.get("evidence_gaps", [])),
        ]) + " |",
        "",
        "| 屏数方案 | 屏数 | 一级卖点深度 | 证据边界 | 结论 |",
        "|---|---:|---|---|---|",
    ]
    mode_labels = {
        "COMPACT_COVERAGE": "紧凑覆盖",
        "BALANCED_EXPRESSION": "平衡表达",
        "FULL_SALES": "完整销售",
    }
    for candidate in strategy["module_count_candidates"]:
        lines.append("| " + " | ".join([
            mode_labels.get(candidate.get("candidate_mode"), candidate.get("candidate_mode", "—")),
            str(candidate["count"]),
            _md_cell(candidate.get("primary_selling_point_depth_fit") or candidate.get("selling_point_fit")),
            _md_cell(candidate.get("evidence_boundary_fit") or candidate.get("coverage_tradeoff")),
            "选定" if candidate["decision"] == "SELECTED" else "不选",
        ]) + " |")

    lines.extend([
        "",
        "| 比例方案 | 单屏比例 | 构图适配 | 移动阅读取舍 | 结论 |",
        "|---|---:|---|---|---|",
    ])
    for candidate in strategy["ratio_candidates"]:
        lines.append("| " + " | ".join([
            "内部评审母版" if candidate["label"] == "3:4" else "纵向备选",
            candidate["label"],
            _md_cell(candidate["composition_fit"]),
            _md_cell(candidate["mobile_reading_tradeoff"]),
            "选定" if candidate["decision"] == "SELECTED" else "不选",
        ]) + " |")

    lines.extend([
        "",
        "| 目标平台 | 总屏数 | 单屏比例 | 设计尺寸 | 安全边距 | 最终切片 | 平台核验状态 | 屏数依据 | 比例依据 |",
        "|---|---:|---:|---:|---:|---:|---|---|---|",
        "| " + " | ".join([
            _md_cell(strategy["target_platform"]), str(strategy["module_count"]),
            strategy["aspect_ratio"]["label"],
            f"{strategy['canvas_width_px']}×{strategy['module_height_px']} px",
            f"{strategy['safe_margin_px']} px", f"{strategy['slice_height_px']} px",
            _md_cell(strategy["verification_status"]), _md_cell(strategy["module_count_rationale"]),
            _md_cell(strategy["ratio_rationale"]),
        ]) + " |",
        "",
        "| 模块 | 页面职责 | 主结论 | 画面如何证明 | 商品出镜策略 | 空间结构 | 文字如何进入画面 | 与前后屏关系 |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for item in packet["storyboard"]:
        lines.append("| " + " | ".join([
            _md_cell(item["module"]), _md_cell(item["page_duty"]), _md_cell(item["main_conclusion"]),
            _md_cell(item["visual_proof"]), _md_cell(item["商品出镜策略"]), _md_cell(item["空间结构"]),
            _md_cell(item["copy_method"]), _md_cell(item["sequence_relation"]),
        ]) + " |")

    if plan.get("plan_format") == "COMPACT_V1_2":
        lines.extend([
            "",
            "| 一级卖点 | 优先级 | 证据等级 | 总览 | 独立表达 | 使用/结果 | 收尾回忆 | 最终状态 |",
            "|---|---|---|---|---|---|---|---|",
        ])
        outcome_jobs = {"MECHANISM_OR_REASON", "USE_SCOPE", "ACTION_OR_OPERATION", "RESULT_OR_EXPERIENCE", "SELECTION", "TRUST"}
        for depth in plan["selling_point_depth_contract"]["claim_depth"]:
            fact = facts_by_id.get(depth["claim_id"], {})
            job_map = depth.get("module_jobs", [])
            def modules_for(jobs):
                return [entry["module_id"] for entry in job_map if entry.get("job") in jobs]
            overview = modules_for({"VALUE_OVERVIEW", "PROBLEM_CONTEXT"})
            dedicated = modules_for({"DEDICATED_EXPRESSION"})
            outcome = modules_for(outcome_jobs)
            recall_ids = modules_for({"RECALL"})
            complete = bool(overview and dedicated and outcome and recall_ids)
            lines.append("| " + " | ".join([
                _md_cell(fact.get("text", depth["claim_id"])),
                _md_cell(depth.get("priority", "PRIMARY")),
                _md_cell(depth.get("evidence_ceiling")),
                _md_cell(overview), _md_cell(dedicated), _md_cell(outcome), _md_cell(recall_ids),
                "完整" if complete else "规划缺口",
            ]) + " |")

        formula_contract = plan.get("formula_split_contract", {})
        if formula_contract.get("enabled"):
            lines.extend([
                "",
                "| 配方/成分/结构卖点 | 对应痛点或问题 | 对应用户利益 | 独立模块 | 视觉表达路线 | 证据边界 |",
                "|---|---|---|---|---|---|",
            ])
            for entry in formula_contract.get("entries", []):
                lines.append("| " + " | ".join([
                    _md_cell(entry.get("formula_or_element", entry.get("claim_id", ""))),
                    _md_cell(entry.get("buyer_problem_or_question", "")),
                    _md_cell(entry.get("supported_benefit", "")),
                    _md_cell(entry.get("dedicated_module_id", "")),
                    _md_cell(entry.get("visual_expression_route", "")),
                    _md_cell(entry.get("evidence_ceiling", "")),
                ]) + " |")

        if input_data.get("user_supplied_selling_points"):
            supplied_by_id = {item["id"]: item for item in input_data["user_supplied_selling_points"]}
            lines.extend([
                "",
                "| 用户原始卖点 | 处理状态 | 原子事实 | 计划屏幕 | 处理说明 |",
                "|---|---|---|---|---|",
            ])
            for entry in plan.get("user_selling_point_coverage_ledger", []):
                lines.append("| " + " | ".join([
                    _md_cell(supplied_by_id.get(entry["selling_point_id"], {}).get("text", entry["selling_point_id"])),
                    _md_cell(entry["status"]), _md_cell(entry["atomic_claim_ids"]),
                    _md_cell(entry["planned_module_ids"]), _md_cell(entry["reason"]),
                ]) + " |")

    dna = plan["series_visual_dna"]
    lines.extend([
        "",
        "视觉 DNA：" + "；".join([
            "品牌锚点 " + _as_compact_text(dna.get("brand_anchor_system")),
            "色彩 " + _as_compact_text(dna.get("palette_tokens")),
            "字体 " + _as_compact_text(dna.get("typography_tokens")),
            "图形 " + _as_compact_text(dna.get("graphic_tokens")),
            "摄影 " + _as_compact_text(dna.get("photography_tokens")),
            "商品质感 " + _as_compact_text(dna.get("product_tokens")),
        ]) + "。",
        "",
        "合并处理：" + _as_compact_text(strategy.get("merge_decisions", [])),
    ])
    defer_labels = {
        "CONFLICTING_FACT": "事实冲突",
        "HIGH_RISK_UNDOCUMENTED": "高风险且缺少独立证据",
        "UNSUPPORTED_INVENTION": "当前证据不支持",
        "IMMATERIAL_DUPLICATE": "与已保留事实重复",
    }
    deferred = []
    for item in strategy["claim_coverage"]:
        if item.get("disposition") == "DEFERRED":
            fact = facts_by_id.get(item.get("claim_id"), {})
            deferred.append(
                f"{fact.get('text', item.get('claim_id'))}（{defer_labels.get(item.get('defer_reason_code'), item.get('defer_reason_code'))}）"
            )
    lines.extend([
        "延后表达：" + (_as_compact_text(deferred, limit=20) if deferred else "无。"),
        "",
        f"如同意，请回复：**批准 {strategy['module_count']} 屏 {strategy['aspect_ratio']['label']} 方案，按此生成**。",
    ])
    return "\n".join(lines)


def summary(session: dict) -> dict:
    modules = session.get("modules", [])
    state = session.get("state")
    current = None
    if modules and 0 <= session.get("current_index", 0) < len(modules):
        current = modules[session["current_index"]]["id"]
    result = {
        "state": state,
        "allowed_actions": allowed_actions(state),
        "current_module": current,
        "completed_modules": sum(module.get("status") in COMPLETE_STATUSES for module in modules),
        "total_modules": len(modules),
        "assembly": session.get("assembly"),
        "stage_timings": _seconds_between_events(session),
    }
    if session.get("planning_metrics"):
        result["planning_metrics"] = session["planning_metrics"]
    if current:
        module = modules[session["current_index"]]
        result["current_module_runtime"] = {
            "status": module.get("status"),
            "cycle_id": module.get("cycle_id", 1),
            "cycle_attempt_count": module.get("cycle_attempt_count", 0),
            "automatic_repair_remaining": max(
                0,
                module.get("repair_budget", 1) - max(0, module.get("cycle_attempt_count", 0) - 1),
            ),
            "lifetime_attempt_count": len(module.get("attempts", [])),
            "residual_issues": module.get("residual_issues", []),
        }
    if session.get("conflict_checkpoint"):
        result["conflict_checkpoint"] = session["conflict_checkpoint"]
        result["planning_fact_ids"] = session.get("planning_fact_ids", [])
    if session.get("plan"):
        strategy = session["plan"]["output_strategy"]
        result["approved_output_strategy"] = {
            "target_platform": strategy["target_platform"],
            "module_count": strategy["module_count"],
            "aspect_ratio": strategy["aspect_ratio"]["label"],
            "dimensions_px": f"{strategy['canvas_width_px']}x{strategy['module_height_px']}",
            "verification_status": strategy["verification_status"],
        }
        if state == "AWAITING_PLAN_APPROVAL":
            result["approval_packet"] = _approval_packet(session["plan"])
            result["approval_document"] = session.get("approval_document")
            result["approval_markdown"] = _approval_markdown(session)
            result["approval_output_instruction"] = (
                "Show approval_markdown verbatim as the complete user-facing response; "
                "do not abbreviate, paraphrase, replace it with a page-order list, or add a second plan."
            )
    return result


def cmd_inspect(args: argparse.Namespace) -> dict:
    return summary(load_json(args.session))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Aurora domestic e-commerce detail-page state harness")
    sub = root.add_subparsers(dest="command", required=True)
    commands = {}
    for name in ("start", "resolve-conflicts", "lock-identity", "compile-plan", "authorize", "generate-next", "record-generation", "audit-current", "prepare-repair", "apply-user-adjustment", "assemble", "audit-long-page", "finalize", "inspect"):
        commands[name] = sub.add_parser(name)
    commands["start"].add_argument("--input", required=True); commands["start"].add_argument("--session", required=True)
    for name in commands:
        if name != "start": commands[name].add_argument("--session", required=True)
    commands["lock-identity"].add_argument("--identity", required=True)
    commands["resolve-conflicts"].add_argument("--resolution", required=True)
    commands["compile-plan"].add_argument("--plan", required=True)
    commands["authorize"].add_argument("--approval-text", required=True)
    commands["authorize"].add_argument("--approved-module-count", required=True, type=int)
    commands["authorize"].add_argument("--approved-aspect-ratio", required=True)
    commands["authorize"].add_argument("--approval-document-sha256", required=True)
    commands["generate-next"].add_argument("--out", required=True)
    commands["record-generation"].add_argument("--token", required=True); commands["record-generation"].add_argument("--image", required=True)
    commands["audit-current"].add_argument("--judgment", required=True)
    commands["prepare-repair"].add_argument("--repair-plan", required=True)
    commands["apply-user-adjustment"].add_argument("--adjustment", required=True)
    commands["assemble"].add_argument("--output", required=True)
    commands["audit-long-page"].add_argument("--judgment", required=True)
    commands["finalize"].add_argument("--output", required=True); commands["finalize"].add_argument("--approval-text", required=True)
    return root


HANDLERS = {
    "start": cmd_start, "resolve-conflicts": cmd_resolve_conflicts,
    "lock-identity": cmd_lock_identity, "compile-plan": cmd_compile_plan,
    "authorize": cmd_authorize, "generate-next": cmd_generate_next, "record-generation": cmd_record_generation,
    "audit-current": cmd_audit_current, "prepare-repair": cmd_prepare_repair,
    "apply-user-adjustment": cmd_apply_user_adjustment, "assemble": cmd_assemble,
    "audit-long-page": cmd_audit_long_page, "finalize": cmd_finalize, "inspect": cmd_inspect,
}


def main() -> int:
    try:
        args = parser().parse_args()
        print(json.dumps(HANDLERS[args.command](args), ensure_ascii=False, indent=2))
        return 0
    except (HarnessError, KeyError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
