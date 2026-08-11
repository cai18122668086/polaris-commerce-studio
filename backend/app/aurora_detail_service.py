"""Durable orchestration for Aurora detail-page harness sessions.

This service translates database/API events into harness commands.  It does
not choose module count, aspect ratio, current module, or repair outcome.
Those decisions remain in the frozen Skill session.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .aurora_detail_runtime import (
    AURORA_DETAIL_SKILL_ID,
    AURORA_DETAIL_VERSION,
    AuroraDetailHarnessAdapter,
    HarnessResult,
)
from .domain import JobItemStatus, JobStatus, PlanValidationStatus
from .models import (
    AuroraDetailSessionRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    utc_now,
)
from .services import canonical_hash, new_id, transition_job
from .skill_runtime import SkillManifestRegistry


class AuroraDetailServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AuroraDetailSessionService:
    def __init__(self, adapter: AuroraDetailHarnessAdapter) -> None:
        self.adapter = adapter

    def start_planning_bundle(
        self,
        session: Session,
        job: JobRecord,
        bundle: Mapping[str, Any],
    ) -> AuroraDetailSessionRecord:
        """Start the harness and compile the planner bundle when conflict-free."""

        self._require_aurora_job(job)
        existing = self.get(session, job, for_update=True, required=False)
        if existing is not None:
            return existing
        raw_input = self._mapping(bundle, "raw_input")
        started = self.adapter.start(job.id, raw_input)
        manifest = SkillManifestRegistry.bundled().get(AURORA_DETAIL_SKILL_ID)
        record = AuroraDetailSessionRecord(
            id=new_id("aurora"),
            workspace_id=job.workspace_id,
            job_id=job.id,
            revision=1,
            state=str(started.session["state"]),
            skill_version=AURORA_DETAIL_VERSION,
            skill_content_hash=manifest.content_hash,
            session_payload=started.session,
            active_request_payload=None,
        )
        session.add(record)
        if record.state == "AWAITING_CONFLICT_RESOLUTION":
            transition_job(
                job,
                JobStatus.AWAITING_CONFIRMATION,
                stage="awaiting_conflict_resolution",
                progress=12,
            )
            return record
        identity = self._mapping(bundle, "identity")
        plan = self._mapping(bundle, "plan")
        locked = self.adapter.lock_identity(job.id, record.session_payload, identity)
        compiled = self.adapter.compile_plan(job.id, locked.session, plan)
        self._apply(record, compiled)
        self._persist_plan_and_items(session, job, plan)
        transition_job(
            job,
            JobStatus.AWAITING_CONFIRMATION,
            stage="awaiting_plan_approval",
            progress=15,
        )
        return record

    def continue_after_conflicts(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
        bundle: Mapping[str, Any],
    ) -> AuroraDetailSessionRecord:
        record = self._locked_revision(session, job, expected_revision)
        if record.state != "AWAITING_IDENTITY":
            raise AuroraDetailServiceError(
                "AURORA_STATE_INVALID", "Resolved session is not awaiting identity."
            )
        locked = self.adapter.lock_identity(
            job.id, record.session_payload, self._mapping(bundle, "identity")
        )
        plan = self._mapping(bundle, "plan")
        compiled = self.adapter.compile_plan(job.id, locked.session, plan)
        self._apply(record, compiled)
        self._persist_plan_and_items(session, job, plan)
        if JobStatus(job.status) != JobStatus.AWAITING_CONFIRMATION:
            transition_job(
                job,
                JobStatus.AWAITING_CONFIRMATION,
                stage="awaiting_plan_approval",
                progress=15,
            )
        else:
            job.stage = "awaiting_plan_approval"
            job.state_version += 1
        return record

    def resolve_conflicts(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
        resolution: Mapping[str, Any],
    ) -> AuroraDetailSessionRecord:
        record = self._locked_revision(session, job, expected_revision)
        result = self.adapter.resolve_conflicts(
            job.id, record.session_payload, resolution
        )
        self._apply(record, result)
        job.stage = "planning_after_conflict_resolution"
        job.state_version += 1
        return record

    def authorize(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
        approval_text: str,
        approved_module_count: int,
        approved_aspect_ratio: str,
    ) -> AuroraDetailSessionRecord:
        record = self._locked_revision(session, job, expected_revision)
        result = self.adapter.authorize(
            job.id,
            record.session_payload,
            approval_text=approval_text,
            approved_module_count=approved_module_count,
            approved_aspect_ratio=approved_aspect_ratio,
        )
        self._apply(record, result)
        plan = session.scalar(
            select(JobPlanRecord)
            .where(JobPlanRecord.job_id == job.id)
            .order_by(JobPlanRecord.revision.desc())
            .limit(1)
            .with_for_update()
        )
        if plan is None:
            raise AuroraDetailServiceError(
                "AURORA_PLAN_MISSING", "Compiled Aurora plan is missing."
            )
        plan.confirmed_at = utc_now()
        transition_job(
            job,
            JobStatus.PROCESSING,
            stage="waiting_generation",
            progress=20,
        )
        return record

    def generate_next(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
    ) -> tuple[AuroraDetailSessionRecord, dict[str, Any]]:
        record = self._locked_revision(session, job, expected_revision)
        result, request = self.adapter.generate_next(job.id, record.session_payload)
        self._apply(record, result)
        record.active_request_payload = request
        item = self._current_item(session, job, result.session)
        item.status = JobItemStatus.RUNNING.value
        item.stage = "generating"
        item.state_version += 1
        job.stage = "generating"
        job.state_version += 1
        return record, request

    def record_candidate(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
        token: str,
        image_path: Path,
        candidate_asset_id: str,
    ) -> AuroraDetailSessionRecord:
        record = self._locked_revision(session, job, expected_revision)
        active = record.active_request_payload
        if not isinstance(active, Mapping) or active.get("token") != token:
            raise AuroraDetailServiceError(
                "AURORA_GENERATION_TOKEN_STALE", "Generation token is stale."
            )
        result = self.adapter.record_generation(
            job.id,
            record.session_payload,
            token=token,
            image_path=image_path,
        )
        self._apply(record, result)
        record.active_request_payload = None
        item = self._current_item(session, job, result.session)
        item.stage = "candidate_audit_pending"
        item.configuration = {
            **item.configuration,
            "candidate_asset_id": candidate_asset_id,
            "candidate_status": "AUDITING",
        }
        item.state_version += 1
        job.stage = "candidate_audit_pending"
        job.state_version += 1
        return record

    def audit_current(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
        judgment: Mapping[str, Any],
    ) -> AuroraDetailSessionRecord:
        record = self._locked_revision(session, job, expected_revision)
        result = self.adapter.audit_current(
            job.id, record.session_payload, judgment
        )
        self._apply(record, result)
        module_id = str(judgment.get("module_id") or "")
        item = self._item_by_key(session, job, module_id)
        if result.session["state"] in {"AUTHORIZED", "AWAITING_ASSEMBLY"}:
            item.status = JobItemStatus.SUCCEEDED.value
            item.stage = "accepted"
            item.finished_at = utc_now()
            item.configuration = {
                **item.configuration,
                "candidate_status": "ACCEPTED",
            }
        elif result.session["state"] == "REPAIR_REQUIRED":
            item.status = JobItemStatus.PENDING.value
            item.stage = "repair_required"
            item.configuration = {
                **item.configuration,
                "candidate_status": "REPAIR_REQUIRED",
            }
        elif result.session["state"] == "REPAIR_EXHAUSTED":
            item.status = JobItemStatus.FAILED.value
            item.stage = "repair_exhausted"
            item.error_code = "REPAIR_EXHAUSTED"
            item.error_message = "Automatic repair budget is exhausted."
            item.finished_at = utc_now()
            item.configuration = {
                **item.configuration,
                "candidate_status": "REJECTED",
            }
            job.stage = "repair_exhausted"
        item.state_version += 1
        job.state_version += 1
        return record

    def prepare_repair(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
        repair_plan: Mapping[str, Any],
    ) -> AuroraDetailSessionRecord:
        record = self._locked_revision(session, job, expected_revision)
        result = self.adapter.prepare_repair(
            job.id, record.session_payload, repair_plan
        )
        self._apply(record, result)
        item = self._current_item(session, job, result.session)
        item.stage = "repairing"
        item.state_version += 1
        job.stage = "repairing"
        job.state_version += 1
        return record

    def apply_user_adjustment(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
        adjustment: Mapping[str, Any],
    ) -> AuroraDetailSessionRecord:
        record = self._locked_revision(session, job, expected_revision)
        result = self.adapter.apply_user_adjustment(
            job.id, record.session_payload, adjustment
        )
        self._apply(record, result)
        item = self._item_by_key(session, job, str(adjustment.get("module_id") or ""))
        item.status = JobItemStatus.PENDING.value
        item.stage = "user_adjustment"
        item.error_code = None
        item.error_message = None
        item.finished_at = None
        item.state_version += 1
        job.stage = "waiting_generation"
        job.state_version += 1
        return record

    def assemble(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
        output_path: Path,
    ) -> AuroraDetailSessionRecord:
        record = self._locked_revision(session, job, expected_revision)
        result = self.adapter.assemble(
            job.id, record.session_payload, output_path
        )
        self._apply(record, result)
        job.stage = "long_page_audit_pending"
        job.state_version += 1
        return record

    def audit_long_page(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
        judgment: Mapping[str, Any],
    ) -> AuroraDetailSessionRecord:
        record = self._locked_revision(session, job, expected_revision)
        result = self.adapter.audit_long_page(
            job.id, record.session_payload, judgment
        )
        self._apply(record, result)
        job.stage = "awaiting_final_review"
        job.state_version += 1
        return record

    def finalize(
        self,
        session: Session,
        job: JobRecord,
        *,
        expected_revision: int,
        output_path: Path,
        approval_text: str,
    ) -> AuroraDetailSessionRecord:
        record = self._locked_revision(session, job, expected_revision)
        result = self.adapter.finalize(
            job.id,
            record.session_payload,
            output_path=output_path,
            approval_text=approval_text,
        )
        self._apply(record, result)
        try:
            manifest_payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AuroraDetailServiceError(
                "AURORA_MANIFEST_UNAVAILABLE", "Final manifest was not persisted."
            ) from exc
        record.session_payload = {
            **record.session_payload,
            "delivery_manifest": manifest_payload,
        }
        job.succeeded_item_count = job.expected_item_count
        job.failed_item_count = 0
        transition_job(job, JobStatus.COMPLETED, stage="completed", progress=100)
        return record

    def get(
        self,
        session: Session,
        job: JobRecord,
        *,
        for_update: bool = False,
        required: bool = True,
    ) -> AuroraDetailSessionRecord | None:
        statement = select(AuroraDetailSessionRecord).where(
            AuroraDetailSessionRecord.workspace_id == job.workspace_id,
            AuroraDetailSessionRecord.job_id == job.id,
        )
        if for_update:
            statement = statement.with_for_update()
        record = session.scalar(statement)
        if record is None and required:
            raise AuroraDetailServiceError(
                "AURORA_SESSION_NOT_FOUND", "Aurora detail session was not found."
            )
        return record

    def _locked_revision(
        self, session: Session, job: JobRecord, expected_revision: int
    ) -> AuroraDetailSessionRecord:
        self._require_aurora_job(job)
        record = self.get(session, job, for_update=True)
        assert record is not None
        if record.revision != expected_revision:
            raise AuroraDetailServiceError(
                "AURORA_SESSION_REVISION_CONFLICT",
                "Session changed; reload before applying this action.",
            )
        return record

    @staticmethod
    def _apply(record: AuroraDetailSessionRecord, result: HarnessResult) -> None:
        record.session_payload = result.session
        record.state = str(result.session["state"])
        record.revision += 1

    @staticmethod
    def _mapping(bundle: Mapping[str, Any], key: str) -> Mapping[str, Any]:
        value = bundle.get(key)
        if not isinstance(value, Mapping):
            raise AuroraDetailServiceError(
                "AURORA_PLANNER_BUNDLE_INVALID", f"Planner bundle lacks {key}."
            )
        return value

    @staticmethod
    def _require_aurora_job(job: JobRecord) -> None:
        settings = job.configuration.get("settings")
        if (
            job.type != "detail_pack"
            or not isinstance(settings, Mapping)
            or settings.get("market_region") != "domestic"
            or settings.get("workflow_version") != "aurora_v0.7.0"
        ):
            raise AuroraDetailServiceError(
                "AURORA_JOB_REQUIRED", "Job is not an Aurora v0.7.0 detail task."
            )

    @staticmethod
    def _persist_plan_and_items(
        session: Session, job: JobRecord, plan: Mapping[str, Any]
    ) -> None:
        modules = plan.get("modules")
        if not isinstance(modules, list) or not modules:
            raise AuroraDetailServiceError(
                "AURORA_PLAN_INVALID", "Compiled plan has no modules."
            )
        existing = session.scalar(
            select(JobPlanRecord.id).where(JobPlanRecord.job_id == job.id).limit(1)
        )
        if existing is not None:
            raise AuroraDetailServiceError(
                "AURORA_PLAN_ALREADY_EXISTS", "Aurora plan is already persisted."
            )
        session.add(
            JobPlanRecord(
                id=new_id("plan"),
                workspace_id=job.workspace_id,
                job_id=job.id,
                revision=1,
                schema_version="aurora-detail-plan-v0.7.0",
                payload=dict(plan),
                payload_hash=canonical_hash(plan),
                validation_status=PlanValidationStatus.VALID.value,
                validation_errors=[],
                validator_version="aurora-harness-v0.7.0",
                validated_at=utc_now(),
            )
        )
        for ordinal, module in enumerate(modules):
            module_id = str(module.get("id") or "")
            session.add(
                JobItemRecord(
                    id=new_id("item"),
                    workspace_id=job.workspace_id,
                    job_id=job.id,
                    item_key=module_id,
                    ordinal=ordinal,
                    status=JobItemStatus.PENDING.value,
                    stage="waiting_generation",
                    configuration={
                        "module_id": module_id,
                        "width": module.get("output", {}).get("width_px"),
                        "height": module.get("output", {}).get("height_px"),
                    },
                )
            )
        job.expected_item_count = len(modules)
        job.estimated_cost_min_micros = None
        job.estimated_cost_max_micros = None
        job.estimated_credits = len(modules)

    @staticmethod
    def _current_item(
        session: Session, job: JobRecord, payload: Mapping[str, Any]
    ) -> JobItemRecord:
        modules = payload.get("modules")
        current_index = payload.get("current_index")
        if not isinstance(modules, list) or not isinstance(current_index, int):
            raise AuroraDetailServiceError(
                "AURORA_SESSION_INVALID", "Current module is unavailable."
            )
        try:
            module_id = str(modules[current_index]["id"])
        except (IndexError, KeyError, TypeError) as exc:
            raise AuroraDetailServiceError(
                "AURORA_SESSION_INVALID", "Current module is unavailable."
            ) from exc
        return AuroraDetailSessionService._item_by_key(session, job, module_id)

    @staticmethod
    def _item_by_key(
        session: Session, job: JobRecord, item_key: str
    ) -> JobItemRecord:
        item = session.scalar(
            select(JobItemRecord)
            .where(
                JobItemRecord.workspace_id == job.workspace_id,
                JobItemRecord.job_id == job.id,
                JobItemRecord.item_key == item_key,
            )
            .with_for_update()
        )
        if item is None:
            raise AuroraDetailServiceError(
                "AURORA_JOB_ITEM_MISSING", "Current module item is missing."
            )
        return item


def aurora_detail_public_payload(
    job: JobRecord, record: AuroraDetailSessionRecord
) -> dict[str, Any]:
    """Project only user-facing decisions; never expose prompt or raw session."""

    payload = record.session_payload
    plan = payload.get("plan") if isinstance(payload.get("plan"), Mapping) else None
    strategy = (
        plan.get("output_strategy")
        if isinstance(plan, Mapping)
        and isinstance(plan.get("output_strategy"), Mapping)
        else None
    )
    facts = {
        item.get("id"): item
        for item in payload.get("input", {}).get("verified_facts", [])
        if isinstance(item, Mapping)
    }
    conflicts = []
    for conflict in payload.get("input", {}).get("source_conflicts", []):
        if not isinstance(conflict, Mapping) or conflict.get("status") != "UNRESOLVED":
            continue
        values = []
        for fact_id in conflict.get("alternative_fact_ids", []):
            fact = facts.get(fact_id)
            if isinstance(fact, Mapping):
                values.append(
                    {
                        "fact_id": fact_id,
                        "value": fact.get("text"),
                        "source": fact.get("evidence_ref"),
                    }
                )
        conflicts.append(
            {
                "conflict_id": conflict.get("id"),
                "topic": conflict.get("topic"),
                "values": values,
                "why_material": conflict.get("why_material"),
            }
        )
    output_decision = None
    storyboard: list[dict[str, Any]] = []
    merge_summary: list[str] = []
    deferred_summary: list[dict[str, Any]] = []
    campaign_dna = None
    if isinstance(strategy, Mapping) and isinstance(plan, Mapping):
        output_decision = {
            "target_platform": strategy.get("target_platform"),
            "module_count": strategy.get("module_count"),
            "module_count_candidates": strategy.get("module_count_candidates", []),
            "aspect_ratio": strategy.get("aspect_ratio", {}).get("label"),
            "dimensions": (
                f"{strategy.get('canvas_width_px')}x"
                f"{strategy.get('module_height_px')}"
            ),
            "safe_margin_px": strategy.get("safe_margin_px"),
            "slice_height_px": strategy.get("slice_height_px"),
            "verification_status": strategy.get("verification_status"),
            "module_count_rationale": strategy.get("module_count_rationale"),
            "ratio_rationale": strategy.get("ratio_rationale"),
        }
        for module in plan.get("modules", []):
            if not isinstance(module, Mapping):
                continue
            storyboard.append(
                {
                    "module_id": module.get("id"),
                    "duty": module.get("duty"),
                    "lead_conclusion": module.get("lead_conclusion"),
                    "visual_proof": module.get("visual_proof_direction"),
                    "composition_and_camera": (
                        f"{module.get('composition_family')} · "
                        f"{module.get('camera_scale')}"
                    ),
                    "text_entry": module.get("text_system", {}).get(
                        "placement_logic"
                    ),
                    "adjacency": module.get("variation_from_previous", []),
                }
            )
        merge_summary = list(strategy.get("merge_decisions", []))
        deferred_summary = [
            {
                "claim_id": item.get("claim_id"),
                "reason": item.get("rationale"),
            }
            for item in strategy.get("claim_coverage", [])
            if isinstance(item, Mapping) and item.get("disposition") == "DEFERRED"
        ]
        dna = plan.get("series_visual_dna", {})
        if isinstance(dna, Mapping):
            campaign_dna = "；".join(
                str(dna.get(key) or "")
                for key in (
                    "brand_anchor_system",
                    "palette_tokens",
                    "typography_tokens",
                    "graphic_tokens",
                    "photography_tokens",
                    "product_tokens",
                )
                if dna.get(key)
            )
    modules = []
    for module in payload.get("modules", []):
        if isinstance(module, Mapping):
            modules.append(
                {
                    "module_id": module.get("id"),
                    "order": module.get("order"),
                    "status": module.get("status"),
                    "cycle_id": module.get("cycle_id"),
                    "cycle_attempt_count": module.get("cycle_attempt_count"),
                    "residual_issues": module.get("residual_issues", []),
                }
            )
    return {
        "job_id": job.id,
        "revision": record.revision,
        "state": record.state,
        "allowed_actions": _public_allowed_actions(record.state),
        "conflict_checkpoint": (
            {"conflicts": conflicts} if conflicts else None
        ),
        "output_decision": output_decision,
        "campaign_visual_dna": campaign_dna,
        "storyboard": storyboard,
        "merge_summary": merge_summary,
        "deferred_summary": deferred_summary,
        "modules": modules,
        "long_page": payload.get("assembly"),
        "long_page_audit": payload.get("long_page_audit"),
        "manifest": payload.get("delivery_manifest"),
    }


def _public_allowed_actions(state: str) -> list[str]:
    return {
        "AWAITING_CONFLICT_RESOLUTION": ["resolve_conflicts"],
        "AWAITING_PLAN_APPROVAL": ["authorize_plan"],
        "REPAIR_EXHAUSTED": ["apply_user_adjustment"],
        "AWAITING_USER_FINAL_REVIEW": ["finalize"],
    }.get(state, [])
