"""Domestic detail model intake contracts and immutable local receipts."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .facts import (
    INTAKE_VERSION,
    DetailIntakeError,
    _native_schemas,
    _schema,
    user_fact_ledger,
)
from .planner_dispatch import require_route, validate_dispatch_result
from .plans import canonical_hash

INTAKE_PROFILE = "aurora_domestic_intake"


def intake_response_schema() -> dict[str, Any]:
    native_input, identity = _native_schemas()
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "version",
            "conflict_scan",
            "source_conflicts",
            "observed_facts",
            "brand_confirmation_required",
        ],
        "properties": {
            "version": {"const": INTAKE_VERSION},
            "conflict_scan": native_input["properties"]["conflict_scan"],
            "source_conflicts": native_input["properties"]["source_conflicts"],
            "observed_facts": {
                "type": "array",
                "items": native_input["properties"]["verified_facts"]["items"],
            },
            "identity": {"anyOf": [identity, {"type": "null"}]},
            "identity_observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["kind", "source_asset_id", "region", "text"],
                    "properties": {
                        "kind": {
                            "enum": [
                                "silhouette",
                                "proportions",
                                "parts",
                                "color_material",
                            ]
                        },
                        **{
                            key: {"type": "string"}
                            for key in ("source_asset_id", "region", "text")
                        },
                    },
                },
            },
            "reference_materials": native_input["properties"]["reference_materials"],
            "operating_analysis": native_input["properties"]["operating_analysis"],
            "brand_confirmation_required": {"type": "boolean"},
            "brand_observation": {"type": "object"},
            "target_buyer": {"type": "string"},
            "primary_scenario": {"type": "string"},
        },
    }


def intake_prompt(
    settings: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
    resolution: Mapping[str, Any] | None = None,
) -> str:
    return (
        "Perform source intake BEFORE identity lock or any storyboard. "
        "Return JSON only, with version=domestic-detail-intake-v1. The "
        "attached product_reference images and original user facts are "
        "the only product truth. style_reference images teach visual "
        "grammar only. Never turn generated images or references into "
        "facts. Scan every product asset ID and every original Fxx user "
        "fact ID: list them in conflict_scan.scanned_source_refs. Report "
        "only real material SKU/specification/performance conflicts and "
        "all alternative fact IDs, with source-specific observations. A "
        "material conflict MUST stop before identity/storyboard; omit "
        "identity and modules. Use O01.. for observed facts and cite "
        "evidence_ref as an original product asset ID, with "
        "observed_region. Preserve the Fxx IDs and original user text "
        "without rewriting. Do not repeat preservation policies as "
        "observations. When clear, provide exactly four "
        "identity_observations (silhouette, proportions, parts, "
        "color_material) describing actual visible geometry, region and "
        "source_asset_id; identity.invariant_features must equal their "
        "ordered text. Proportions must describe visible ratio/shape and "
        "parts must state actual count and relation. Retain the user's "
        "exact product_name/category when supplied. BRANDED requires a "
        "readable current-product logo, its exact observed_logo_text and "
        "observed_region. BRANDLESS requires the user's explicit "
        "brandless_confirmation, retained verbatim in "
        "brandless_evidence. If neither is available, set "
        "brand_confirmation_required=true, describe actual "
        "brand_observation, and omit identity; ask no other unnecessary "
        "questions. Analyze every style asset as reference_materials "
        "using its asset ID, path=asset:<id>, concrete analyzed_units "
        "and observed_expression_methods. Do not fabricate ANALYZED "
        "references. No full plan/modules/copy is permitted in this "
        "response. Observed facts are atomic: include atomic_key and "
        "atomicity=ONE_INDEPENDENT_PROPOSITION. When the user supplied "
        "no selling points, include complete operating_analysis with "
        "fact-bound value bridges; disclose buyer/pain hypotheses as "
        "hypotheses, never product facts. If HUMAN_RESOLUTION is "
        "supplied, honor its exact "
        "retained/rejected fact IDs and confirmation text. Preserve "
        "original conflict IDs, alternatives and observed facts; do not "
        "invent a new silent resolution. Return source_conflicts as "
        "UNRESOLVED (the native Harness will apply the exact user "
        "receipt before identity lock); an approved resolution permits "
        "the identity analysis.\n"
    ) + json.dumps(
        {
            "USER_FACTS": user_fact_ledger(settings),
            "SETTINGS": dict(settings),
            "SOURCES": list(sources),
            "HUMAN_RESOLUTION": resolution,
        },
        ensure_ascii=False,
    )


def validate_resolution(
    raw_intake: Mapping[str, Any], resolution: Mapping[str, Any]
) -> dict[str, Any]:
    source = Path(__file__).resolve().parents[2] / (
        "skill_sources/aurora-domestic-ecommerce-detail-page/schemas/conf"
        "lict-resolution.schema.json"
    )
    if (
        not isinstance(resolution.get("confirmation_text"), str)
        or not resolution["confirmation_text"].strip()
    ):
        raise DetailIntakeError(
            "INTAKE_RESOLUTION_INVALID",
            "Preserve the user's explicit confirmation words",
        )
    conflicts = {item["id"]: item for item in raw_intake.get("source_conflicts", [])}
    if conflicts:
        _schema(
            resolution,
            json.loads(source.read_text(encoding="utf-8")),
            "/intake_resolution",
        )
    rows = resolution.get("resolutions")
    if (
        not isinstance(rows, list)
        or len(rows) != len(conflicts)
        or {item.get("conflict_id") for item in rows} != set(conflicts)
    ):
        raise DetailIntakeError(
            "INTAKE_RESOLUTION_INCOMPLETE",
            "One response must account for every material conflict exactly once",
        )
    all_retained: set[str] = set()
    all_rejected: set[str] = set()
    for row in rows:
        retained, rejected = (
            set(row["retained_fact_ids"]),
            set(row["rejected_fact_ids"]),
        )
        alternatives = set(conflicts[row["conflict_id"]]["alternative_fact_ids"])
        if not retained or retained & rejected or retained | rejected != alternatives:
            raise DetailIntakeError(
                "INTAKE_RESOLUTION_INVALID",
                (
                    "Retain at least one known alternative and explicitly reject "
                    "every other value"
                ),
            )
        all_retained.update(retained)
        all_rejected.update(rejected)
    if all_retained & all_rejected:
        raise DetailIntakeError(
            "INTAKE_RESOLUTION_CONTRADICTORY",
            "A fact cannot be both retained and rejected across conflicts",
        )
    return deepcopy(dict(resolution))


def active_fact_ids(intake: Mapping[str, Any]) -> list[str]:
    rejected = {
        fact_id
        for row in (intake.get("resolution") or {}).get("resolutions", [])
        for fact_id in row["rejected_fact_ids"]
    }
    return [
        fact["id"]
        for fact in [*intake.get("user_facts", []), *intake.get("observed_facts", [])]
        if fact["id"] not in rejected
    ]


def intake_binding(
    *,
    settings: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
    skill_hash: str,
    model: str,
    resolution: Mapping[str, Any] | None,
    dispatch_route: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_root = Path(__file__).parent
    value = {
        "version": INTAKE_VERSION,
        "settings": dict(settings),
        "sources": list(sources),
        "skill_content_hash": skill_hash,
        "model": model,
        "dispatch_route": deepcopy(dict(dispatch_route)) if dispatch_route else None,
        "resolution": resolution,
        "intake_runtime_sha256": canonical_hash(
            {
                "adapter": hashlib.sha256(
                    (source_root.parent / "xinghe_agent.py").read_bytes()
                ).hexdigest(),
                **{
                    name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
                    for name in ("facts.py", "intake.py", "planner_dispatch.py")
                },
            }
        ),
    }
    return {**value, "sha256": canonical_hash(value)}


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


@dataclass(frozen=True)
class IntakeStore:
    root: Path
    binding: Mapping[str, Any]
    job_id: str | None = None

    @property
    def path(self) -> Path:
        return self.root / (str(self.binding["sha256"]) + ".json")

    def completed(self) -> dict[str, Any] | None:
        if self.binding.get("sha256") != canonical_hash(
            {k: v for k, v in self.binding.items() if k != "sha256"}
        ):
            raise DetailIntakeError(
                "INTAKE_BINDING_CHANGED", "The original intake binding hash changed"
            )
        if not self.path.exists():
            for previous in self.root.glob("*.json"):
                if previous.name.endswith(".response.json"):
                    continue
                old = json.loads(previous.read_text(encoding="utf-8")).get(
                    "binding", {}
                )
                if all(
                    old.get(key) == self.binding.get(key)
                    for key in ("settings", "sources", "resolution")
                ):
                    raise DetailIntakeError(
                        "INTAKE_BINDING_CHANGED",
                        "An existing intake has a different code, Skill, or model "
                        "binding; reconcile it before dispatch",
                    )
            return None
        request = json.loads(self.path.read_text(encoding="utf-8"))
        if self.job_id is not None and request.get("job_id") != self.job_id:
            raise DetailIntakeError(
                "INTAKE_RECEIPT_INVALID", "The original intake belongs to another job"
            )
        if canonical_hash(request.get("binding")) != canonical_hash(self.binding):
            raise DetailIntakeError(
                "INTAKE_BINDING_CHANGED", "Saved intake inputs or Skill changed"
            )
        completion = self.path.with_suffix(".response.json")
        if not completion.exists():
            raise DetailIntakeError(
                "INTAKE_OUTCOME_UNKNOWN",
                "Reconcile the original intake before another paid request",
            )
        value = json.loads(completion.read_text(encoding="utf-8"))
        if value.get("sha256") != canonical_hash(value.get("result")):
            raise DetailIntakeError(
                "INTAKE_RESPONSE_CHANGED", "The original model intake receipt changed"
            )
        result = value["result"]
        if self.binding.get("dispatch_route") is not None:
            route = require_route(self.binding["dispatch_route"])
            validate_dispatch_result(result, route)
            expected = {
                "version": "native-intake-call-v1",
                "binding_sha256": self.binding["sha256"],
                "request_file": "intake/" + self.path.name,
                "response_file": "intake/" + completion.name,
                "source_job_id": request["job_id"],
            }
            envelope = result.get("provider_envelope") or {}
            if canonical_hash(envelope.get("native_intake_receipt")) != canonical_hash(
                expected
            ):
                raise DetailIntakeError(
                    "INTAKE_RECEIPT_INVALID",
                    "The original intake event identity changed",
                )
            if route["kind"] == "http" and result.get("error_code") is None:
                from ..xinghe_agent import _planner_content_payload

                try:
                    parsed = _planner_content_payload(result["audit_raw_content"])
                except Exception as exc:
                    raise DetailIntakeError(
                        "INTAKE_RAW_REPLY_CHANGED",
                        "Original intake model text cannot be parsed",
                    ) from exc
                if canonical_hash(parsed) != canonical_hash(result.get("payload")):
                    raise DetailIntakeError(
                        "INTAKE_RAW_REPLY_CHANGED",
                        "Original intake model text differs from its parsed result",
                    )
        return result

    def begin(self, job_id: str) -> None:
        if self.job_id is not None and job_id != self.job_id:
            raise DetailIntakeError(
                "INTAKE_RECEIPT_INVALID", "Intake job identity changed"
            )
        try:
            _write_once(self.path, {"binding": dict(self.binding), "job_id": job_id})
        except FileExistsError as exc:
            raise DetailIntakeError(
                "INTAKE_ALREADY_DISPATCHED",
                "This exact intake request was already dispatched",
            ) from exc

    def finish(self, result: Mapping[str, Any]) -> None:
        _write_once(
            self.path.with_suffix(".response.json"),
            {"result": dict(result), "sha256": canonical_hash(result)},
        )
        self.completed()
