"""Bounded creative authoring; the native Harness remains the final authority."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

STORY_FIELDS = (
    "id",
    "duty",
    "buyer_question",
    "lead_conclusion",
    "lead_claim_id",
    "selling_point_cluster_ids",
    "story_function",
    "pain_ids",
    "value_bridge_ids",
    "visual_proof_direction",
    "visual_archetype",
    "composition_family",
    "camera_scale",
    "primary_subject_class",
    "presentation_form",
    "complete_product_role",
)
PLANNING_SECONDS = 600.0
CALL_SECONDS = 180.0
REFERENCES = (
    "detail-story-grammar.md",
    "visual-proof.md",
    "storyboard-matrix.md",
    "continuity-and-rhythm.md",
    "compliance-and-platform.md",
    "reference-intelligence.md",
)


def system_prompt(root: Path) -> str:
    policy = """Author a fact-grounded Aurora v4.3.1 campaign in bounded stages.
The local native Harness owns compilation, approval, generation and pixel audit.
This call only authors the requested planning stage. Do not reproduce execution
instructions or audit reports. Never invent product facts, branding, specifications,
materials, performance or evidence. Source photo watermarks/backgrounds are not
product identity. Keep hypotheses separate from supplied facts. Use original fact IDs.
Every PRIMARY claim needs DEEP coverage: overview, dedicated proof, use/result and
closing recall across at least three screens. Preserve one story with distinct jobs.
8/10/12 screens require at least 4/5/6 subject classes and 5/6/7 presentation forms,
with at most 3/3/4 dominant complete-product screens. Middle proof screens may omit
the full product. Every normal screen needs useful visible content units bound to
fact IDs, copy and visual anchors; no slogan-only posters. Plan actual unequal zones,
not extra zones for labels. Never use two consecutive full-bleed single scenes.
BRANDLESS means zero independent logos. BRANDED means one authorized independent
logo on M01 only. User facts and observed facts retain separate provenance.
Write concise Chinese copy and observable visual relations. Keep internal evidence,
risk and approval workflow out of sales copy. Only schema JSON is returned.
"""
    return policy + "\n".join(
        f"\n--- {name} ---\n" + (root / "references" / name).read_text(encoding="utf-8")
        for name in REFERENCES
    )


def phase_schema(full: Mapping[str, Any], request: Any) -> dict[str, Any]:
    schema = deepcopy(full["json_schema"]["schema"])
    native = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "skill_sources"
            / "aurora-domestic-ecommerce-detail-page/schemas/detail-plan.schema.json"
        ).read_text(encoding="utf-8")
    )
    for key, prop in list(schema["properties"].items()):
        expanded = native["properties"].get(key, {})
        if (
            prop.get("type") == "object"
            and not prop.get("properties")
            and expanded.get("properties")
        ):
            schema["properties"][key] = deepcopy(expanded)
    depth = schema["properties"]["selling_point_depth_contract"]["properties"][
        "claim_depth"
    ]["items"]
    depth["required"].extend(["priority", "module_jobs"])
    depth["properties"].update(
        {
            "priority": {"const": "PRIMARY"},
            "module_jobs": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["module_id", "job"],
                    "properties": {
                        "module_id": {"type": "string", "pattern": "^M[0-9]{2,}$"},
                        "job": deepcopy(
                            depth["properties"]["required_decision_jobs"]["items"]
                        ),
                    },
                },
            },
        }
    )
    module = schema["properties"]["modules"]["items"]
    if request.authoring_stage == "story":
        module = {
            "type": "object",
            "additionalProperties": False,
            "required": list(STORY_FIELDS),
            "properties": {
                key: deepcopy(module["properties"][key]) for key in STORY_FIELDS
            },
        }
        ids = [f"M{i:02d}" for i in range(1, request.page_count + 1)]
        # A storyboard contains creative duties, not every nested rendering contract.
    else:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["modules"],
            "properties": {},
        }
        ids = list(request.authoring_target_ids)
        if len(ids) != 2:
            raise ValueError(
                "Atomic detail completion requires exactly two target screens"
            )
    slots = []
    context = request.authoring_context or {}
    locked = {m["id"]: m for m in context.get("modules", [])}
    for module_id in ids:
        item = deepcopy(module)
        item["properties"]["id"] = {"const": module_id}
        if request.authoring_stage == "pair":
            for key in STORY_FIELDS:
                item["properties"][key] = {"const": locked[module_id][key]}
            policy = {
                "DOMINANT": "REQUIRED_DOMINANT",
                "SUPPORTING": "REQUIRED_SUPPORTING",
                "IDENTITY_TOKEN_ONLY": "IDENTITY_TOKEN_ONLY",
                "ABSENT": "ABSENT_PREFERRED",
            }[locked[module_id]["complete_product_role"]]
            item["required"].append("product_presence_decision")
            item["properties"]["product_presence_decision"]["properties"]["policy"] = {
                "const": policy
            }
            expression = item["properties"]["expression"]
            if "product_presence_policy" not in expression["required"]:
                expression["required"].append("product_presence_policy")
            expression["properties"]["product_presence_policy"] = {"const": policy}
        slots.append(item)
    schema["properties"]["modules"] = {
        "type": "array",
        "minItems": len(ids),
        "maxItems": len(ids),
        "prefixItems": slots,
        "items": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "aurora_bounded_" + request.authoring_stage,
            "strict": False,
            "schema": schema,
        },
    }


def prompt(request: Any) -> str:
    context = deepcopy(request.authoring_context or {})
    errors = context.pop("validation_errors", None)
    if request.authoring_stage == "story":
        instruction = (
            "Create ONE complete campaign-level plan and a concise ordered atomic "
            "storyboard for exactly " + str(request.page_count) + " screens. "
            "The modules contain ONLY the requested spine fields; detailed proof, "
            "copy, zones and rendering contracts are authored in later calls. "
            "Use plan_format COMPACT_V1_3, information_contract_version 4.1 and "
            "expression_contract_version 4.3. Campaign contracts must be complete, "
            "including claim depth, coverage, pain/value bridges, visual DNA, hero "
            "and information progression. hero_screen_contract requires "
            "hero_module_id, "
            "hero_entity_id, hero_job, hero_uniqueness, supporting_entities_allowed, "
            "co_equal_hero_forbidden and hero_identity_evidence. "
            "detail_information_contract "
            "requires buyer_question_sequence, non_repeating_overview_limit, "
            "required_progression_jobs and every_pair_requires_information_delta. "
            "output_strategy.module_count_candidates contains exactly ONE object: "
            "candidate_mode=DIRECT_DERIVATION, decision=SELECTED, count equal to "
            "screen_count. Never emit rejected alternatives. Keep all required "
            "fit explanations and the six module_count_formula fields. "
            "Keep output_strategy.module_count exact. Pairs are adjacent M01/M02, "
            "M03/M04 etc with 3:8 canvases, two fixed 3:4 windows. Author their "
            "seam intent consistently with the atomic duties. Only the lower screen's "
            "incoming transition defines its pair's internal seam. Do not invent "
            "independent trust/ingredient/performance claims just to fill the count."
        )
        body = {
            "product_name": request.product_name,
            "user_information": request.product_information,
            "locked_intake": request.detail_intake,
            "platform": request.platform_code,
            "screen_size": request.size,
            "screen_count": request.page_count,
        }
        if context:
            body["prior_invalid_stage"] = context
    else:
        instruction = (
            "Complete ONLY the two specified atomic screens of this already authored "
            "story. Return {modules:[upper,lower]} with all compact fields. Every "
            "spine field constrained by const is frozen. Keep each screen's own "
            "duty, claims, copy, evidence and product presence; a pair is a raster "
            "container. Use the campaign's pair seam intent for the lower incoming "
            "transition. expression_signature is the exact '+' join of "
            "primary_subject_class,presentation_form,camera_scale,"
            "complete_product_role. "
            "content units must be distinct and bind actual fact IDs and visible copy. "
            "Do not repeat campaign objects. Do not guess facts from missing images: "
            "locked intake contains the original source observations and source IDs. "
            "STRUCTURE_ZONE_COUNTS: FULL_BLEED_HERO=1; SPLIT_PANEL,COMPARISON_SPLIT,"
            "MACRO_DIAGRAM,ASYMMETRIC_EDITORIAL,SPECIFICATION_BOARD,STACKED_BANDS=2; "
            "CENTRAL_OBJECT_ORBIT,FRAMED_LIFESTYLE_PLUS_CARDS,NESTED_INFO_BOARD,"
            "PORTRAIT_STRIP_PLUS_PAIN_ARRAY,PROCESS_STRIP_PLUS_RESULT,PRODUCT_PAIR_PLUS_TABLE,"
            "SELECTION_MATRIX=3. Labels occupy an existing spatial zone. "
            "No watermark, invented logo, internal risk or evidence workflow copy."
        )
        body = {
            "target_module_ids": request.authoring_target_ids,
            "campaign_and_story": context,
            "locked_intake": request.detail_intake,
        }
    return (
        instruction
        + "\nINPUT_JSON="
        + json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        + (
            "\nCorrect every listed error without changing frozen duties: "
            + json.dumps(errors, ensure_ascii=False)
            if errors
            else ""
        )
    )


def errors_for(
    payload: object, response_format: Mapping[str, Any]
) -> list[dict[str, Any]]:
    validator = Draft202012Validator(response_format["json_schema"]["schema"])
    return [
        {
            "path": "/" + "/".join(map(str, e.absolute_path)),
            "message": e.message,
            "constraint": e.validator,
            "expected": e.validator_value,
        }
        for e in sorted(
            validator.iter_errors(payload), key=lambda e: str(list(e.absolute_path))
        )
    ]


def selected_story(payload: object, page_count: int) -> object:
    """Discard only explicitly rejected alternatives, never author a decision."""
    value = deepcopy(payload)
    if not isinstance(value, dict):
        return value
    strategy = value.get("output_strategy")
    if not isinstance(strategy, dict):
        return value
    candidates = strategy.get("module_count_candidates")
    if not isinstance(candidates, list) or not candidates:
        return value
    if not all(isinstance(row, dict) for row in candidates):
        return value
    selected = [row for row in candidates if row.get("decision") == "SELECTED"]
    if (
        len(selected) == 1
        and selected[0].get("candidate_mode") == "DIRECT_DERIVATION"
        and selected[0].get("count") == page_count
        and all(row.get("decision") in {"SELECTED", "REJECTED"} for row in candidates)
    ):
        strategy["module_count_candidates"] = selected
    return value


def merge_error_fields(
    original: object, correction: object, errors: list[dict[str, Any]]
) -> object:
    """Apply only authored replacements at invalid subtrees, retaining valid fields."""
    merged: Any = deepcopy(original)
    paths = sorted(
        {tuple(e["path"].lstrip("/").split("/")) for e in errors},
        key=lambda p: (len(p), p),
    )
    applied: list[tuple[str, ...]] = []
    for path in paths:
        if any(path[: len(parent)] == parent for parent in applied):
            continue
        if path == ("",):
            return deepcopy(correction)
        try:
            source: Any = correction
            target = merged
            for token in path[:-1]:
                source = (
                    source[int(token)] if isinstance(source, list) else source[token]
                )
                target = (
                    target[int(token)] if isinstance(target, list) else target[token]
                )
            key = path[-1]
            value = source[int(key)] if isinstance(source, list) else source[key]
            if isinstance(target, list):
                target[int(key)] = deepcopy(value)
            else:
                target[key] = deepcopy(value)
            applied.append(path)
        except (KeyError, IndexError, TypeError, ValueError):
            # A missing authored replacement remains invalid; never synthesize it.
            continue
    return merged


def recover_story(
    request: Any, source_root: Path, binding: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Recover a story or pair from immutable replies on an explicit failed retry."""
    if request.authoring_stage not in {"story", "pair"} or (
        request.authoring_context or {}
    ).get("validation_errors"):
        return None
    from ..xinghe_agent import (
        _planner_response_format,
        normalize_usage,
        validate_aurora_domestic_plan,
    )
    from .planning_calls import NativePlanningStore
    from .plans import canonical_hash

    def context(value: Any) -> dict[str, Any]:
        return {
            k: v
            for k, v in dict(value or {}).items()
            if k not in {"validation_errors", "prior_response"}
        }

    def project(value: object) -> object:
        return (
            selected_story(value, request.page_count)
            if request.authoring_stage == "story"
            else deepcopy(value)
        )

    truth_fields = (
        "product_name",
        "product_information",
        "page_count",
        "language",
        "platform_code",
        "size",
        "domestic_protocol",
        "source_inventory",
        "detail_intake",
        "intake_settings",
        "intake_resolution",
        "authoring_stage",
        "authoring_target_ids",
    )
    current = binding["semantic_request"]["semantics"]
    schema = _planner_response_format(request)
    candidates = []
    base = None
    for path in sorted(
        source_root.glob("*.request.json"), key=lambda p: p.stat().st_mtime_ns
    ):
        raw = json.loads(path.read_bytes())["binding"]
        old = NativePlanningStore(source_root, raw)
        if old.store.request_path != path:
            continue
        semantics = raw.get("semantic_request", {}).get("semantics", {})
        if (
            raw.get("phase") != binding["phase"]
            or raw.get("group_key") != binding["group_key"]
            or raw.get("skill_content_hash") != binding["skill_content_hash"]
            or raw.get("dispatch_route") != binding["dispatch_route"]
            or any(
                canonical_hash(semantics.get(k)) != canonical_hash(current.get(k))
                for k in truth_fields
            )
            or canonical_hash(context(semantics.get("authoring_context")))
            != canonical_hash(context(current.get("authoring_context")))
        ):
            continue
        result = old._original()
        if result.get("error_code") or not isinstance(result.get("payload"), Mapping):
            continue
        projected = project(result["payload"])
        source_hashes = [canonical_hash(result)]
        correction = bool(
            (semantics.get("authoring_context") or {}).get("validation_errors")
        )
        if correction and base is not None and errors_for(projected, schema):
            prior = project(base["payload"])
            projected = merge_error_fields(prior, projected, errors_for(prior, schema))
            source_hashes.insert(0, canonical_hash(base))
        elif not correction:
            base = result
        if errors_for(projected, schema):
            continue
        assert isinstance(projected, dict)
        if request.authoring_stage == "story":
            validate_aurora_domestic_plan(
                projected, request.page_count, campaign_only=True
            )
        candidates.append(
            (path.stat().st_mtime_ns, raw, result, projected, source_hashes)
        )
    if not candidates:
        return None
    _, original, result, projected, source_hashes = max(
        candidates, key=lambda row: row[0]
    )
    return {
        **result,
        "payload": projected,
        "audit_raw_content": None,
        "provider_request_id": None,
        "raw_usage": None,
        "normalized_usage": normalize_usage(None),
        "api_latency_seconds": 0,
        "actual_cost_micros": 0,
        "external_request": False,
        "phase": "aurora_recovered_" + request.authoring_stage,
        "supplemental_results": (),
        "provider_envelope": {
            "authored_input_recovery": {
                "source_binding_sha256": canonical_hash(original),
                "source_result_sha256": canonical_hash(result),
                "source_result_hashes": source_hashes,
                "projected_payload_sha256": canonical_hash(projected),
                "source_request_file": str(
                    NativePlanningStore(source_root, original).store.request_path
                ),
                "provider_request_count": 0,
            }
        },
    }


def fake_phase(payload: Mapping[str, Any], request: Any) -> dict[str, Any]:
    """Project the explicit synthetic fixture through the real stage schemas."""
    from .mock_intake import bounded_mock_campaign

    value = bounded_mock_campaign(payload, request.detail_intake)
    if request.authoring_stage == "story":
        value["modules"] = [{k: m[k] for k in STORY_FIELDS} for m in value["modules"]]
    elif request.authoring_stage == "pair":
        context = request.authoring_context
        locked = {m["id"]: m for m in context["modules"]}
        patterns = context["reference_expression_system"]["adopted_patterns"]
        for module in value["modules"]:
            for key in STORY_FIELDS:
                module[key] = deepcopy(locked[module["id"]][key])
            module["reference_pattern_ids"] = [
                p["id"] for p in patterns if module["id"] in p["scheduled_module_ids"]
            ]
        value = {
            "modules": [
                m for m in value["modules"] if m["id"] in request.authoring_target_ids
            ]
        }
    return value


async def complete(
    coordinator: Any, request: Any, result: Any, results: list[Any]
) -> dict[str, Any]:
    # Local import avoids a module-load cycle with the shared gateway.
    from ..xinghe_agent import (
        AuroraDetailHarnessError,
        XingheAgentError,
        _planner_response_format,
        detail_workspace,
        validate_aurora_domestic_plan,
        write_detail_contract,
    )

    index = len(results) - 1
    extra: list[Any] = []
    corrections = 0
    payload: dict[str, Any] = {}

    async def accept(stage_request: Any, response: Any) -> dict[str, Any]:
        nonlocal corrections

        def candidate(value: Any) -> Any:
            return (
                selected_story(value, request.page_count)
                if stage_request.authoring_stage == "story"
                else deepcopy(value)
            )

        value = candidate(response.payload)
        errors = errors_for(value, _planner_response_format(stage_request))
        if errors:
            if corrections:
                raise XingheAgentError(
                    "AURORA_AUTHORING_INVALID",
                    "Bounded authoring correction exhausted",
                    validation_errors=errors,
                )
            corrections += 1
            context = deepcopy(stage_request.authoring_context or {})
            context["prior_response"] = response.payload
            prior_candidate = value
            prior_errors = errors
            context["validation_errors"] = errors
            correction = replace(
                stage_request,
                authoring_context=context,
                idempotency_key=stage_request.idempotency_key + ":correction-1",
            )
            response = await coordinator._native_planner_call(correction)
            extra.append(response)
            if response.error_code:
                raise XingheAgentError(
                    response.error_code,
                    response.error_message or "Authoring result unknown",
                )
            value = merge_error_fields(
                prior_candidate, candidate(response.payload), prior_errors
            )
            from .plans import canonical_hash

            write_detail_contract(
                detail_workspace(request.job_id)
                / "planning"
                / (
                    "correction-projection-"
                    + stage_request.authoring_stage
                    + "-"
                    + ("+".join(stage_request.authoring_target_ids) or "campaign")
                    + ".json"
                ),
                {
                    "rule": "only-replace-invalid-authored-subtrees-v1",
                    "original_payload_sha256": canonical_hash(prior_candidate),
                    "correction_payload_sha256": canonical_hash(response.payload),
                    "merged_payload_sha256": canonical_hash(value),
                    "validation_errors": prior_errors,
                },
            )
            errors = errors_for(value, _planner_response_format(stage_request))
            if errors:
                raise XingheAgentError(
                    "AURORA_AUTHORING_INVALID",
                    "Corrected stage remains invalid",
                    validation_errors=errors,
                )
        if (
            stage_request.authoring_stage == "story"
            and selected_story(response.payload, request.page_count) != response.payload
        ):
            from .plans import canonical_hash

            write_detail_contract(
                detail_workspace(request.job_id)
                / "planning"
                / "selected-story-projection.json",
                {
                    "rule": "retain-the-single-authored-direct-selection-v1",
                    "source_payload_sha256": canonical_hash(response.payload),
                    "projected_payload_sha256": canonical_hash(value),
                    "discarded": [
                        row
                        for row in response.payload["output_strategy"][
                            "module_count_candidates"
                        ]
                        if row.get("decision") == "REJECTED"
                    ],
                },
            )
        return deepcopy(dict(value))

    try:
        payload = await accept(request, result)
        payload["product_intake"] = deepcopy(request.detail_intake)
        # Structural campaign validation occurs before any screen-completion spend.
        validate_aurora_domestic_plan(
            payload,
            request.page_count,
            skill_root=coordinator.skill_root,
            campaign_only=True,
        )
        story = deepcopy(payload)
        completed: list[dict[str, Any]] = []
        for offset in range(0, request.page_count, 2):
            targets = tuple(m["id"] for m in story["modules"][offset : offset + 2])
            context = deepcopy(story)
            # The compact full storyboard preserves global rhythm; completed detail
            # is only needed for the immediately preceding handoff, not all screens.
            if completed:
                context["previous_completed_screen"] = completed[-1]
            pair_request = replace(
                request,
                planning_profile="aurora_domestic_modules_completion",
                authoring_stage="pair",
                authoring_target_ids=targets,
                authoring_context=context,
                sources=(),
                idempotency_key=request.idempotency_key + ":" + "+".join(targets),
            )
            response = await coordinator._native_planner_call(pair_request)
            extra.append(response)
            if response.error_code:
                raise XingheAgentError(
                    response.error_code,
                    response.error_message or "Authoring result unknown",
                )
            pair = await accept(pair_request, response)
            completed.extend(pair["modules"])
            write_detail_contract(
                detail_workspace(request.job_id)
                / "planning"
                / f"authored-{offset // 2 + 1}.json",
                pair,
            )
        payload["modules"] = completed
        structured = validate_aurora_domestic_plan(
            payload, request.page_count, skill_root=coordinator.skill_root
        )
        structured["native_approval"] = await asyncio.to_thread(
            coordinator._preflight_aurora_plan, request, structured["aurora_plan"]
        )
        return structured
    except AuroraDetailHarnessError as exc:
        raise XingheAgentError("AURORA_PLAN_PREFLIGHT_INVALID", str(exc)) from exc
    finally:
        results[index] = replace(
            result,
            payload=payload or result.payload,
            phase="aurora_domestic_detail",
            supplemental_results=(*result.supplemental_results, *extra),
        )
