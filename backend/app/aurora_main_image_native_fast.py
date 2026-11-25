"""Original v20 compiler and prompts with the separate trimmed Skill runtime."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from jsonschema import Draft202012Validator
from sqlalchemy import select

from . import aurora_main_image_authored as authored
from .aurora_main_image_planner import (
    _IDENTITY_SYSTEM_PROMPT,
    PAGE_ROLES,
    AuroraMainImagePlanner,
    AuroraPlanningError,
    _all_facts,
    _bind_identity_evidence,
    _build_raw,
    _load_json,
    _public_v20_plan_payload,
)
from .aurora_main_image_runtime import AuroraHarnessRunner, write_contract
from .config import default_skill_root
from .domain import JobStatus, PlanValidationStatus
from .models import (
    AssetRecord,
    JobAssetRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    utc_now,
)
from .new_detail_skill_provider import BundledSkillManifestValidator
from .planner_recovery import summary, total_cost
from .services import canonical_hash, get_ready_assets, new_id, transition_job
from .xinghe_agent import (
    PlannerRequest,
    _aurora_identity_json_schema,
    _planner_call_results,
    _planner_usage_record,
)

VERSION = "aurora-main-image-native-fast-v1"
SCHEMA_VERSION = "aurora-main-image-native-fast-plan-v1"
SKILL_ID = "aurora-domestic-ecommerce-main-image-native-fast"
# Plans executed by the fast pipeline: the retained native-compiler plan and
# the one-pass authored plan (the default for new tasks).
FAST_PLAN_SCHEMAS = frozenset({SCHEMA_VERSION, authored.SCHEMA_VERSION})
PROFILE = "aurora_native_fast_identity"


@dataclass(frozen=True)
class NativeFastHarnessRunner(AuroraHarnessRunner):
    skill_root: Path = default_skill_root(SKILL_ID)
    command_arguments: ClassVar[dict[str, frozenset[str]]] = {
        "start": frozenset({"input", "session"}),
        "lock-identity": frozenset({"session", "identity"}),
        "compile": frozenset({"session", "plan"}),
        "authorize": frozenset({"session", "approval-text"}),
        "generate-next": frozenset({"session", "out"}),
        "record-generation": frozenset({"session", "token", "image"}),
        "finalize": frozenset({"session", "output", "approval-text"}),
        "inspect": frozenset({"session"}),
    }

    def run(self, command: str, workspace: Path, arguments: Any) -> dict[str, Any]:
        BundledSkillManifestValidator(
            source_roots={SKILL_ID: self.skill_root}
        ).validate(SKILL_ID)
        return super().run(command, workspace, arguments)


def public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Expose the original concise plan without executable prompts or paths."""
    public = {
        key: value
        for key, value in payload.items()
        if not key.startswith("_")
        and key not in {"user_facts", "source_bindings", "style_lock"}
    }
    public["pages"] = [
        {
            key: page.get(key)
            for key in (
                "page_index",
                "page_role",
                "main_selling_point",
                "supporting_selling_points",
                "visual_proof",
                "composition_and_subject",
                "reading_path_and_type_hierarchy",
                "non_repetition_reason",
                "commercial_closure",
                "status",
            )
        }
        for page in payload["pages"]
    ]
    return public


def _validate_authored_plan(plan: JobPlanRecord, job: JobRecord) -> None:
    payload = plan.payload
    ids = job.configuration.get("input", {}).get("product_asset_ids", [])
    if (
        job.configuration.get("settings", {}).get("main_image_speed") != "native_fast"
        or payload.get("version") != authored.VERSION
        or payload.get("skill_id") != authored.REFERENCE_ID
        or payload.get("canvas") != list(authored.CANVAS)
        or payload.get("product_asset_ids") != ids
        or canonical_hash(payload) != plan.payload_hash
        or not isinstance(payload.get("product_identity_lock"), dict)
        or not isinstance(payload.get("style_lock"), dict)
        or len(payload.get("pages", [])) != 6
    ):
        raise AuroraPlanningError("Main image plan version or identity binding changed")
    pages = payload["pages"]
    if [p.get("page_index") for p in pages] != list(range(6)) or [
        p.get("page_role") for p in pages
    ] != list(PAGE_ROLES):
        raise AuroraPlanningError("Main image plan must preserve all six page duties")
    for page in pages:
        if (
            not isinstance(page.get("prompt"), str)
            or not page["prompt"].strip()
            or not page.get("source_asset_ids")
            or not set(page["source_asset_ids"]).issubset(ids)
            or len(page["source_asset_ids"]) != len(set(page["source_asset_ids"]))
            or hashlib.sha256(page["prompt"].encode()).hexdigest()
            != page.get("prompt_sha256")
        ):
            raise AuroraPlanningError("Main image frozen prompt or references changed")
    if authored.reference_bundle()[1] != payload.get("skill_content_hash"):
        raise AuroraPlanningError("Main image planning references changed")


def validate_plan(plan: JobPlanRecord, job: JobRecord) -> None:
    if plan.schema_version == authored.SCHEMA_VERSION:
        _validate_authored_plan(plan, job)
        return
    payload = plan.payload
    ids = job.configuration.get("input", {}).get("product_asset_ids", [])
    if (
        job.configuration.get("settings", {}).get("main_image_speed") != "native_fast"
        or plan.schema_version != SCHEMA_VERSION
        or payload.get("version") != VERSION
        or payload.get("skill_id") != SKILL_ID
        or payload.get("canvas") != [1024, 1024]
        or payload.get("product_asset_ids") != ids
        or canonical_hash(payload) != plan.payload_hash
        or not isinstance(payload.get("product_identity_lock"), dict)
        or not isinstance(payload.get("style_lock"), dict)
        or len(payload.get("pages", [])) != 6
    ):
        raise AuroraPlanningError(
            "Native fast plan version or identity binding changed"
        )
    pages = payload["pages"]
    if [p.get("page_index") for p in pages] != list(range(6)) or [
        p.get("page_role") for p in pages
    ] != list(PAGE_ROLES):
        raise AuroraPlanningError("Native fast plan must preserve all six page duties")
    for page in pages:
        if (
            not isinstance(page.get("prompt"), str)
            or not page["prompt"].strip()
            or not page.get("source_asset_ids")
            or not set(page["source_asset_ids"]).issubset(ids)
            or len(page["source_asset_ids"]) != len(set(page["source_asset_ids"]))
            or hashlib.sha256(page["prompt"].encode()).hexdigest()
            != page.get("prompt_sha256")
        ):
            raise AuroraPlanningError("Native fast frozen prompt or references changed")
    if BundledSkillManifestValidator().validate(SKILL_ID) != payload.get(
        "skill_content_hash"
    ):
        raise AuroraPlanningError("Native fast Skill changed; create a new task")


def authorize(plan: JobPlanRecord, job: JobRecord, approval_text: str) -> None:
    validate_plan(plan, job)
    payload = copy.deepcopy(plan.payload)
    if plan.schema_version == authored.SCHEMA_VERSION:
        # The authored plan already holds the frozen per-page prompts; there is
        # no harness session to authorize.
        payload.update(harness_state="AUTHORIZED", approval_text=approval_text)
        plan.payload, plan.payload_hash = payload, canonical_hash(payload)
        return
    root = Path(payload["_native_workspace"])
    runner = NativeFastHarnessRunner()
    session_path = root / "session.json"
    write_contract(session_path, payload["_native_session"])
    runner.run(
        "authorize", root, {"session": session_path, "approval-text": approval_text}
    )
    authorized = _load_json(session_path)
    by_path = {
        str(Path(row["path"]).resolve()): row["evidence_id"]
        for row in authorized["identity"]["evidence"]
    }
    requests = []
    for page in payload["pages"]:
        index = page["page_index"]
        workspace = root / f"page-{index + 1:02d}"
        workspace.mkdir(parents=True, exist_ok=True)
        page_session = copy.deepcopy(authorized)
        page_session.update(
            active_page_index=index, accepted_pages=[], pending_generation=None
        )
        path = workspace / "session.json"
        write_contract(path, page_session)
        result = runner.run(
            "generate-next",
            workspace,
            {"session": path, "out": workspace / "request.json"},
        )
        request = result["generation_request"]
        source_ids = [
            by_path[str(Path(path).resolve())]
            for path in request["imagegen_reference_paths"]
        ]
        if (
            request["prompt"] != page["prompt"]
            or source_ids != page["source_asset_ids"]
            or request["page_index"] != index
        ):
            raise AuroraPlanningError(
                "Native generation request differs from the compiled plan"
            )
        requests.append(request)
    payload.update(
        _native_session=authorized,
        _native_requests=requests,
        harness_state="AUTHORIZED",
    )
    plan.payload, plan.payload_hash = payload, canonical_hash(payload)


class NativeFastMainImagePlanner(AuroraMainImagePlanner):
    """One original identity call; native local compilation is unchanged."""

    def __init__(
        self,
        session_factory: Any,
        gateway: Any,
        storage: Any,
        work_root: Path | None = None,
    ) -> None:
        super().__init__(
            session_factory,
            NativeFastHarnessRunner(),
            gateway=gateway,
            storage=storage,
            work_root=work_root,
            execution_mode=VERSION,
        )

    async def plan(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            if session.scalar(
                select(JobPlanRecord.id).where(JobPlanRecord.job_id == job_id)
            ):
                return JobStatus(job.status)
            config = copy.deepcopy(job.configuration)
            if config.get("settings", {}).get("main_image_speed") != "native_fast":
                raise AuroraPlanningError("Native fast requires explicit selection")
            if config.get("_main_image_fast_planning"):
                return JobStatus(job.status)
            job.configuration = {
                **config,
                "_main_image_fast_planning": {"state": "preparing"},
            }
            session.commit()
            ids, workspace_id = config["input"]["product_asset_ids"], job.workspace_id
            assets = get_ready_assets(session, workspace_id, ids)
            bindings = [
                {
                    "asset_id": key,
                    "sha256": assets[key].sha256,
                    "width": assets[key].width,
                    "height": assets[key].height,
                }
                for key in ids
            ]
        sources, paths = await self._materialize_sources(
            workspace_id, job_id, ids, assets
        )
        settings = config["settings"]
        content_hash = BundledSkillManifestValidator().validate(SKILL_ID)
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            if job.status != "planning" or job.cancel_requested_at:
                return JobStatus(job.status)
            job.configuration = {
                **job.configuration,
                "_main_image_fast_planning": {"state": "invoked"},
            }
            session.commit()
        gateway = self.gateway
        if gateway is None:
            raise AuroraPlanningError("Native identity gateway is unavailable")
        if authored.enabled():
            return await self._plan_authored(
                job_id, workspace_id, ids, bindings, sources, settings
            )
        result = await gateway.plan(
            PlannerRequest(
                workspace_id=workspace_id,
                job_id=job_id,
                group_key=job_id,
                sources=sources,
                page_count=6,
                language="zh-CN",
                product_name=settings["product_name"],
                product_information=tuple(_all_facts(settings)),
                platform_code="TAOBAO_DOMESTIC_MAIN_IMAGE",
                size="1024x1024",
                idempotency_key=f"{job_id}:{VERSION}:identity",
                system_prompt=_IDENTITY_SYSTEM_PROMPT,
                planning_profile=PROFILE,
            )
        )
        receipt = {
            "state": "returned",
            "provider_request_id": result.provider_request_id,
            "usage": result.normalized_usage,
            "elapsed_seconds": result.api_latency_seconds,
            "actual_cost_micros": total_cost(result),
            "planner_recovery": summary(result),
            "error_code": result.error_code,
        }
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            job.configuration = {
                **job.configuration,
                "_main_image_fast_planning": receipt,
            }
            identity_payload = (
                dict(result.payload) if isinstance(result.payload, dict) else None
            )
            if (
                identity_payload is not None
                and identity_payload.get("profile01_semantics_read") is False
            ):
                # The inherited original system prompt permits this runtime
                # flag; it is not model-authored product identity.
                identity_payload.pop("profile01_semantics_read")
            if (
                result.error_code
                or identity_payload is None
                or not Draft202012Validator(_aurora_identity_json_schema()).is_valid(
                    identity_payload
                )
            ):
                session.commit()
                raise AuroraPlanningError(
                    result.error_message
                    or "Native product identity response is incomplete"
                )
            if job.status != "planning" or job.cancel_requested_at:
                session.commit()
                return JobStatus(job.status)
            identity = _bind_identity_evidence(identity_payload, sources, paths)
            identity.pop("profile01_semantics_read", None)
            workspace = self.job_workspace(job_id)
            raw = _build_raw(job_id, settings, paths)
            input_path, identity_path, session_path = (
                workspace / n for n in ("input.json", "identity.json", "session.json")
            )
            write_contract(input_path, raw)
            write_contract(identity_path, identity)
            self.harness.run(
                "start", workspace, {"input": input_path, "session": session_path}
            )
            self.harness.run(
                "lock-identity",
                workspace,
                {"identity": identity_path, "session": session_path},
            )
            self.harness.run("compile", workspace, {"session": session_path})
            compiled = _load_json(session_path)
            public = _public_v20_plan_payload(
                settings, identity, compiled, execution_mode=VERSION
            )
            pages = []
            for index, page in enumerate(compiled["plan"]["pages"]):
                source_ids = list(page["evidence_ids"])
                if page["generation_mode"] == "PRODUCT_PRESERVING_EDIT":
                    source_ids = list(
                        dict.fromkeys([page["edit_target_evidence_id"], *source_ids])
                    )
                pages.append(
                    {
                        **page,
                        **public["pages"][index],
                        "prompt": page["prompt"],
                        "source_asset_ids": source_ids,
                        "prompt_sha256": hashlib.sha256(
                            page["prompt"].encode()
                        ).hexdigest(),
                    }
                )
            payload = {
                **public,
                "schema_version": SCHEMA_VERSION,
                "version": VERSION,
                "skill_id": SKILL_ID,
                "skill_content_hash": content_hash,
                "compiler_lineage": "original-zip-v2.0.0-unchanged",
                "source_bindings": bindings,
                "product_asset_ids": ids,
                "canvas": [1024, 1024],
                "user_facts": settings,
                "confirmed_facts": _all_facts(settings),
                "style_lock": compiled["plan"]["campaign_style"],
                "pages": pages,
                "execution_policy": {
                    "execution_mode": VERSION,
                    "concurrency": 6,
                    "automatic_redraw_enabled": False,
                    "plan_authorization_required": True,
                    "final_set_approval_required": False,
                },
                "validation": {
                    "status": "STRUCTURALLY_VALIDATED",
                    "visual_review": "NOT_REVIEWED",
                },
                "_native_workspace": str(workspace),
                "_native_session": compiled,
                "usage": {
                    "planner": [
                        {
                            "provider": getattr(
                                self.gateway, "provider_name", "unknown"
                            ),
                            "reported": bool(
                                (result.normalized_usage or {}).get("reported")
                            ),
                            **_planner_usage_record(call),
                            "provider_request_id_presence": "present"
                            if call.provider_request_id else "absent",
                            "provider_request_id": call.provider_request_id,
                            "raw_usage": call.raw_usage,
                            "normalized_usage": call.normalized_usage,
                        }
                        for call in (_planner_call_results([result]) or (result,))
                    ]
                },
            }
            plan = JobPlanRecord(
                id=new_id("plan"),
                workspace_id=workspace_id,
                job_id=job_id,
                revision=1,
                schema_version=SCHEMA_VERSION,
                payload=payload,
                payload_hash=canonical_hash(payload),
                validation_status=PlanValidationStatus.VALID.value,
                validation_errors=[],
                validator_version=VERSION,
                validated_at=utc_now(),
            )
            validate_plan(plan, job)
            session.add(plan)
            transition_job(
                job,
                JobStatus.AWAITING_CONFIRMATION,
                stage="awaiting_plan_confirmation",
                progress=15,
            )
            from .main_image_auto_start import confirm_validated_plan

            confirm_validated_plan(session, job, plan, work_root=self.work_root)
            session.commit()
            return JobStatus(job.status)


async def _authored_plan_method(
    self: NativeFastMainImagePlanner,
    job_id: str,
    workspace_id: str,
    ids: list[str],
    bindings: list[dict[str, Any]],
    sources: Any,
    settings: dict[str, Any],
) -> JobStatus | None:
    """One planning call authors the six pages (detail-page style)."""

    facts = _all_facts(settings)
    result = await self.gateway.plan(
        PlannerRequest(
            workspace_id=workspace_id,
            job_id=job_id,
            group_key=job_id,
            sources=sources,
            page_count=6,
            language="zh-CN",
            product_name=settings["product_name"],
            product_information=tuple(facts),
            platform_code="TAOBAO_DOMESTIC_MAIN_IMAGE",
            size="1024x1024",
            idempotency_key=f"{job_id}:{authored.VERSION}:plan",
            system_prompt=authored.system_prompt(),
            planning_profile=authored.PROFILE,
        )
    )
    receipt = {
        "state": "returned",
        "provider_request_id": result.provider_request_id,
        "usage": result.normalized_usage,
        "elapsed_seconds": result.api_latency_seconds,
        "actual_cost_micros": total_cost(result),
        "planner_recovery": summary(result),
        "error_code": result.error_code,
    }
    with self.session_factory() as session:
        job = session.get(JobRecord, job_id, with_for_update=True)
        if job is None:
            return None
        job.configuration = {**job.configuration, "_main_image_fast_planning": receipt}
        try:
            if result.error_code:
                raise authored.AuthoredPlanError(
                    result.error_message or "主图规划调用失败"
                )
            strategy = authored.validate_strategy(result.payload, len(ids))
        except authored.AuthoredPlanError as error:
            session.commit()
            raise AuroraPlanningError(str(error)) from error
        if job.status != "planning" or job.cancel_requested_at:
            session.commit()
            return JobStatus(job.status)
        pages = []
        for index, page in enumerate(strategy["plan"]["pages"]):
            prompt = authored.compile_prompt(strategy, index)
            pages.append(
                {
                    **authored.public_page(page, index),
                    "status": "awaiting_plan_approval",
                    "prompt": prompt,
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "source_asset_ids": authored.page_source_ids(strategy, index, ids),
                }
            )
        identity = strategy["plan"]["product_identity_lock"]
        payload = {
            "schema_version": authored.SCHEMA_VERSION,
            "version": authored.VERSION,
            "skill_id": authored.REFERENCE_ID,
            "skill_content_hash": authored.reference_bundle()[1],
            "compiler_lineage": "authored-one-pass-planner",
            "approval_checkpoint": "six_page_plan",
            "product": {
                "name": settings.get("product_name"),
                "category": settings.get("category"),
            },
            "product_identity_lock": {
                "identity_summary": identity["identity"],
                "label_text": identity["label_text"],
                "must_not_change": identity["do_not_change"],
                "physical_logic": identity["physical_logic"],
            },
            "campaign_style": strategy["plan"]["campaign_style_lock"],
            "source_copy_lines": strategy["analysis"]["source_copy_lines"],
            "source_bindings": bindings,
            "product_asset_ids": ids,
            "canvas": list(authored.CANVAS),
            "user_facts": settings,
            "confirmed_facts": strategy["analysis"]["confirmed_facts"],
            "style_lock": strategy["plan"]["campaign_style_lock"],
            "pages": pages,
            "execution_policy": {
                "execution_mode": authored.VERSION,
                "concurrency": 6,
                "automatic_redraw_enabled": False,
                "plan_authorization_required": True,
                "final_set_approval_required": False,
            },
            "validation": {
                "status": "STRUCTURALLY_VALIDATED",
                "visual_review": "NOT_REVIEWED",
            },
            "_authored_strategy": strategy,
            "usage": {
                "planner": [
                    {
                        "provider": getattr(self.gateway, "provider_name", "unknown"),
                        "reported": bool(
                            (result.normalized_usage or {}).get("reported")
                        ),
                        **_planner_usage_record(call),
                        "provider_request_id_presence": "present"
                        if call.provider_request_id
                        else "absent",
                        "provider_request_id": call.provider_request_id,
                        "raw_usage": call.raw_usage,
                        "normalized_usage": call.normalized_usage,
                    }
                    for call in (_planner_call_results([result]) or (result,))
                ]
            },
        }
        plan = JobPlanRecord(
            id=new_id("plan"),
            workspace_id=workspace_id,
            job_id=job_id,
            revision=1,
            schema_version=authored.SCHEMA_VERSION,
            payload=payload,
            payload_hash=canonical_hash(payload),
            validation_status=PlanValidationStatus.VALID.value,
            validation_errors=[],
            validator_version=authored.VERSION,
            validated_at=utc_now(),
        )
        validate_plan(plan, job)
        session.add(plan)
        transition_job(
            job,
            JobStatus.AWAITING_CONFIRMATION,
            stage="awaiting_plan_confirmation",
            progress=15,
        )
        from .main_image_auto_start import confirm_validated_plan

        confirm_validated_plan(session, job, plan, work_root=self.work_root)
        session.commit()
        return JobStatus(job.status)


NativeFastMainImagePlanner._plan_authored = _authored_plan_method  # type: ignore[attr-defined]


async def finalize_delivery(session_factory: Any, storage: Any, job_id: str) -> None:
    """Bind six actual delivered originals into the trimmed native runtime.

    This is file/token/completeness validation, with zero model calls. Partial
    suites retain their deliverable pages and do not get a fake final manifest.
    """
    with session_factory() as session:
        job = session.get(JobRecord, job_id)
        if (
            job is None
            or job.configuration.get("settings", {}).get("main_image_speed")
            != "native_fast"
        ):
            return
        plan = session.scalar(
            select(JobPlanRecord)
            .where(JobPlanRecord.job_id == job_id)
            .order_by(JobPlanRecord.revision.desc())
            .limit(1)
        )
        if plan is None or plan.payload.get("_native_final_job_id") == job_id:
            return
        if plan.schema_version == authored.SCHEMA_VERSION:
            # No harness session to bind: pages are delivered as generated.
            return
        items = session.scalars(
            select(JobItemRecord)
            .where(JobItemRecord.job_id == job_id)
            .order_by(JobItemRecord.ordinal)
        ).all()
        if len(items) != 6 or any(
            i.status not in {"succeeded", "reused"} for i in items
        ):
            return
        validate_plan(plan, job)
        rows = session.execute(
            select(JobAssetRecord, AssetRecord, JobItemRecord)
            .join(AssetRecord, AssetRecord.id == JobAssetRecord.asset_id)
            .join(JobItemRecord, JobItemRecord.id == JobAssetRecord.job_item_id)
            .where(
                JobAssetRecord.job_id == job_id,
                JobAssetRecord.workspace_id == job.workspace_id,
                JobAssetRecord.direction == "output",
                JobAssetRecord.is_deliverable.is_(True),
            )
            .order_by(JobItemRecord.ordinal)
        ).all()
        if len(rows) != 6 or [row[2].ordinal for row in rows] != list(range(6)):
            raise AuroraPlanningError(
                "Native technical closure requires six delivered originals"
            )
        originals = [
            (row[1].object_key, row[1].sha256, row[1].content_type) for row in rows
        ]
        payload = copy.deepcopy(plan.payload)
        expected_hash = plan.payload_hash
        workspace_id = job.workspace_id
    configured = Path(payload["_native_workspace"]).resolve()
    root = configured.parent / job_id / "technical-delivery" / new_id("closure")
    root.mkdir(parents=True, exist_ok=True)
    runner = NativeFastHarnessRunner()
    base = copy.deepcopy(payload["_native_session"])
    versions = []
    for index, (object_key, sha, content_type) in enumerate(originals):
        data = await storage.read_bytes(object_key)
        if hashlib.sha256(data).hexdigest() != sha:
            raise AuroraPlanningError("Delivered native original SHA changed")
        workspace = root / f"page-{index + 1:02d}"
        workspace.mkdir(parents=True, exist_ok=True)
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[
            content_type
        ]
        image_path = workspace / ("original" + suffix)
        image_path.write_bytes(data)
        request = payload["_native_requests"][index]
        page_session = copy.deepcopy(base)
        page_session.update(
            state="AWAITING_GENERATED_ASSET",
            active_page_index=index,
            accepted_pages=[],
            generated_versions=[],
            pending_generation={
                "token_digest": canonical_hash(request["generation_token"]),
                "page_index": index,
                "revision": request["revision"],
            },
        )
        path = workspace / "session.json"
        write_contract(path, page_session)
        runner.run(
            "record-generation",
            workspace,
            {
                "session": path,
                "token": request["generation_token"],
                "image": image_path,
            },
        )
        version = _load_json(path)["generated_versions"][-1]
        if version["sha256"] != sha or version["status"] != "GENERATED_NOT_REVIEWED":
            raise AuroraPlanningError(
                "Native record must bind the actual unaudited original"
            )
        versions.append(version)
    base.update(
        state="READY_FOR_DELIVERY",
        accepted_pages=list(range(6)),
        generated_versions=versions,
        pending_generation=None,
        active_page_index=None,
    )
    path = root / "session.json"
    output = root / "final-manifest.json"
    write_contract(path, base)
    runner.run(
        "finalize",
        root,
        {
            "session": path,
            "output": output,
            "approval-text": "按已确认六图方案授权进行技术交付；成图未经独立AI复审。",
        },
    )
    manifest = _load_json(output)
    with session_factory() as session:
        job = session.get(JobRecord, job_id, with_for_update=True)
        plan = session.scalar(
            select(JobPlanRecord)
            .where(JobPlanRecord.job_id == job_id)
            .order_by(JobPlanRecord.revision.desc())
            .limit(1)
            .with_for_update()
        )
        if job is None or job.workspace_id != workspace_id or plan is None:
            raise AuroraPlanningError("Native delivery ownership changed")
        if plan.payload.get("_native_final_job_id") == job_id:
            return
        if plan.payload_hash != expected_hash:
            raise AuroraPlanningError("Native plan changed during technical closure")
        value = {
            **plan.payload,
            "_native_final_job_id": job_id,
            "_native_final_session": _load_json(path),
            "_native_final_manifest": manifest,
            "harness_state": "FINALIZED",
            "technical_delivery": {
                "status": "COMPLETE",
                "visual_review": "NOT_REVIEWED",
                "page_count": 6,
                "sha256": [item[1] for item in originals],
                "set_audit_performed": False,
            },
        }
        plan.payload, plan.payload_hash = value, canonical_hash(value)
        session.commit()
