from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.aurora_detail_runtime import normalize_native_plan_for_harness

CASES = json.loads(
    (Path(__file__).parent / "fixtures/domestic_detail/deferred_claim_cases.json")
    .read_text(encoding="utf-8")
)["cases"]


def claim_plan(claim: dict) -> dict:
    return {
        "modules": [
            {"id": "M01", "lead_claim_id": "F01", "supporting_claim_ids": ["F02"]}
        ],
        "output_strategy": {"claim_coverage": [deepcopy(claim)]},
    }


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case"])
def test_characterize_deferred_reason_overwrite(case: dict) -> None:
    """Record the observed defect before the separate extraction and fix."""
    plan = claim_plan(case["claim"])
    before = deepcopy(plan)
    normalized = normalize_native_plan_for_harness(plan)
    claim = normalized["output_strategy"]["claim_coverage"][0]
    assert claim["disposition"] == "DEFERRED"
    assert claim["defer_reason_code"] == "NOT_DEFERRED"
    assert claim["module_ids"] == []
    assert plan == before
    assert normalize_native_plan_for_harness(normalized) == normalized


@pytest.mark.parametrize("disposition,claim_id", [
    ("LEAD", "F01"), ("SUPPORT", "F02"), ("CONTEXT_ONLY", "F02"),
])
def test_explicit_selected_claims_preserve_their_contract(
    disposition: str, claim_id: str,
) -> None:
    claim = {
        "claim_id": claim_id, "disposition": disposition,
        "module_ids": ["M01"], "rationale": "A verified fact supports this screen.",
        "defer_reason_code": "NOT_DEFERRED",
    }
    normalized = normalize_native_plan_for_harness(claim_plan(claim))
    assert normalized["output_strategy"]["claim_coverage"] == [claim]
