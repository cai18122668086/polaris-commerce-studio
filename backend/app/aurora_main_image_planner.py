"""Durable first approval checkpoint for the Aurora six-image workflow."""

from __future__ import annotations

import json
from tempfile import TemporaryDirectory

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .aurora_main_image_runtime import (
    AURORA_MAIN_IMAGE_VERSION,
    AuroraHarnessRunner,
    write_contract,
)
from .domain import JobStatus, PlanValidationStatus
from .models import AuditEventRecord, JobPlanRecord, JobRecord, utc_now
from .services import canonical_hash, new_id, transition_job

PAGE_ROLES = (
    "SEARCH_MAIN_IMAGE_LISTING_COVER",
    "CAROUSEL_IDENTITY_HERO",
    "CAROUSEL_CORE_FEATURE_PROOF",
    "CAROUSEL_SCENE_OR_OPERATION",
    "CAROUSEL_DETAIL_OR_TRUST",
    "CAROUSEL_OFFER_OR_SPEC_CLOSURE",
)


class AuroraMainImagePlanner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        harness: AuroraHarnessRunner | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.harness = harness or AuroraHarnessRunner()

    async def plan(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            existing = session.scalar(
                select(JobPlanRecord.id).where(JobPlanRecord.job_id == job.id).limit(1)
            )
            if existing is not None:
                return JobStatus(job.status)
            configuration = (
                job.configuration if isinstance(job.configuration, dict) else {}
            )
            input_value = configuration.get("input", {})
            settings = configuration.get("settings", {})
            asset_ids = list(input_value.get("product_asset_ids", []))
            facts = list(settings.get("selling_points", []))
            raw = {
                "request_id": job.id,
                "profile01_semantics_read": False,
                "product": {
                    "name": settings.get("product_name", ""),
                    "category": settings.get("category", ""),
                    "original_references": asset_ids,
                    "verified_selling_points": facts,
                    "verified_attributes": settings.get("product_attributes", []),
                    "verified_scenes": settings.get("scenes", []),
                    "verified_offers": settings.get("offers", []),
                    "verified_service_or_trust_facts": settings.get(
                        "service_or_trust_facts", []
                    ),
                },
            }
            with TemporaryDirectory(prefix="polaris-aurora-plan-") as temporary:
                from pathlib import Path

                workspace = Path(temporary)
                input_path = workspace / "input.json"
                session_path = workspace / "session.json"
                write_contract(input_path, raw)
                self.harness.run(
                    "start",
                    workspace,
                    {"input": input_path, "session": session_path},
                )
                harness_session = json.loads(session_path.read_text(encoding="utf-8"))

            pages = []
            for ordinal, role in enumerate(PAGE_ROLES):
                fact = facts[min(ordinal, len(facts) - 1)]
                pages.append(
                    {
                        "page_index": ordinal,
                        "page_role": role,
                        "headline": fact,
                        "visual_duty": _visual_duty(role),
                        "source_asset_ids": asset_ids,
                        "status": "awaiting_plan_approval",
                    }
                )
            payload = {
                "schema_version": "aurora-main-image-plan-v1",
                "skill_id": "aurora-domestic-ecommerce-main-image",
                "skill_version": AURORA_MAIN_IMAGE_VERSION,
                "approval_checkpoint": "six_page_plan",
                "product": {
                    "name": settings.get("product_name"),
                    "category": settings.get("category"),
                },
                "pages": pages,
                "harness_session": harness_session,
                "execution_policy": {
                    "sequence": "strictly_sequential",
                    "max_automatic_repairs_per_page": 1,
                    "final_set_approval_required": True,
                },
            }
            plan = JobPlanRecord(
                id=new_id("plan"),
                workspace_id=job.workspace_id,
                job_id=job.id,
                revision=1,
                schema_version="aurora-main-image-plan-v1",
                payload=payload,
                payload_hash=canonical_hash(payload),
                validation_status=PlanValidationStatus.VALID.value,
                validation_errors=[],
                validator_version=f"aurora-harness-{AURORA_MAIN_IMAGE_VERSION}",
                validated_at=utc_now(),
            )
            session.add(plan)
            session.add(
                AuditEventRecord(
                    workspace_id=job.workspace_id,
                    action="aurora.plan_created",
                    resource_type="job",
                    resource_id=job.id,
                    request_id=plan.id,
                    details={
                        "page_count": 6,
                        "harness_state": harness_session["state"],
                    },
                )
            )
            transition_job(
                job,
                JobStatus.AWAITING_CONFIRMATION,
                stage="awaiting_plan_confirmation",
                progress=15,
            )
            session.commit()
            return JobStatus.AWAITING_CONFIRMATION


def _visual_duty(role: str) -> str:
    return {
        "SEARCH_MAIN_IMAGE_LISTING_COVER": "缩略图中快速识别商品与核心购买理由",
        "CAROUSEL_IDENTITY_HERO": "建立商品身份与整套视觉世界",
        "CAROUSEL_CORE_FEATURE_PROOF": "用可见证据证明核心卖点",
        "CAROUSEL_SCENE_OR_OPERATION": "呈现真实使用场景或操作方式",
        "CAROUSEL_DETAIL_OR_TRUST": "展示细节、材质或可信依据",
        "CAROUSEL_OFFER_OR_SPEC_CLOSURE": "用规格、权益或服务完成决策闭环",
    }[role]
