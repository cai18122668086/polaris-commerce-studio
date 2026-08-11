from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from runtime.assembly import assemble_vertical
from runtime.prompt_compiler import compile_prompt
from runtime.state import (
    HarnessError,
    allowed_actions,
    atomic_write_json,
    current_module,
    load_json,
    require_fields,
    require_state,
)
from runtime.visual_gate import validate_long_page_judgment, validate_module_judgment


VERSION = "0.7.0"


def _unique_strings(values) -> list[str]:
    result = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generation_references(session: dict) -> Tuple[List[str], Optional[str]]:
    """Return a stable imagegen-sized reference set: series master + product evidence."""
    master = None
    modules = session.get("modules", [])
    if session.get("current_index", 0) > 0 and modules:
        master = modules[0].get("accepted_asset")

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


def save(session_path: str, session: dict, event: str) -> None:
    session.setdefault("events", []).append({"at": now(), "event": event, "state": session["state"]})
    session["updated_at"] = now()
    atomic_write_json(session_path, session)


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
    session["identity"] = identity
    session["state"] = "IDENTITY_LOCKED"
    save(args.session, session, "identity_locked")
    return summary(session)


def validate_plan(session: dict, plan: dict) -> None:
    if any(item.get("status") == "UNRESOLVED" for item in session["input"].get("source_conflicts", [])):
        raise HarnessError("Full planning is forbidden while product-source conflicts remain unresolved")
    require_fields(plan, ("campaign_thesis", "dominant_decision_type", "output_strategy", "reference_expression_system", "style_constitution", "series_visual_dna", "typography_rhythm", "modules"), "plan")
    strategy = plan["output_strategy"]
    require_fields(
        strategy,
        (
            "target_platform", "profile_name", "selection_mode", "module_count",
            "module_count_rationale", "module_count_candidates", "selling_point_clusters", "merge_decisions", "claim_coverage",
            "aspect_ratio", "canvas_width_px", "module_height_px", "safe_margin_px",
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
        raise HarnessError("Module count must be selected after comparing at least two selling-point coverage options")
    for candidate in strategy["module_count_candidates"]:
        require_fields(candidate, ("count", "coverage_tradeoff", "selling_point_fit", "decision"), "module-count candidate")
    candidate_counts = [item.get("count") for item in strategy["module_count_candidates"]]
    if len(candidate_counts) != len(set(candidate_counts)):
        raise HarnessError("Module-count candidates must compare distinct counts")
    if strategy["module_count"] not in candidate_counts:
        raise HarnessError("Selected module_count must match one evaluated selling-point candidate")
    selected_candidates = [item for item in strategy["module_count_candidates"] if item["decision"] == "SELECTED"]
    if len(selected_candidates) != 1 or selected_candidates[0]["count"] != strategy["module_count"]:
        raise HarnessError("Exactly one module-count candidate must be selected and match module_count")
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
            ("id", "order", "duty", "buyer_question", "lead_conclusion", "lead_claim_id", "selling_point_cluster_ids", "visual_proof_direction", "visual_evidence", "visual_proof_contract", "copy_intent", "composition_family", "camera_scale", "text_system", "reading_path", "copy_density", "visual_payload_density", "proof_relation_strength", "commercial_energy", "breathing_screen", "brand_anchor", "independent_logo_policy", "inherited_dna_tokens", "variation_from_previous", "output"),
            "plan module",
        )
        for optional_empty_key in ("reference_pattern_ids", "visible_copy"):
            if optional_empty_key not in module or not isinstance(module[optional_empty_key], list):
                raise HarnessError(f"plan module missing required list field: {optional_empty_key}")
        require_fields(module["visual_evidence"], ("evidence_class", "proof_device", "visible_content", "forbidden_inventions"), f"visual evidence for {module['id']}")
        contract = module["visual_proof_contract"]
        require_fields(contract, ("buyer_takeaway", "visual_verb", "primary_subject", "supporting_subjects", "required_relations", "minimum_visual_payload", "visual_specificity_anchor", "allowed_metaphor", "hidden_copy_test"), f"visual proof contract for {module['id']}")
        if contract["minimum_visual_payload"] < 3 and not module["breathing_screen"]:
            raise HarnessError(f"Module {module['id']} must require at least three effective visual payloads unless it is an explicit breathing screen")
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
        output = module["output"]
        if output["width_px"] != strategy["canvas_width_px"] or output["height_px"] != strategy["module_height_px"] or output["safe_margin_px"] != strategy["safe_margin_px"]:
            raise HarnessError(f"Module {module['id']} dimensions do not match the approved output strategy")
        previous_module = module
    if len(module_ids) != len(set(module_ids)):
        raise HarnessError("Module IDs must be unique")
    known_module_ids = set(module_ids)
    module_by_id = {item["id"]: item for item in plan["modules"]}
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
    plan = load_json(args.plan)
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
    save(args.session, session, "plan_compiled")
    return summary(session)


def cmd_authorize(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AWAITING_PLAN_APPROVAL")
    if not args.approval_text.strip():
        raise HarnessError("Approval text must preserve the user's explicit words")
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
    if session.get("version") != VERSION:
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
    prompt = compile_prompt(session, module, repair=is_repair)
    request = {
        "token": token,
        "module_id": module["id"],
        "attempt": len(module["attempts"]) + 1,
        "cycle_id": module.get("cycle_id", 1),
        "cycle_attempt": module.get("cycle_attempt_count", 0) + 1,
        "mode": "repair" if is_repair else ("user_adjustment" if module["status"] == "USER_ADJUSTMENT" else "initial"),
        "prompt": prompt,
        "reference_images": references,
        "edit_target": (
            next(
                item["image"] for item in module["attempts"]
                if item.get("cycle_id", 1) == module.get("cycle_id", 1)
            )
            if is_repair else module.get("cycle_base_asset")
        ),
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
            "reference_count": len(references),
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
    module["cycle_attempt_count"] = module.get("cycle_attempt_count", 0) + 1
    module["attempts"].append({
        "number": len(module["attempts"]) + 1,
        "cycle_id": module.get("cycle_id", 1),
        "cycle_attempt": module["cycle_attempt_count"],
        "image": str(image.resolve()), "token": args.token,
        "recorded_at": now(), "judgment": None,
    })
    module["status"] = "AWAITING_AUDIT"
    session["active_token"] = None
    session["state"] = "AWAITING_PIXEL_AUDIT"
    save(args.session, session, f"generation_recorded:{module['id']}")
    return summary(session)


def advance_after_acceptance(session: dict) -> None:
    if all(module["status"] == "COMPLETE" for module in session["modules"]):
        session["state"] = "AWAITING_ASSEMBLY"
        return
    next_index = next(i for i, module in enumerate(session["modules"]) if module["status"] != "COMPLETE")
    session["current_index"] = next_index
    session["state"] = "AUTHORIZED"


def cmd_audit_current(args: argparse.Namespace) -> dict:
    session = load_json(args.session)
    require_state(session, "AWAITING_PIXEL_AUDIT")
    module = current_module(session)
    judgment = load_json(args.judgment)
    validate_module_judgment(judgment, module)
    attempt = module["attempts"][-1]
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
        module["accepted_asset"] = None
        module["status"] = "REPAIR_EXHAUSTED"
        module["residual_issues"] = [item.get("visible_evidence", str(item)) for item in judgment["material_failures"]]
        session["state"] = "REPAIR_EXHAUSTED"
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
    validate_long_page_judgment(judgment)
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
        "completed_modules": sum(module.get("status") == "COMPLETE" for module in modules),
        "total_modules": len(modules),
        "assembly": session.get("assembly"),
    }
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
