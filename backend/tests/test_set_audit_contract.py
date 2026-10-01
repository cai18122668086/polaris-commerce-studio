import asyncio
import copy
import json
from types import SimpleNamespace

import jsonschema
import pytest

from app.aurora_main_image_provider import (
    _normalize_parallel_set_audit_payload,
    _v20_gateway_error,
)
from app.aurora_set_audit_contract import CHECK_NAMES, json_schema
from app.xinghe_agent import PlannerRequest, TengliOpenAICompatibleGateway


def contract():
    return {
        "checks": [
            {
                "check_name": name,
                "status": "PASS",
                "pixel_evidence": f"Visible composition on page {index}.",
            }
            for index, name in enumerate(CHECK_NAMES)
        ],
        "identified_search_page_index": 0,
        "search_role_is_unique": True,
        "confusable_page_indexes": [],
        "search_identification_evidence": "Page zero alone has a cover hierarchy.",
        "carousel_distinctions": [
            {
                "page_index": n,
                "why_not_search_cover": f"Page {n} shows a focused feature.",
            }
            for n in range(1, 6)
        ],
    }


def normalize(payload):
    return _normalize_parallel_set_audit_payload(
        payload, [SimpleNamespace(sha256=str(n)) for n in range(6)]
    )


def test_strict_contract_and_per_page_aliases():
    payload = contract()
    jsonschema.validate(payload, json_schema())
    assert normalize(copy.deepcopy(payload))["search_role_is_unique"] is True
    for check in payload["checks"]:
        check["required_check_name"] = check.pop("check_name")
        check["result"] = check.pop("status")
    assert normalize(payload)["search_role_is_unique"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "unknown",
        "duplicate",
        "no_evidence",
        "aggregate_aliases",
        "ambiguous_name",
    ],
)
def test_unsupported_or_incomplete_contract_is_protocol_error(mutation):
    payload = contract()
    if mutation == "missing":
        payload["checks"].pop()
    elif mutation == "unknown":
        payload["checks"][3]["status"] = "UNKNOWN"
    elif mutation == "duplicate":
        payload["checks"][3] = payload["checks"][2]
    elif mutation == "no_evidence":
        payload["carousel_distinctions"][2]["why_not_search_cover"] = ""
    elif mutation == "ambiguous_name":
        payload["checks"][0]["required_check_name"] = CHECK_NAMES[1]
    else:
        payload["checks"] = [
            {
                "required_check_name": name,
                "result": "PASS",
                "evidence": "Aggregate evidence",
            }
            for name in (
                CHECK_NAMES[0],
                "pages_1_through_5_are_not_search_listing_covers",
                "single_cover_role_is_visually_unique",
                "set_role_distinction",
            )
        ]
    with pytest.raises(ValueError):
        normalize(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "failed_page",
        "contradictory_status",
        "other_cover",
        "confusable",
    ],
)
def test_pass_summary_never_overrides_negative_evidence(mutation):
    payload = contract()
    if mutation == "failed_page":
        payload["checks"][3]["status"] = "FAIL"
    elif mutation == "contradictory_status":
        payload["checks"][3]["result"] = "FAIL"
    elif mutation == "other_cover":
        payload["search_listing_cover_page_index"] = 4
    else:
        payload["confusable_page_indexes"] = [2]
    assert normalize(payload)["search_role_is_unique"] is False


def test_self_reported_non_unique_cannot_veto_consistent_checks():
    """``search_role_is_unique`` is derived, not an independent veto.

    Production six-page audits returned six PASS checks, an identified search
    page index of 0 and no confusable pages, yet the model also filled
    ``search_role_is_unique`` with ``false``.  The boolean is recomputed from
    the per-page checks, so the consistent evidence must win and the set must
    pass instead of failing and blocking its archive download.
    """

    payload = contract()
    payload["search_role_is_unique"] = False
    assert normalize(payload)["search_role_is_unique"] is True


def test_check_less_audit_still_fails_closed_without_checks():
    """Dropping that veto must not weaken the protocol guard.

    A payload without the six per-page checks cannot be derived at all: the
    evidence validator rejects it as a protocol error instead of letting the
    model's own ``search_role_is_unique`` value through.
    """

    payload = contract()
    payload.pop("checks")
    payload["search_role_is_unique"] = False
    with pytest.raises(ValueError):
        normalize(payload)


def test_explicit_negative_signals_still_force_failure():
    """The remaining explicit negatives keep failing after the veto is gone."""

    payload = contract()
    payload["search_role_is_unique"] = False
    payload["page_0_alone_is_search_listing_cover"] = False
    assert normalize(payload)["search_role_is_unique"] is False


@pytest.mark.parametrize(
    "content,finish",
    [("", "stop"), ("not JSON SECRET", "stop"), ('{"checks": [', "length")],
)
def test_gateway_protocol_diagnostics_are_bounded_and_private(content, finish):
    class Transport:
        async def post_json(self, **kwargs):
            assert kwargs["payload"]["response_format"]["json_schema"]["strict"] is True
            return 200, {
                "choices": [{"finish_reason": finish, "message": {"content": content}}]
            }

    gateway = TengliOpenAICompatibleGateway(
        api_key="placeholder",
        base_url="https://fixture.invalid",
        planner_model="fixture",
        image_model="fixture",
        transport=Transport(),
        diagnostic_content_sample=True,
    )
    result = asyncio.run(
        gateway.plan(
            PlannerRequest(
                workspace_id="ws_test",
                job_id="job_test",
                group_key="set",
                sources=(),
                page_count=6,
                language="zh-CN",
                product_name="test",
                product_information=(),
                platform_code="TAOBAO",
                size="1024x1024",
                idempotency_key="fixture",
                planning_profile="aurora_set_audit",
            )
        )
    )
    assert result.error_code is not None
    error = _v20_gateway_error(result, "Set review protocol error")
    diagnostics = error.aurora_gateway_diagnostics
    assert diagnostics["provider_envelope"]["finish_reason"] == finish
    assert "SECRET" not in json.dumps(diagnostics)
    assert "content_sample_head" not in diagnostics


@pytest.mark.parametrize(
    "key,value",
    [
        ("identified_search_page_index", False),
        ("search_role_is_unique", "PASS"),
        ("confusable_page_indexes", None),
    ],
)
def test_unknown_top_level_verdict_cannot_be_inferred_as_pass(key, value):
    payload = contract()
    payload[key] = value
    with pytest.raises(ValueError):
        normalize(payload)
