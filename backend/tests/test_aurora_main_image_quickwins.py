"""Regression tests for the 2026-11-25 domestic main-image quick wins.

Facts and identity come from dev job job_9323577dd79d47348bb2079660a53c87
(24 min, 6/6 pages repaired, page 6 HARNESS_BLOCKED).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app import aurora_generation_shadow
from app.aurora_main_image_planner import AuroraPlanningError
from app.aurora_main_image_provider import (
    _AUDIT_SYSTEM_PROMPT,
    AuroraMainImageProvider,
)
from app.aurora_main_image_runtime import AuroraV20HarnessRunner
from app.config import Settings
from app.provider import ProviderArtifact, ProviderOutcome, ProviderRequest
from app.xinghe_agent import (
    FakeXingheGateway,
    PlannerCallResult,
    PlannerRequest,
    TengliOpenAICompatibleGateway,
    XingheAgentError,
)

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "aurora_v20"
    / "job_9323577_input_identity.json"
)
PRIMARY_URL = "https://primary.invalid/"
FAILOVER_URL = "https://failover.invalid/"


def _real_job() -> dict[str, Any]:
    return dict(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _compiled_session(
    tmp_path: Path, fixture: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compile the real job's input through the native v2 Harness."""

    fixture = fixture or _real_job()
    evidence_path = tmp_path / "source-01.png"
    evidence_path.write_bytes(
        (Path(__file__).resolve().parents[2] / "public" / "og.png").read_bytes()
    )
    raw = fixture["input"]
    raw["product"]["original_references"] = [str(evidence_path)]
    identity = fixture["identity"]
    for evidence in identity["evidence"]:
        evidence["path"] = str(evidence_path)
    input_path = tmp_path / "input.json"
    identity_path = tmp_path / "identity.json"
    session_path = tmp_path / "session.json"
    input_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    identity_path.write_text(json.dumps(identity, ensure_ascii=False), encoding="utf-8")
    runner = AuroraV20HarnessRunner()
    runner.run("start", tmp_path, {"input": input_path, "session": session_path})
    runner.run(
        "lock-identity", tmp_path, {"session": session_path, "identity": identity_path}
    )
    runner.run("compile", tmp_path, {"session": session_path})
    return dict(json.loads(session_path.read_text(encoding="utf-8")))


# 1. The direct-pixel reviewer receives the audit contract ------------------


class _RecordingPlannerTransport:
    def __init__(self, fail_hosts: tuple[str, ...] = ()) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_hosts = fail_hosts

    async def post_json(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        self.calls.append(kwargs)
        if any(kwargs["url"].startswith(host) for host in self.fail_hosts):
            raise XingheAgentError(
                "PROVIDER_TRANSPORT_FAILED",
                "Provider transport failed (URLError).",
                retryable=True,
            )
        return 200, {
            "id": "review",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        }


def _gateway(
    transport: _RecordingPlannerTransport, **overrides: Any
) -> TengliOpenAICompatibleGateway:
    options: dict[str, Any] = {
        "api_key": "primary-key",
        "base_url": PRIMARY_URL,
        "planner_model": "planner-test",
        "image_model": "image-test",
        "failover_enabled": True,
        "failover_api_key": "failover-key",
        "failover_base_url": FAILOVER_URL,
        "planner_timeout_seconds": 1200,
        "planner_review_timeout_seconds": 180,
        "transport": transport,
    }
    options.update(overrides)
    return TengliOpenAICompatibleGateway(**options)


def _user_text(call: dict[str, Any]) -> str:
    content = call["payload"]["messages"][1]["content"]
    return "\n".join(part["text"] for part in content if part["type"] == "text")


def test_page_review_request_carries_fact_pool_and_page_contract(
    tmp_path: Path,
) -> None:
    session = _compiled_session(tmp_path)
    page = session["plan"]["pages"][5]
    generation_request = {
        "page_index": 5,
        "page_role": page["page_role"],
        "page_contract": page,
        "campaign_constitution": {
            "product_identity": {"identity_summary": "瓶身下部可见“精光身体乳”"}
        },
        "authorized_facts": {
            "display_facts": ["260g"],
            "selling_points": session["raw_input"]["product"][
                "verified_selling_points"
            ],
        },
    }
    transport = _RecordingPlannerTransport()
    provider = AuroraMainImageProvider.__new__(AuroraMainImageProvider)
    provider.gateway = _gateway(transport)
    payload = b"candidate-pixels"
    artifact = ProviderArtifact(
        payload=payload,
        filename="page-06.png",
        content_type="image/png",
        width=1024,
        height=1024,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    request = ProviderRequest(
        workspace_id="workspace_one",
        job_id="job_review_contract",
        job_item_id="item_5",
        attempt_id="attempt_5",
        operation="domestic_main_image",
        idempotency_key="review-contract",
        configuration={"job": {"settings": {"product_name": "OLAY超白瓶美白身体乳"}}},
    )
    with pytest.raises(AuroraPlanningError):
        # The recorded reply is an empty JSON object; only the request matters.
        asyncio.run(
            provider._audit_v20_candidate(
                request,
                generation_request,
                tmp_path / "page-06.png",
                artifact,
                identity_sources=(),
            )
        )

    assert len(transport.calls) == 1
    text = _user_text(transport.calls[0])
    contract_text = text.split("audit_contract=", 1)[1]
    contract = json.loads(contract_text.split("\nSource image", 1)[0])
    assert contract["page_index"] == 5
    assert contract["authorized_fact_pool"]["all_exact_fact_seeds"] == [
        "260g",
        "烟酰胺·色淡林精华配方",
        "7天美白，一润到底",
        "浮光栀子香，精致香氛",
        "260g 大容量",
    ]
    assert contract["page_contract"]["primary_claim"] == page["primary_claim"]
    assert contract["page_contract"]["layout_contract"]["composition_archetype"] == (
        "CLOSURE_SPEC_ARCH"
    )
    assert contract["layout_observation_contract"]["composition_archetype_seen"] == (
        "CLOSURE_SPEC_ARCH"
    )
    assert "authorized_fact_pool" in text and "page_contract" in text
    assert "精光身体乳" in contract["authorized_identity_copy"][
        "label_and_package_text_source"
    ]
    assert contract["authorized_identity_copy"]["product_name"] == (
        "OLAY超白瓶美白身体乳"
    )


def test_reviewer_and_shadow_prompts_carry_no_toy_car_rules() -> None:
    shadow = aurora_generation_shadow.build_execution_semantics_prompt(
        {"page_contract": {}, "page_index": 0}
    )
    for prompt in (_AUDIT_SYSTEM_PROMPT, shadow):
        lowered = prompt.casefold()
        for term in ("wheel", "steering", "seat count", "red/black", "dashboard"):
            assert term not in lowered
    assert "character by character" in _AUDIT_SYSTEM_PROMPT


# 2. Claim allocation ------------------------------------------------------


def test_real_job_closure_page_gets_the_spec_and_proof_pages_no_text_only_lead(
    tmp_path: Path,
) -> None:
    pages = _compiled_session(tmp_path)["plan"]["pages"]
    leads = [page["primary_claim"] for page in pages]

    assert leads[0] == "7天美白，一润到底"
    # The closure page carries the spec cluster, never the search hook.
    assert leads[5] == "260g 大容量"
    assert "7天美白，一润到底" not in pages[5]["claim_bundle"]
    assert pages[5]["supporting_claims"]
    assert "260g" in pages[5]["commercial_closure"]
    # Pages that need visual proof never lead with a text-only fact.
    for index in (2, 3, 4):
        assert pages[index]["observability"] != "TEXT_ONLY_VERIFIED", leads
    # The search hook is not repeated as secondary copy on later pages.
    for page in pages[1:]:
        assert "7天美白，一润到底" not in page["claim_bundle"]
    # "260g" and "260g 大容量" are one fact: never both on one page.
    for page in pages:
        assert not {"260g", "260g 大容量"} <= set(page["claim_bundle"])


def test_proof_pages_reuse_a_renderable_fact_instead_of_a_text_only_one(
    tmp_path: Path,
) -> None:
    fixture = _real_job()
    product = fixture["input"]["product"]
    product["verified_selling_points"] = [
        "7天美白，一润到底",
        "柔滑乳液质地",
        "260g 大容量",
        "48小时保湿",
    ]
    product["user_provided_display_facts"] = ["260g"]
    pages = _compiled_session(tmp_path, fixture)["plan"]["pages"]
    for index in (2, 3, 4):
        assert pages[index]["primary_claim"] == "柔滑乳液质地"
    assert pages[5]["primary_claim"] == "260g 大容量"


# 3. Dead primary route and per-call review timeout -------------------------


def _review_request(key: str) -> PlannerRequest:
    return PlannerRequest(
        workspace_id="workspace_one",
        job_id="job_breaker",
        group_key="job_breaker:v20-audit:0",
        sources=(),
        page_count=1,
        language="zh-CN",
        product_name="Aurora v2.0 direct-pixel audit",
        product_information=(json.dumps({"page_index": 0}),),
        platform_code="TAOBAO_AURORA_V20_PIXEL_AUDIT",
        size="1024x1024",
        idempotency_key=key,
        planning_profile="aurora_v20_visual_audit",
    )


@pytest.mark.parametrize("recovery", [False, True])
def test_unreachable_primary_is_parked_instead_of_retried_every_call(
    recovery: bool,
) -> None:
    transport = _RecordingPlannerTransport(fail_hosts=(PRIMARY_URL,))
    gateway = _gateway(transport, planner_recovery_enabled=recovery)

    for index in range(5):
        result = asyncio.run(gateway.plan(_review_request(f"review-{index}")))
        assert isinstance(result, PlannerCallResult)

    primary = [call for call in transport.calls if call["url"].startswith(PRIMARY_URL)]
    failover = [
        call for call in transport.calls if call["url"].startswith(FAILOVER_URL)
    ]
    # Two consecutive connection failures open the circuit; later calls go
    # straight to the failover route.
    assert len(primary) == 2
    assert len(failover) == 5


def test_review_calls_are_capped_by_the_review_timeout() -> None:
    transport = _RecordingPlannerTransport()
    gateway = _gateway(transport, failover_enabled=False)
    asyncio.run(gateway.plan(_review_request("review-timeout")))
    identity = _review_request("identity-timeout")
    identity = replace(identity, planning_profile="aurora_identity")
    asyncio.run(gateway.plan(identity))

    assert transport.calls[0]["timeout_seconds"] == 180
    assert transport.calls[1]["timeout_seconds"] == 1200
    assert Settings().planner_review_timeout_seconds == 180


# 4. Request counting -------------------------------------------------------


class _RepairOnceGateway(FakeXingheGateway):
    """Fail the first page-0 audit on the search baseline to force a repair.

    Image results report one upstream request each, like the real gateway.
    """

    audits = 0

    async def edit(self, request: Any) -> Any:
        result = await super().edit(request)
        usage = {**(result.raw_usage or {}), "network_requests": 1}
        return replace(result, raw_usage=usage)

    async def plan(self, request: PlannerRequest) -> PlannerCallResult:
        result = await super().plan(request)
        if request.planning_profile == "aurora_v20_visual_audit":
            self.audits += 1
            if self.audits == 1 and isinstance(result.payload, dict):
                payload = dict(result.payload)
                payload["observations"] = {
                    **payload["observations"],
                    "type_roles_seen": 3,
                    "commercial_closure_visible": False,
                }
                return PlannerCallResult(**{**result.__dict__, "payload": payload})
        return result


def test_repaired_page_counts_both_image_calls(tmp_path: Path) -> None:
    session = _compiled_session(tmp_path)
    session_path = tmp_path / "session.json"
    AuroraV20HarnessRunner().run(
        "authorize",
        tmp_path,
        {"session": session_path, "approval-text": "确认六图规划并授权生成"},
    )
    session = json.loads(session_path.read_text(encoding="utf-8"))
    job_id = session["request_id"]

    class MemoryProvider(AuroraMainImageProvider):
        state = session

        def _load_authorized_context(self, request):  # type: ignore[no-untyped-def]
            del request
            return SimpleNamespace(ordinal=0), dict(self.state)

        def _persist_session(self, job_id, harness_session):  # type: ignore[no-untyped-def]
            del job_id
            self.state = dict(harness_session)

    gateway = _RepairOnceGateway()
    provider = MemoryProvider(
        session_factory=None,  # type: ignore[arg-type]
        gateway=gateway,
        storage=None,  # type: ignore[arg-type]
        work_root=tmp_path / "work",
        execution_mode="sequential_v20",
    )
    result = asyncio.run(
        provider.execute(
            ProviderRequest(
                workspace_id="workspace_one",
                job_id=job_id,
                job_item_id="item_0",
                attempt_id="attempt_0",
                operation="domestic_main_image",
                idempotency_key="count-0",
                configuration={},
            )
        )
    )

    assert result.outcome == ProviderOutcome.SUCCEEDED, result.error_message
    assert len(gateway.image_calls) == 2
    assert gateway.audits == 2
    assert result.raw_usage is not None
    assert result.raw_usage["network_requests"] == 4
