from __future__ import annotations

from .state import HarnessError, require_fields


CANDIDATE_MODES = ("COMPACT_COVERAGE", "BALANCED_EXPRESSION", "FULL_SALES")
DECISION_JOBS = {
    "PROBLEM_CONTEXT", "VALUE_OVERVIEW", "DEDICATED_EXPRESSION", "MECHANISM_OR_REASON",
    "USE_SCOPE", "ACTION_OR_OPERATION", "RESULT_OR_EXPERIENCE", "RISK_QUALIFICATION",
    "SELECTION", "TRUST", "RECALL",
}
EVIDENCE_CEILINGS = {"DIRECT_PROOF_AVAILABLE", "QUALIFIED_CLAIM_ONLY", "PACKAGING_CLAIM_ONLY", "CONTEXT_ONLY"}


def validate_formula_split_contract(plan: dict, fact_ids: set[str]) -> None:
    """Require independently meaningful formula/ingredient claims to have own modules."""
    contract = plan.get("formula_split_contract")
    if not contract:
        return
    require_fields(contract, ("enabled", "trigger_basis", "entries"), "formula split contract")
    if not contract["enabled"]:
        if contract["entries"]:
            raise HarnessError("A disabled formula split contract must not contain entries")
        return
    if not contract["entries"]:
        raise HarnessError("Enabled formula split contract must list each independent formula/element claim")
    modules = {item["id"]: item for item in plan["modules"]}
    seen_modules = set()
    for entry in contract["entries"]:
        require_fields(entry, ("claim_id", "formula_or_element", "independent_split_reason", "buyer_problem_or_question", "supported_benefit", "evidence_ceiling", "dedicated_module_id", "visual_expression_route"), "formula split entry")
        if entry["claim_id"] not in fact_ids or entry["evidence_ceiling"] not in EVIDENCE_CEILINGS:
            raise HarnessError("Formula split entries must use active verified claims and approved evidence ceilings")
        module_id = entry["dedicated_module_id"]
        if module_id not in modules or module_id in seen_modules:
            raise HarnessError("Each independent formula/element claim needs its own dedicated module")
        seen_modules.add(module_id)
        module = modules[module_id]
        module_claims = {module.get("lead_claim_id"), *module.get("supporting_claim_ids", [])}
        if entry["claim_id"] not in module_claims:
            raise HarnessError("A formula dedicated module must carry its verified claim")
        if module.get("lead_claim_id") != entry["claim_id"]:
            raise HarnessError("A formula dedicated module must lead with that formula/element claim")


def validate_sales_depth_contract(plan: dict, fact_ids: set[str]) -> None:
    strategy = plan["output_strategy"]
    candidates = strategy["module_count_candidates"]
    if len(candidates) < 3:
        raise HarnessError("Normal sales planning must compare compact, balanced and full-sales module-count candidates")
    by_mode = {}
    for candidate in candidates:
        require_fields(
            candidate,
            ("candidate_mode", "count", "coverage_tradeoff", "selling_point_fit", "story_obligation_fit",
             "primary_selling_point_depth_fit", "evidence_boundary_fit", "decision"),
            "v0.9.1 module-count candidate",
        )
        mode = candidate["candidate_mode"]
        if mode not in CANDIDATE_MODES or mode in by_mode:
            raise HarnessError("Module-count candidates must contain each of compact, balanced and full-sales modes exactly once")
        by_mode[mode] = candidate
    if set(by_mode) != set(CANDIDATE_MODES):
        raise HarnessError("Module-count candidates must contain compact, balanced and full-sales modes")
    if not by_mode["COMPACT_COVERAGE"]["count"] < by_mode["BALANCED_EXPRESSION"]["count"] < by_mode["FULL_SALES"]["count"]:
        raise HarnessError("Compact, balanced and full-sales candidate counts must increase distinctly")

    selected = [item for item in candidates if item["decision"] == "SELECTED"]
    if len(selected) != 1:
        raise HarnessError("Exactly one module-count candidate must be selected")

    contract = plan.get("selling_point_depth_contract")
    if not contract:
        raise HarnessError("Route-aware sales planning requires selling_point_depth_contract")
    require_fields(contract, ("selection_policy", "primary_claim_ids", "claim_depth"), "selling-point depth contract")
    if "compact_selection_exception" not in contract or not isinstance(contract["compact_selection_exception"], str):
        raise HarnessError("Selling-point depth contract requires compact_selection_exception, using an empty string when not applicable")
    primary = set(contract["primary_claim_ids"])
    if not primary or primary - fact_ids:
        raise HarnessError("Primary selling points must use active verified fact IDs")
    recall_primary = set(plan.get("campaign_recall_contract", {}).get("must_remember_claim_ids", []))
    if primary != recall_primary:
        raise HarnessError("Selling-point depth primary claims must equal the campaign must-remember claims")
    depth_items = contract["claim_depth"]
    if {item.get("claim_id") for item in depth_items} != primary:
        raise HarnessError("Selling-point depth entries must account for every primary claim exactly once")
    modules = {item["id"]: item for item in plan["modules"]}
    deep_count = 0
    for item in depth_items:
        require_fields(
            item,
            ("claim_id", "depth_tier", "evidence_ceiling", "required_decision_jobs", "scheduled_module_ids",
             "dedicated_module_ids", "non_duplicate_rationale", "forbidden_expansion"),
            "selling-point depth entry",
        )
        if item["depth_tier"] not in ("DEEP", "STANDARD", "SUPPORT") or item["evidence_ceiling"] not in EVIDENCE_CEILINGS:
            raise HarnessError("Selling-point depth entry has an unsupported tier or evidence ceiling")
        if plan.get("plan_format") == "COMPACT_V1_2":
            require_fields(item, ("priority", "module_jobs"), "v1.2 selling-point depth entry")
            if item["priority"] != "PRIMARY":
                raise HarnessError("Every must-remember claim must be explicitly prioritized PRIMARY")
            if not isinstance(item["module_jobs"], list) or not item["module_jobs"]:
                raise HarnessError("Every primary claim needs an explicit module-to-decision-job map")
        jobs = set(item["required_decision_jobs"])
        scheduled = set(item["scheduled_module_ids"])
        dedicated = set(item["dedicated_module_ids"])
        if not jobs or jobs - DECISION_JOBS or not scheduled or scheduled - set(modules) or dedicated - scheduled:
            raise HarnessError("Selling-point depth jobs and modules must use approved values")
        if not dedicated:
            raise HarnessError("Every primary selling point needs at least one dedicated or visually dominant module")
        for module_id in dedicated:
            if plan.get("plan_format") == "COMPACT_V1_2":
                if modules[module_id]["lead_claim_id"] != item["claim_id"]:
                    raise HarnessError("A dedicated selling-point module must lead with that claim; supporting presence is not depth")
            else:
                module_claims = {modules[module_id]["lead_claim_id"], *modules[module_id].get("supporting_claim_ids", [])}
                if item["claim_id"] not in module_claims:
                    raise HarnessError("A dedicated selling-point module must actually carry that verified claim")
        if item["depth_tier"] == "DEEP":
            deep_count += 1
            if plan.get("plan_format") == "COMPACT_V1_2":
                required_core = {"VALUE_OVERVIEW", "DEDICATED_EXPRESSION", "RECALL"}
                outcome_jobs = {"MECHANISM_OR_REASON", "USE_SCOPE", "ACTION_OR_OPERATION", "RESULT_OR_EXPERIENCE", "SELECTION", "TRUST"}
                if len(jobs) < 4 or len(scheduled) < 3 or not required_core.issubset(jobs) or not jobs & outcome_jobs:
                    raise HarnessError("A DEEP selling point needs overview, dedicated proof, a use/result decision job and recall")
                mapped_modules = {entry.get("module_id") for entry in item["module_jobs"]}
                mapped_jobs = {entry.get("job") for entry in item["module_jobs"]}
                if mapped_modules != scheduled or mapped_jobs != jobs:
                    raise HarnessError("module_jobs must exactly explain scheduled modules and required decision jobs")
            elif len(jobs) < 2 or len(scheduled) < 2:
                raise HarnessError("A DEEP selling point needs at least two decision jobs and two modules")
        if item["evidence_ceiling"] in ("PACKAGING_CLAIM_ONLY", "CONTEXT_ONLY") and "MECHANISM_OR_REASON" in jobs:
            raise HarnessError("Packaging-only or context-only evidence cannot be expanded into a mechanism claim")
    if plan.get("plan_format") == "COMPACT_V1_2":
        if deep_count != len(primary):
            raise HarnessError("Every must-remember primary selling point must receive DEEP sales treatment")
    else:
        minimum_deep = 2 if len(primary) >= 3 else 1
        if deep_count < minimum_deep:
            raise HarnessError("The must-remember selling-point set is underdeveloped for a sales detail page")

    if selected[0]["candidate_mode"] == "COMPACT_COVERAGE":
        reason = str(contract["compact_selection_exception"]).strip()
        if len(reason) < 20:
            raise HarnessError("Compact coverage is a lower bound; selecting it requires an explicit user or evidence limitation")
