"""Small actual-pixel review prompt and explicitly synthetic test projection."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .website_contract import MARKER, PROFILE

CHECKS = (
    "identity",
    "facts",
    "legibility",
    "approved_plan_fidelity",
    "composition_and_continuity",
    "proof_integrity",
)
OBSERVATIONS = (
    "ocr_text",
    "unauthorized_ocr_text",
    "forbidden_text_hits",
    "product_presence_observed",
    "planned_elements_visible",
    "planned_elements_missing",
    "visible_proof_relations",
    "content_units_observed",
    "independent_brand_logo_count",
    "independent_brand_logo_source_fidelity",
)


def request_context(information: tuple[str, ...]) -> dict[str, Any]:
    """Ordinary legacy product prose is not a website review contract."""
    try:
        value = json.loads(information[0]) if information else {}
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def prompt(context: dict[str, Any], schema: dict[str, Any]) -> str:
    return (
        """Inspect the attached real product references, both generated fixed
screen slices, and the final full 3:8 candidate canvas. Only product_reference
images establish product truth. Return WEBSITE_LEAN_V1 JSON matching the schema.
For each actual slice report six core checks: identity, facts, legibility,
approved_plan_fidelity, composition_and_continuity, proof_integrity. Each boolean
needs a distinct concrete visible observation. Inspect shape/parts/color against
the source, transcribe actual OCR, check truthful copy, visible approved selling
points, useful visual proof, composition and the intended seam. Report no numerical
aesthetic scores, headline ranks or depth-layer counts. Minor spacing or decorative
preferences are advisory. Missing product, unsupported claim, essential illegibility,
lost screen duty, misleading proof, broken geometry or a content-destroying seam
is material. Never fill an observation from the approved plan.
Preserve exact module order, canvas/slice hashes, crop boxes and contract hashes
from the context. Record artifact_binding and its same raw OCR. \
Both the joint pair checks and each screen use these same six core checks. \
A PASS cannot hide a false check or
material failure. Compare identity only within actual visible scope: full product,
identity token or no visible product, with NOT_APPLICABLE for unseen comparisons.
If an observation is unknown, audit_complete=false and describe uncertainty; it
does not authorize image repair. Brandless means zero independent logos. Only
approved copy may carry product claims; do not reproduce source watermarks.
"""
        + "\nRESPONSE_CONTRACT_JSON="
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        + "\nINPUT_JSON="
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )


def synthetic_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mock-only projection; never called for a real provider response."""
    result = deepcopy(reports)
    aliases = {
        "approved_plan_fidelity": "approved_plan_fidelity",
        "composition_and_continuity": "spatial_structure_match",
    }
    for report in result:
        report[MARKER] = PROFILE
        report["checks"] = {
            key: report["checks"][aliases.get(key, key)] for key in CHECKS
        }
        report["passed_layers"] = list(CHECKS)
        observed = report["observations"]
        report["observations"] = {key: observed[key] for key in OBSERVATIONS}
        report["observations"]["composition_observation"] = (
            "SYNTHETIC_OFFLINE_FIXTURE; no actual composition acceptance"
        )
        report["observations"]["brand_observation"] = (
            "SYNTHETIC_OFFLINE_FIXTURE; no actual brand acceptance"
        )
    return result
