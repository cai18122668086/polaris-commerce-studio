"""Round 4: closing layout, distinct proof leads, fewer-mismatch delivery and
set-audit cover confusability as a residual (job_431e1f7c9f98458ca9b01fc29d5a0c17)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import label_fidelity
from app.aurora_main_image_provider import (
    _accepted_generated_sources,
    _normalize_parallel_set_audit_payload,
)
from app.aurora_main_image_runtime import AuroraV20HarnessRunner
from app.domain import JobItemStatus, JobStatus, PlanValidationStatus
from app.execution import ExecutionCoordinator
from app.main_image_auto_start import (
    SUBMISSION_KEY,
    SUBMISSION_VERSION,
    finalize_validated_set,
)
from app.models import JobItemRecord, JobPlanRecord, JobRecord
from app.xinghe_agent import (
    FakeXingheGateway,
    PlannerCallResult,
    PlannerRequest,
)
from tests.test_aurora_main_image_quickwins import _compiled_session
from tests.test_aurora_main_image_round2 import _run_pages
from tests.test_execution_reliability import (
    WORKSPACE_ID,
    _BlockedSetAuditProvider,
    _six_succeeded_aurora_pages,
)
from tests.test_label_fidelity import REFERENCE, _MainLabelGateway

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "aurora_v20"
SAVED_SET_AUDIT = FIXTURES / "job_431e1f7c_set_audit_observation.json"


# 1a. Closing page and proof leads ------------------------------------------


def test_closing_page_is_a_flat_lay_with_the_spec_as_a_secondary_block(
    tmp_path: Path,
) -> None:
    page = _compiled_session(tmp_path)["plan"]["pages"][5]
    assert page["camera_directive"].startswith("规格平铺俯拍")
    assert "规格只作次级信息块" in page["prompt"]
    assert "不得用超大数字" in page["prompt"]


def test_no_fact_leads_two_proof_pages_and_headlines_stay_distinct(
    tmp_path: Path,
) -> None:
    pages = _compiled_session(tmp_path)["plan"]["pages"]
    proof_leads = [pages[index]["primary_claim"] for index in (2, 3, 4)]
    assert len(set(proof_leads)) == 3, proof_leads
    assert "260g 大容量" not in proof_leads
    seeds = [p["display_copy_contract"]["headline_seed_source_segment"] for p in pages]
    assert len(set(seeds)) == 6, seeds
    # A recycled fact is told which segment is its only headline.
    recycled = [
        p for p in pages if p["display_copy_contract"].get("headline_exclusive_segment")
    ]
    assert recycled
    for page in recycled:
        segment = page["display_copy_contract"]["headline_exclusive_segment"]
        assert f"【本页主标题】只用「{segment}」作主标题" in page["prompt"]


# 1c. Both drafts misprint the label: fewer mismatches wins ------------------


class _TwoBadLabelsGateway(_MainLabelGateway):
    def __init__(self, label_reads: list[list[str]]) -> None:
        super().__init__([], fail_page1_audit=True)
        self.label_reads = list(label_reads)

    async def plan(self, request: PlannerRequest) -> PlannerCallResult:
        if (
            request.planning_profile == label_fidelity.READ_PROFILE
            and ":poster-text" not in request.idempotency_key
        ):
            result = await FakeXingheGateway.plan(self, request)
            lines = self.label_reads.pop(0) if self.label_reads else list(REFERENCE)
            return replace(
                result,
                payload={"products": [{"label_lines": lines}], "other_text_lines": []},
            )
        return await super().plan(request)


def test_when_both_drafts_misprint_the_label_the_fewer_mismatches_ships(
    tmp_path: Path,
) -> None:
    one_wrong = [line.replace("精光", "精华") for line in REFERENCE]
    two_wrong = [line.replace("色淡林", "色淡斑") for line in one_wrong]
    assert one_wrong != list(REFERENCE) and two_wrong != one_wrong
    gateway = _TwoBadLabelsGateway(
        [list(REFERENCE), one_wrong, two_wrong]  # page 0, page 1 draft, repair
    )
    provider, results = _run_pages(tmp_path, gateway)  # type: ignore[arg-type]
    versions = [v for v in provider.state["generated_versions"] if v["page_index"] == 1]
    draft, repair = versions
    check = repair["post_repair_identity_check"]
    assert check["pre_repair"]["label_mismatch_count"] < check["repaired"][
        "label_mismatch_count"
    ]
    assert draft["status"] == "ACCEPTED_WITH_RESIDUALS"
    assert repair["status"] == "REJECTED_IDENTITY_REGRESSION"
    assert results[1].artifact is not None
    assert results[1].artifact.sha256 == draft["sha256"]


# 2. Cover confusability is a residual, not a failure ------------------------


def test_cover_confusability_from_the_saved_set_audit_still_finalizes(
    tmp_path: Path,
) -> None:
    provider, _ = _run_pages(tmp_path, FakeXingheGateway())  # type: ignore[arg-type]
    # Finish pages 2-5 with the same offline gateway.
    for index in range(2, 6):
        from app.provider import ProviderRequest

        asyncio.run(
            provider.execute(
                ProviderRequest(
                    workspace_id="workspace_one",
                    job_id=provider.state["request_id"],
                    job_item_id=f"item_{index}",
                    attempt_id=f"attempt_{index}",
                    operation="domestic_main_image",
                    idempotency_key=f"round4-{index}",
                    configuration={},
                )
            )
        )
    state = provider.state
    assert state["state"] == "AWAITING_SET_AUDIT"
    saved = json.loads(SAVED_SET_AUDIT.read_text(encoding="utf-8"))
    assert saved["confusable_page_indexes"] == [5]
    job_id = state["request_id"]
    sources = _accepted_generated_sources(state, job_id, tuple(range(6)))
    observation = _normalize_parallel_set_audit_payload(dict(saved), sources)
    work_root = tmp_path / "roots"
    set_dir = work_root / job_id / "sequential-v20" / "set-audit"
    set_dir.mkdir(parents=True)
    (set_dir / "session.json").write_text(json.dumps(state), encoding="utf-8")
    (set_dir / "observation.json").write_text(
        json.dumps(observation, ensure_ascii=False), encoding="utf-8"
    )
    AuroraV20HarnessRunner().run(
        "audit-set",
        set_dir,
        {
            "session": set_dir / "session.json",
            "observation": set_dir / "observation.json",
        },
    )
    audited = json.loads((set_dir / "session.json").read_text(encoding="utf-8"))
    assert audited["set_audit_passed"] is False

    added: list[Any] = []
    job = SimpleNamespace(
        id=job_id,
        workspace_id="workspace_one",
        type="domestic_main_image",
        status=JobStatus.AWAITING_FINAL_REVIEW.value,
        cancel_requested_at=None,
        configuration={
            "settings": {"auto_start_after_plan": True},
            SUBMISSION_KEY: {"version": SUBMISSION_VERSION, "actor_user_id": "usr"},
        },
    )
    plan = SimpleNamespace(
        payload={
            "execution_policy": {"execution_mode": "sequential_v20"},
            "_sequential_v20_set_session": audited,
        },
        payload_hash="",
    )
    session = SimpleNamespace(add=added.append)
    assert finalize_validated_set(session, job, plan, work_root=work_root)  # type: ignore[arg-type]
    manifest = json.loads(Path(plan.payload["final_manifest"]).read_text("utf-8"))
    assert manifest["set_audit_passed"] is False
    assert any(
        "search_role_unique" in item.get("failed_checks", [])
        for item in manifest["residual_issues_disclosed"]
    )
    assert len(manifest["pages"]) == 6


def test_blocked_set_audit_never_fails_an_automatic_job_item(
    client: TestClient,
) -> None:
    job_id = _six_succeeded_aurora_pages(client)
    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, job_id)
        assert job is not None
        job.status = JobStatus.PROCESSING.value
        job.stage = "generating"
        job.configuration = {
            **job.configuration,
            "settings": {
                **(job.configuration.get("settings") or {}),
                "auto_start_after_plan": True,
            },
            SUBMISSION_KEY: {"version": SUBMISSION_VERSION, "actor_user_id": "usr"},
        }
        session.add(
            JobPlanRecord(
                id=f"plan_{uuid4().hex}",
                workspace_id=WORKSPACE_ID,
                job_id=job_id,
                revision=1,
                payload={"execution_policy": {"execution_mode": "parallel_v20"}},
                payload_hash="0" * 64,
                validation_status=PlanValidationStatus.VALID.value,
            )
        )
        session.commit()

    coordinator = ExecutionCoordinator(
        client.app.state.session_factory,
        _BlockedSetAuditProvider(),
        worker_id="cover-confusability",
    )
    asyncio.run(coordinator.run(job_id))
    with client.app.state.session_factory() as session:
        items = session.scalars(
            select(JobItemRecord).where(JobItemRecord.job_id == job_id)
        ).all()
        assert {item.status for item in items} == {JobItemStatus.SUCCEEDED.value}
        assert not any(item.error_code == "AURORA_SET_AUDIT_FAILED" for item in items)
