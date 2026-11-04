"""Source-bound story planning. Structural checks never invent semantic verdicts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .replica_exact_contracts import canonical_hash
from .replica_native import ReplicaNativeError

STORY_DIMENSIONS = (
    "role_fidelity",
    "information_gain",
    "semantic_handoff",
    "evidence_fit",
    "source_coverage",
)


class StoryEvidenceMissing(ReplicaNativeError):
    code = "REPLICA_STORY_EVIDENCE_MISSING"
    message = "部分参考页缺少可对应的商品事实，已保留方案；请补充相关资料后重新分析。"


class StoryPlanningIncomplete(ReplicaNativeError):
    code = "REPLICA_STORY_PLAN_INCOMPLETE"
    message = "整套讲述方案尚未通过内容检查，已保留当前进度，请继续分析后再生成。"


def obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def text(minimum: int = 8, maximum: int = 800) -> dict[str, Any]:
    return {"type": "string", "minLength": minimum, "maxLength": maximum}


def array(item: dict[str, Any], maximum: int = 60) -> dict[str, Any]:
    return {"type": "array", "items": item, "maxItems": maximum}


def source_story_schema() -> dict[str, Any]:
    return obj(
        {
            key: text()
            for key in (
                "source_role",
                "buyer_question",
                "persuasion_job",
                "belief_shift",
                "evidence_obligations",
                "expression_actions",
                "semantic_handoff",
            )
        }
    )


def mapping_schema() -> dict[str, Any]:
    return obj(
        {
            "entries": array(
                obj(
                    {
                        "reference_unit_id": text(1, 40),
                        "target_role": text(),
                        "target_fact_ids": array(text(1, 40), 40),
                        "translation": text(),
                        "information_gain": text(),
                        "relation_to_previous": text(),
                        "next_unit_id": {"type": ["string", "null"], "maxLength": 40},
                        "handoff": text(),
                        "repetition_mode": {
                            "enum": [
                                "different_argument",
                                "source_repetition",
                                "opening",
                                "closure",
                            ]
                        },
                        "repetition_reason": text(),
                        "evidence_gap": text(0),
                    }
                )
            )
        }
    )


def review_schema() -> dict[str, Any]:
    return obj(
        {
            "unit_checks": array(
                obj(
                    {
                        "reference_unit_id": text(1, 40),
                        "comparisons": {
                            **array(
                                obj(
                                    {
                                        "dimension": {"enum": list(STORY_DIMENSIONS)},
                                        "match": {"type": "boolean"},
                                        "evidence": text(12),
                                    }
                                ),
                                len(STORY_DIMENSIONS),
                            ),
                            "minItems": len(STORY_DIMENSIONS),
                        },
                        "material_mismatches": array(text()),
                        "revise_mapping": {"type": "boolean"},
                        "decision": {"enum": ["PASS", "FAIL"]},
                    }
                )
            )
        }
    )


def source_sequence(units: list[dict[str, Any]], layouts: Any) -> list[dict[str, Any]]:
    return [
        {
            "reference_unit_id": unit["id"],
            "source_story": deepcopy(layouts[unit["id"]]["source_story"]),
            "reference_observation": deepcopy(
                layouts[unit["id"]]["reference_observation"]
            ),
        }
        for unit in units
    ]


def bind_mapping(
    value: dict[str, Any],
    units: Any,
    layouts: Any,
    ledger: Any,
    previous: Any = None,
    repair_ids: Any = None,
) -> dict[str, Any]:
    ids = [u["id"] for u in units]
    entries = value["entries"]
    if [row["reference_unit_id"] for row in entries] != ids:
        raise ValueError("Map every source screen exactly once in source order")
    approved = {f["id"] for f in ledger["facts"] if f["disposition"] == "approved"}
    old = {r["reference_unit_id"]: r for r in (previous or {}).get("entries", [])}
    for index, row in enumerate(entries):
        facts = row["target_fact_ids"]
        if len(facts) != len(set(facts)) or not set(facts) <= approved:
            raise ValueError("Story mapping may select approved fact IDs only")
        if row["next_unit_id"] != (ids[index + 1] if index + 1 < len(ids) else None):
            raise ValueError("Story handoffs must follow the actual adjacent source")
        uid = row["reference_unit_id"]
        if old and uid not in (repair_ids or []) and row != old[uid]:
            raise ValueError("Retain story assignments outside the requested repair")
    binding = {
        "schema": "replica-story-mapping-v1",
        "source_version": canonical_hash(
            [
                [u["id"], u["crop_sha256"], layouts[u["id"]]["source_story"]]
                for u in units
            ]
        ),
        "facts_version": ledger["version"],
        "entries": deepcopy(entries),
    }
    return {**binding, "version": canonical_hash(binding)}


def validate_mapping(mapping: Any, units: Any, layouts: Any, ledger: Any) -> None:
    rebound = bind_mapping({"entries": mapping["entries"]}, units, layouts, ledger)
    if mapping != rebound:
        raise ValueError("Story mapping source, facts or version changed")
    if any(row["evidence_gap"].strip() for row in mapping["entries"]):
        raise StoryEvidenceMissing()


def entry_for(mapping: Any, uid: str) -> dict[str, Any]:
    return next(row for row in mapping["entries"] if row["reference_unit_id"] == uid)


def module_binding(mapping: Any, uid: str) -> dict[str, Any]:
    row = entry_for(mapping, uid)
    # Unchanged entries retain their own binding when another page is corrected.
    return {"entry_version": canonical_hash(row), **deepcopy(row)}


def validate_proposal(proposal: Any, mapping: Any) -> None:
    row = entry_for(mapping, proposal["reference_unit_id"])
    commercial = proposal["commercial_adaptation"]
    if (
        proposal["page_duty"] != row["target_role"]
        or commercial["supported_role"] != row["target_role"]
    ):
        raise ValueError("Use the assigned story target_role verbatim for this page")
    assigned = set(row["target_fact_ids"])
    if not set(commercial["fact_ids"]) <= assigned:
        raise ValueError("Commercial adaptation must use this screen's assigned facts")
    used = set(commercial["fact_ids"]) | {
        fid
        for adaptation in proposal["fact_adaptations"]
        for fid in adaptation["fact_ids"]
    }
    if not assigned <= used:
        raise ValueError("The screen must use its assigned story facts")


def bind_plan(plan: Any, mapping: Any) -> None:
    plan["story_mapping_version"] = mapping["version"]
    for module in plan["modules"]:
        module["story_binding"] = module_binding(mapping, module["reference_unit_id"])


def validate_story_review(value: Any, ids: list[str]) -> None:
    rows = value["unit_checks"]
    if [r["reference_unit_id"] for r in rows] != ids:
        raise ValueError("Review every story screen once in source order")
    for row in rows:
        checks = row["comparisons"]
        if [c["dimension"] for c in checks] != list(STORY_DIMENSIONS):
            raise ValueError("Return all story comparison dimensions in order")
        if len({c["evidence"] for c in checks}) != len(checks):
            raise ValueError("Each story comparison needs its own concrete evidence")
        passed = all(c["match"] for c in checks) and not row["material_mismatches"]
        if (row["decision"] == "PASS") != passed:
            raise ValueError("Story decision conflicts with its actual comparisons")
        if row["revise_mapping"] and passed:
            raise ValueError("A mapping correction must identify an actual failure")


def merge_story_review(audits: Any, review: Any) -> None:
    """Carry actual model findings into the native pre-generation plan gate."""
    checks = {row["reference_unit_id"]: row for row in review["unit_checks"]}
    for audit in audits:
        row = checks[audit["unit_id"]]
        if row["decision"] == "PASS":
            continue
        findings = [c["evidence"] for c in row["comparisons"] if not c["match"]]
        findings.extend(row["material_mismatches"])
        audit["material_mismatches"].extend("Story: " + f for f in findings)
        commercial = next(
            c for c in audit["comparisons"] if c["dimension"] == "commercial_function"
        )
        commercial["match"] = False
        commercial["evidence"] += " | Story: " + " | ".join(findings)
        audit["decision"] = "FAIL"


def mapping_repair_ids(review: Any, ids: list[str]) -> list[str]:
    affected = {
        r["reference_unit_id"] for r in review["unit_checks"] if r["revise_mapping"]
    }
    # Only the failing allocation and its actual handoff neighbours may change.
    return [
        uid
        for i, uid in enumerate(ids)
        if any(ids[j] in affected for j in range(max(0, i - 1), min(len(ids), i + 2)))
    ]
