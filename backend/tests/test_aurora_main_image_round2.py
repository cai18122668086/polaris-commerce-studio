"""Round-2 regression tests: copy policy, repair identity gate, deadlines,
shared route parking and per-page camera directives."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app import xinghe_agent
from app.aurora_main_image_provider import AuroraMainImageProvider
from app.aurora_main_image_runtime import AuroraV20HarnessRunner
from app.provider import ProviderArtifact, ProviderOutcome, ProviderRequest
from app.xinghe_agent import (
    PLANNER_ROUTE_BREAKER,
    FakeXingheGateway,
    PlannerCallResult,
    PlannerRequest,
    PlannerRouteCircuitBreaker,
)
from tests.test_aurora_main_image_quickwins import (
    FAILOVER_URL,
    PRIMARY_URL,
    _compiled_session,
    _gateway,
    _RecordingPlannerTransport,
    _review_request,
    _user_text,
)

# 1. One copy policy for generation and review ------------------------------


def test_generation_prompt_and_review_contract_share_one_copy_policy(
    tmp_path: Path,
) -> None:
    session = _compiled_session(tmp_path)
    pages = session["plan"]["pages"]
    policy = pages[0]["copy_policy"]
    assert "逐字还原" in policy and "新品上市" in policy and "密集美白" in policy
    for page in pages:
        assert page["copy_policy"] == policy
        assert policy in page["prompt"]
        assert "均可直接使用" not in page["prompt"]
        assert "【商品名】OLAY超白瓶美白身体乳" in page["prompt"]

    transport = _RecordingPlannerTransport()
    provider = AuroraMainImageProvider.__new__(AuroraMainImageProvider)
    provider.gateway = _gateway(transport)
    payload = b"candidate"
    artifact = ProviderArtifact(
        payload=payload,
        filename="page.png",
        content_type="image/png",
        width=1024,
        height=1024,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    generation_request = {
        "page_index": 2,
        "page_role": pages[2]["page_role"],
        "page_contract": {k: v for k, v in pages[2].items() if k != "prompt"},
    }
    with pytest.raises(Exception):  # noqa: B017 - only the request matters
        asyncio.run(
            provider._audit_v20_candidate(
                ProviderRequest(
                    workspace_id="w",
                    job_id="job_copy_policy",
                    job_item_id="i",
                    attempt_id="a",
                    operation="domestic_main_image",
                    idempotency_key="k",
                    configuration={},
                ),
                generation_request,
                tmp_path / "page.png",
                artifact,
                identity_sources=(),
            )
        )
    text = _user_text(transport.calls[0])
    contract_text = text.split("audit_contract=", 1)[1]
    contract = json.loads(contract_text.split("\nSource image")[0])
    assert contract["copy_policy"] == policy
    system = transport.calls[0]["payload"]["messages"][0]["content"]
    assert "identity copy" in system and "copy_policy" in system


# 6. Camera directives -----------------------------------------------------


def test_each_page_gets_its_own_camera_directive(tmp_path: Path) -> None:
    pages = _compiled_session(tmp_path)["plan"]["pages"]
    directives = [page["camera_directive"] for page in pages]
    assert len(set(directives)) == 6
    assert directives[0].startswith("正面") and directives[1].startswith("三分之四")
    assert directives[5].startswith("规格平铺")
    for page in pages:
        assert "【镜头】" + page["camera_directive"] in page["prompt"]


# 2 + 3. Repair identity gate instead of a second full review ---------------


class _Page1RepairGateway(FakeXingheGateway):
    """Pass page 0, fail page 1's first audit, and script the repair check."""

    def __init__(self, *, repaired_label_exact: bool) -> None:
        super().__init__()
        self.repaired_label_exact = repaired_label_exact
        self.audits_by_page: dict[int, int] = {}
        self.repair_checks: list[PlannerRequest] = []

    async def edit(self, request: Any) -> Any:
        result = await super().edit(request)
        # Distinct pixels per call so the draft and its repair differ.
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        shade = (len(self.image_calls) * 37) % 255
        Image.new("RGB", (1024, 1024), (shade, 120, 90)).save(buffer, format="PNG")
        data = buffer.getvalue()
        artifact = replace(
            result.artifact,
            payload=data,
            sha256=hashlib.sha256(data).hexdigest(),
            content_type="image/png",
        )
        usage = {**(result.raw_usage or {}), "network_requests": 1}
        return replace(result, artifact=artifact, raw_usage=usage)

    async def plan(self, request: PlannerRequest) -> PlannerCallResult:
        result = await super().plan(request)
        if request.planning_profile == "aurora_repair_identity_check":
            self.repair_checks.append(request)
            payload = dict(result.payload or {})
            seen = "精光身体乳" if self.repaired_label_exact else "精华身体乳"
            payload["repaired"] = {
                **payload["repaired"],
                "label_exact": self.repaired_label_exact,
                "label_text_seen": seen,
            }
            return replace(result, payload=payload)
        if request.planning_profile != "aurora_v20_visual_audit":
            return result
        page = request.page_count - 1
        self.audits_by_page[page] = self.audits_by_page.get(page, 0) + 1
        if page == 1 and self.audits_by_page[page] == 1:
            payload = dict(result.payload or {})
            checks = [dict(item) for item in payload["checks"]]
            for item in checks:
                if item["name"] == "factual_copy_match":
                    item.update(passed=False, score=40)
            payload["checks"] = checks
            payload["all_material_deficiencies"] = [
                {
                    "check": "factual_copy_match",
                    "visible_problem": "画面出现未授权角标“新品上市”",
                    "root_cause": "沿用了原海报角标",
                    "required_change": "删除“新品上市”角标",
                }
            ]
            return replace(result, payload=payload)
        return result


def _run_pages(
    tmp_path: Path,
    gateway: _Page1RepairGateway,
    configuration: dict[str, Any] | None = None,
) -> tuple[Any, list[Any]]:
    _compiled_session(tmp_path)
    session_path = tmp_path / "session.json"
    AuroraV20HarnessRunner().run(
        "authorize",
        tmp_path,
        {"session": session_path, "approval-text": "确认六图规划并授权生成"},
    )
    session = json.loads(session_path.read_text(encoding="utf-8"))

    class MemoryProvider(AuroraMainImageProvider):
        state = session

        def _load_authorized_context(self, request):  # type: ignore[no-untyped-def]
            del request
            return SimpleNamespace(ordinal=len(self.state["accepted_pages"])), dict(
                self.state
            )

        def _persist_session(self, job_id, harness_session):  # type: ignore[no-untyped-def]
            del job_id
            self.state = dict(harness_session)

    provider = MemoryProvider(
        session_factory=None,  # type: ignore[arg-type]
        gateway=gateway,
        storage=None,  # type: ignore[arg-type]
        work_root=tmp_path / "work",
        execution_mode="sequential_v20",
    )
    results = []
    for index in range(2):
        results.append(
            asyncio.run(
                provider.execute(
                    ProviderRequest(
                        workspace_id="workspace_one",
                        job_id=session["request_id"],
                        job_item_id=f"item_{index}",
                        attempt_id=f"attempt_{index}",
                        operation="domestic_main_image",
                        idempotency_key=f"round2-{index}",
                        configuration=configuration or {},
                    )
                )
            )
        )
    return provider, results


def test_repaired_page_gets_identity_check_instead_of_second_full_review(
    tmp_path: Path,
) -> None:
    gateway = _Page1RepairGateway(repaired_label_exact=True)
    provider, results = _run_pages(tmp_path, gateway)

    assert all(r.outcome == ProviderOutcome.SUCCEEDED for r in results)
    assert gateway.audits_by_page == {0: 1, 1: 1}
    assert len(gateway.repair_checks) == 1
    # Draft and repair share one check call with the product references.
    check_sources = gateway.repair_checks[0].sources
    assert [s.source_role for s in check_sources[-2:]] == [
        "generated_candidate",
        "generated_candidate",
    ]
    # Repair generation received the canvas plus the product reference and
    # a label lock instead of a Python repr of the repair plan.
    repair_call = gateway.image_calls[-1]
    assert len(repair_call.sources) == 2
    assert "【返修标签锁定】" in repair_call.prompt
    assert "{'scope'" not in repair_call.prompt
    page_one = results[1]
    assert page_one.artifact is not None
    state = provider.state
    delivered = [
        v
        for v in state["generated_versions"]
        if v["page_index"] == 1 and v["status"] == "ACCEPTED_WITH_RESIDUALS"
    ]
    assert delivered[-1]["sha256"] == page_one.artifact.sha256
    assert delivered[-1]["revision"] == 1
    assert state["accepted_pages"] == [0, 1]
    # 2 images + 1 full review + 1 identity check (+1 style calibration).
    assert page_one.raw_usage is not None
    assert page_one.raw_usage["network_requests"] == 5


def test_repair_that_damages_the_label_delivers_the_pre_repair_draft(
    tmp_path: Path,
) -> None:
    gateway = _Page1RepairGateway(repaired_label_exact=False)
    provider, results = _run_pages(tmp_path, gateway)

    page_one = results[1]
    assert page_one.outcome == ProviderOutcome.SUCCEEDED
    versions = [v for v in provider.state["generated_versions"] if v["page_index"] == 1]
    draft, repair = versions
    assert repair["status"] == "REJECTED_IDENTITY_REGRESSION"
    assert draft["status"] == "ACCEPTED_WITH_RESIDUALS"
    assert page_one.artifact is not None
    assert page_one.artifact.sha256 == draft["sha256"]
    residual = provider.state["residual_issues"][-1]
    assert residual["page_index"] == 1 and "返修前版本" in residual["decision_summary"]
    excluded = {item["sha256"] for item in provider.state["excluded_generated_assets"]}
    assert repair["sha256"] in excluded and draft["sha256"] not in excluded


# 4. Deadlines and route parking --------------------------------------------


class _SlowTransport(_RecordingPlannerTransport):
    async def post_json(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        if kwargs["url"].startswith(PRIMARY_URL):
            self.calls.append(kwargs)
            await asyncio.sleep(5)
        return await super().post_json(**kwargs)


def test_review_call_has_a_true_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xinghe_agent, "_PLANNER_DEADLINE_GRACE_SECONDS", 0.0)
    transport = _SlowTransport()
    gateway = _gateway(transport, planner_review_timeout_seconds=0.2)
    started = time.monotonic()
    asyncio.run(gateway.plan(_review_request("deadline")))
    elapsed = time.monotonic() - started

    assert elapsed < 2
    assert transport.calls[-1]["url"].startswith(FAILOVER_URL)


class _Http502Transport(_RecordingPlannerTransport):
    async def post_json(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        if kwargs["url"].startswith(PRIMARY_URL):
            self.calls.append(kwargs)
            return 502, {"error": {"message": "bad gateway"}}
        return await super().post_json(**kwargs)


@pytest.mark.parametrize("recovery", [False, True])
def test_upstream_502_fails_over_at_once_and_parks_the_route(recovery: bool) -> None:
    transport = _Http502Transport()
    gateway = _gateway(transport, planner_recovery_enabled=recovery)
    for index in range(4):
        asyncio.run(gateway.plan(_review_request(f"502-{index}")))
    primary = [c for c in transport.calls if c["url"].startswith(PRIMARY_URL)]
    failover = [c for c in transport.calls if c["url"].startswith(FAILOVER_URL)]
    assert len(primary) == 2
    assert len(failover) == 4


class _DictStore:
    """Minimal Redis stand-in shared by two breaker instances (two workers)."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def incr(self, name: str) -> int:
        self.values[name] = int(self.values.get(name, 0)) + 1
        return int(self.values[name])

    def expire(self, name: str, time: int) -> bool:
        del time
        return True

    def set(self, name: str, value: str, ex: int | None = None) -> bool:
        del ex
        self.values[name] = value
        return True

    def exists(self, *names: str) -> int:
        return sum(name in self.values for name in names)

    def delete(self, *names: str) -> int:
        return sum(self.values.pop(name, None) is not None for name in names)


def test_route_parking_is_shared_across_worker_processes() -> None:
    store = _DictStore()
    worker_a = PlannerRouteCircuitBreaker()
    worker_b = PlannerRouteCircuitBreaker()
    worker_a.configure_store(store)
    worker_b.configure_store(store)
    route = SimpleNamespace(planner_base_url=PRIMARY_URL, planner_api_key="k")

    worker_a.record_failure(route)  # type: ignore[arg-type]
    worker_b.record_failure(route)  # type: ignore[arg-type]
    assert worker_a.is_open(route)  # type: ignore[arg-type]
    assert worker_b.is_open(route)  # type: ignore[arg-type]
    worker_b.record_success(route)  # type: ignore[arg-type]
    assert not worker_a.is_open(route)  # type: ignore[arg-type]
    assert PLANNER_ROUTE_BREAKER is not worker_a
