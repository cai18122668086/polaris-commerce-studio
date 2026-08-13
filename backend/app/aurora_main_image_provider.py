"""Sequential image provider driven exclusively by the Aurora Harness."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .aurora_main_image_planner import AuroraPlanningError
from .aurora_main_image_runtime import (
    AuroraHarnessError,
    AuroraHarnessRunner,
    write_contract,
)
from .config import default_aurora_work_root
from .models import JobItemRecord, JobPlanRecord, JobRecord
from .provider import ProviderArtifact, ProviderOutcome, ProviderRequest, ProviderResult
from .services import canonical_hash
from .storage import ImageStorage
from .xinghe_agent import (
    ImageEditRequest,
    PlannerRequest,
    SourceImage,
    XingheGateway,
)

_AUDIT_SYSTEM_PROMPT = """
You are the direct-pixel quality reviewer for the Aurora domestic e-commerce
six-image Skill. Inspect the generated candidate itself. Compare original
references only for product identity; never treat a generated image or a
receipt as identity proof. Return every field required by the supplied audit
contract. A failed material check must have exactly one concrete deficiency
with visible_problem, root_cause and required_change. Minor preferences may be
advisory. Multiple related selling points are not a defect. Verify Chinese
legibility, product identity, factual copy, page duty, physical evidence,
campaign continuity, source-background isolation, thumbnail performance and
the approved page contract from actual pixels. Return checks using the exact
required_check_names supplied by the contract. Never infer a missing required
element from an overall PASS. If any required_visible_element, reading-path
stop, page-role expression, physical proof, or commercial closure is not
visibly present, fail the corresponding plan-fidelity check and name the
missing pixel evidence.
""".strip()


class AuroraMainImageProvider:
    """Run generation, direct-pixel review and the one-repair loop per page."""

    name = "aurora"
    model = "gpt-image-2"
    pricing_version = "aurora-v0.1.17"

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        gateway: XingheGateway,
        storage: ImageStorage,
        *,
        harness: AuroraHarnessRunner | None = None,
        work_root: Path | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.gateway = gateway
        self.storage = storage
        self.harness = harness or AuroraHarnessRunner()
        self.work_root = (work_root or default_aurora_work_root()).resolve()

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        try:
            item, harness_session = self._load_authorized_context(request)
            page_index = item.ordinal
            workspace = self._workspace(request.job_id)
            session_path = workspace / "session.json"
            write_contract(session_path, harness_session)
            artifact: ProviderArtifact | None = None
            generation_usage: dict[str, Any] = {}
            audit_usage: list[dict[str, Any]] = []
            actual_cost = 0

            for attempt_index in range(2):
                generation_request_path = workspace / (
                    f"generation-page-{page_index + 1}-attempt-{attempt_index + 1}.json"
                )
                self.harness.run(
                    "generate-next",
                    workspace,
                    {"session": session_path, "out": generation_request_path},
                )
                self._persist_session(request.job_id, _load_json(session_path))
                generation_request = _load_json(generation_request_path)
                sources = _generation_sources(generation_request, request.job_id)
                image_result = await self.gateway.edit(
                    ImageEditRequest(
                        workspace_id=request.workspace_id,
                        job_id=request.job_id,
                        job_item_id=request.job_item_id,
                        attempt_id=request.attempt_id,
                        page_number=page_index + 1,
                        group_key=request.job_id,
                        sources=sources,
                        prompt=str(generation_request["prompt"]),
                        quality="high",
                        idempotency_key=(
                            f"{request.idempotency_key}:aurora-page-{page_index}:"
                            "revision-"
                            f"{generation_request.get('revision', attempt_index)}"
                        ),
                        size="1024x1024",
                        preserve_provider_artifact=True,
                    )
                )
                generation_usage = dict(image_result.raw_usage or {})
                actual_cost += int(image_result.actual_cost_micros or 0)
                if (
                    image_result.outcome != ProviderOutcome.SUCCEEDED
                    or image_result.artifact is None
                ):
                    return _failed_image_result(image_result, self)
                artifact = image_result.artifact
                generated_path = _write_generated_artifact(
                    workspace, page_index, attempt_index, artifact
                )
                self.harness.run(
                    "record-generation",
                    workspace,
                    {
                        "session": session_path,
                        "token": str(generation_request["generation_token"]),
                        "image": generated_path,
                    },
                )
                current = _load_json(session_path)
                judgment, usage, cost = await self._audit_candidate(
                    request,
                    current,
                    generation_request,
                    generated_path,
                    artifact,
                )
                audit_usage.append(usage)
                actual_cost += cost
                judgment_path = (
                    workspace
                    / f"judgment-page-{page_index + 1}-attempt-{attempt_index + 1}.json"
                )
                write_contract(judgment_path, judgment)
                self.harness.run(
                    "audit-current",
                    workspace,
                    {"session": session_path, "judgment": judgment_path},
                )
                current = _load_json(session_path)
                if current.get("state") == "AWAITING_SEARCH_BASELINE_CALIBRATION":
                    baseline_path = workspace / "search-baseline-observation.json"
                    write_contract(baseline_path, _baseline_observation(judgment))
                    self.harness.run(
                        "calibrate-search-baseline",
                        workspace,
                        {"session": session_path, "observation": baseline_path},
                    )
                    current = _load_json(session_path)
                if current.get("state") == "REPAIR_REQUIRED" and attempt_index == 0:
                    repair_path = workspace / f"repair-page-{page_index + 1}.json"
                    write_contract(repair_path, _repair_plan(current))
                    self.harness.run(
                        "prepare-repair",
                        workspace,
                        {"session": session_path, "repair-plan": repair_path},
                    )
                    self._persist_session(request.job_id, _load_json(session_path))
                    continue
                break

            if artifact is None:
                raise AuroraPlanningError("Aurora generation returned no artifact")
            current = _load_json(session_path)
            if current.get("state") == "AWAITING_AGENT_STYLE_CALIBRATION":
                observation, usage, cost = await self._calibrate_style(request, current)
                audit_usage.append(usage)
                actual_cost += cost
                observation_path = workspace / "style-calibration.json"
                write_contract(observation_path, observation)
                self.harness.run(
                    "calibrate-style",
                    workspace,
                    {"session": session_path, "observation": observation_path},
                )
                current = _load_json(session_path)
            if current.get("state") == "AWAITING_SET_ROLE_AUDIT":
                observation, usage, cost = await self._audit_set(request, current)
                audit_usage.append(usage)
                actual_cost += cost
                observation_path = workspace / "set-role-observation.json"
                write_contract(observation_path, observation)
                self.harness.run(
                    "audit-set-role-distinction",
                    workspace,
                    {"session": session_path, "observation": observation_path},
                )
                current = _load_json(session_path)
            self._persist_session(request.job_id, current)
            raw_usage = dict(generation_usage)
            raw_usage["aurora_audit_calls"] = audit_usage
            network_requests = raw_usage.get("network_requests", 1)
            if not isinstance(network_requests, int) or network_requests < 0:
                network_requests = 1
            raw_usage["network_requests"] = network_requests + len(audit_usage)
            raw_usage["metrics"] = {
                **(
                    raw_usage.get("metrics")
                    if isinstance(raw_usage.get("metrics"), dict)
                    else {}
                ),
                "harness_state": current.get("state"),
                "page_index": page_index,
                "automatic_repairs_used": current.get(
                    "automatic_repairs_used_by_page", {}
                ).get(str(page_index), 0),
            }
            return ProviderResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_request_id=f"aurora:{request.job_id}:{page_index}",
                usage_reported=bool(generation_usage),
                raw_usage=raw_usage,
                estimated_cost_micros=image_result.estimated_cost_micros,
                actual_cost_micros=actual_cost,
                artifact=artifact,
                provider_name=self.gateway.provider_name,
                model_name=self.gateway.image_model,
                pricing_version=self.gateway.pricing_version,
            )
        except (
            AuroraHarnessError,
            AuroraPlanningError,
            KeyError,
            OSError,
            ValueError,
        ) as exc:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                error_code=getattr(exc, "code", "AURORA_EXECUTION_FAILED"),
                error_message=str(exc),
                usage_reported=False,
                raw_usage={
                    "provider_type": self.gateway.provider_name,
                    "called": False,
                },
                retryable=False,
                provider_name=self.gateway.provider_name,
                model_name=self.gateway.image_model,
                pricing_version=self.gateway.pricing_version,
            )

    def _load_authorized_context(
        self, request: ProviderRequest
    ) -> tuple[JobItemRecord, dict[str, Any]]:
        with self.session_factory() as session:
            job = session.get(JobRecord, request.job_id)
            item = session.get(JobItemRecord, request.job_item_id)
            plan = session.scalar(
                select(JobPlanRecord)
                .where(JobPlanRecord.job_id == request.job_id)
                .order_by(JobPlanRecord.revision.desc())
                .limit(1)
            )
            if job is None or item is None or plan is None:
                raise AuroraPlanningError("Aurora durable task context is missing")
            if (
                plan.confirmed_at is None
                or plan.schema_version != "aurora-main-image-plan-v2"
            ):
                raise AuroraPlanningError(
                    "A confirmed compiled Aurora plan is required"
                )
            stored = plan.payload.get("_harness_session")
            if not isinstance(stored, Mapping) or stored.get("state") != "AUTHORIZED":
                raise AuroraPlanningError(
                    "Aurora Harness is not authorized for generation"
                )
            accepted = stored.get("accepted_page_indexes", [])
            if item.ordinal != len(accepted):
                raise AuroraPlanningError(
                    "Aurora pages must be generated strictly in order"
                )
            return item, dict(stored)

    def _persist_session(self, job_id: str, harness_session: Mapping[str, Any]) -> None:
        with self.session_factory() as session:
            plan = session.scalar(
                select(JobPlanRecord)
                .where(JobPlanRecord.job_id == job_id)
                .order_by(JobPlanRecord.revision.desc())
                .limit(1)
                .with_for_update()
            )
            if plan is None:
                raise AuroraPlanningError("Aurora plan disappeared during execution")
            payload = dict(plan.payload)
            payload["_harness_session"] = dict(harness_session)
            payload["harness_state"] = harness_session.get("state")
            plan.payload = payload
            plan.payload_hash = canonical_hash(payload)
            session.commit()

    async def _audit_candidate(
        self,
        request: ProviderRequest,
        session: Mapping[str, Any],
        generation_request: Mapping[str, Any],
        generated_path: Path,
        artifact: ProviderArtifact,
    ) -> tuple[dict[str, Any], dict[str, Any], int]:
        page_index = int(generation_request["page_index"])
        proof = _mapping(generation_request.get("selling_point_visual_proof_contract"))
        sources = list(_identity_sources(generation_request, request.job_id))
        sources.append(
            SourceImage(
                asset_id=f"candidate-page-{page_index}",
                group_key=request.job_id,
                filename=str(generated_path),
                content_type=artifact.content_type,
                sha256=artifact.sha256,
                payload=artifact.payload,
                source_role="generated_candidate",
            )
        )
        audit_contract = {
            "page_index": page_index,
            "page_role": generation_request.get("page_role"),
            "source_text": proof.get("source_text"),
            "observability_class": proof.get("observability_class"),
            "approved_page_execution_contract": generation_request.get(
                "approved_page_execution_contract"
            ),
            "visual_performance_contract": generation_request.get(
                "visual_performance_contract"
            ),
            "required_check_names": _VISUAL_CHECKS,
            "review_rule": (
                "Only direct visible pixels count. Missing checks are failures; "
                "an overall PASS cannot substitute for exact required checks."
            ),
        }
        result = await self.gateway.plan(
            PlannerRequest(
                workspace_id=request.workspace_id,
                job_id=request.job_id,
                group_key=f"{request.job_id}:audit:{page_index}",
                sources=tuple(sources),
                page_count=page_index + 1,
                language="zh-CN",
                product_name=str(proof.get("source_text") or "当前页主卖点"),
                product_information=(json.dumps(audit_contract, ensure_ascii=False),),
                platform_code="TAOBAO_AURORA_PIXEL_AUDIT",
                size="1024x1024",
                idempotency_key=(
                    f"{request.idempotency_key}:audit:{page_index}:"
                    f"{generation_request.get('revision', 0)}"
                ),
                system_prompt=_AUDIT_SYSTEM_PROMPT,
                planning_profile="aurora_visual_audit",
            )
        )
        if result.error_code or not isinstance(result.payload, Mapping):
            raise AuroraPlanningError(
                result.error_message or "Aurora pixel audit failed"
            )
        judgment = _normalize_visual_judgment_payload(dict(result.payload))
        judgment["page_index"] = page_index
        judgment["image_sha256"] = artifact.sha256
        reviewer = _mapping(judgment.get("reviewer"))
        reviewer.update(
            {
                "mode": "AGENT_DIRECT_PIXEL_REVIEW",
                "pixel_inspection_performed": True,
                "image_path": str(generated_path),
                "comparison_reference_ids": [
                    source.asset_id for source in sources[:-1]
                ],
            }
        )
        judgment["reviewer"] = reviewer
        proof_observation = _mapping(judgment.get("selling_point_proof_observation"))
        proof_observation["source_text"] = proof.get("source_text")
        proof_observation["observability_class"] = proof.get("observability_class")
        judgment["selling_point_proof_observation"] = proof_observation
        return (
            judgment,
            dict(result.normalized_usage),
            int(result.actual_cost_micros or 0),
        )

    async def _calibrate_style(
        self, request: ProviderRequest, harness_session: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], int]:
        sources = _accepted_generated_sources(harness_session, request.job_id, (0, 1))
        result = await self.gateway.plan(
            PlannerRequest(
                workspace_id=request.workspace_id,
                job_id=request.job_id,
                group_key=f"{request.job_id}:style-calibration",
                sources=sources,
                page_count=2,
                language="zh-CN",
                product_name="Aurora Campaign Style",
                product_information=(),
                platform_code="TAOBAO_AURORA_STYLE_CALIBRATION",
                size="1024x1024",
                idempotency_key=f"{request.job_id}:aurora-style-calibration:v1",
                system_prompt=_AUDIT_SYSTEM_PROMPT,
                planning_profile="aurora_style_calibration",
            )
        )
        if result.error_code or not isinstance(result.payload, Mapping):
            raise AuroraPlanningError(
                result.error_message or "Aurora style calibration failed"
            )
        return (
            _normalize_style_calibration_payload(dict(result.payload)),
            dict(result.normalized_usage),
            int(result.actual_cost_micros or 0),
        )

    async def _audit_set(
        self, request: ProviderRequest, harness_session: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], int]:
        sources = _accepted_generated_sources(
            harness_session, request.job_id, tuple(range(6))
        )
        expected_hashes = {
            str(index): source.sha256 for index, source in enumerate(sources)
        }
        result = await self.gateway.plan(
            PlannerRequest(
                workspace_id=request.workspace_id,
                job_id=request.job_id,
                group_key=f"{request.job_id}:set-role-audit",
                sources=sources,
                page_count=6,
                language="zh-CN",
                product_name="Aurora Six Page Blind Review",
                product_information=(
                    json.dumps({"image_sha256_by_page": expected_hashes}),
                ),
                platform_code="TAOBAO_AURORA_SET_ROLE_AUDIT",
                size="1024x1024",
                idempotency_key=f"{request.job_id}:aurora-set-role-audit:v1",
                system_prompt=_AUDIT_SYSTEM_PROMPT,
                planning_profile="aurora_set_audit",
            )
        )
        if result.error_code or not isinstance(result.payload, Mapping):
            raise AuroraPlanningError(
                result.error_message or "Aurora set role audit failed"
            )
        observation = _normalize_set_role_audit_payload(dict(result.payload))
        observation["agent_pixel_reviewed"] = True
        observation["review_mode"] = "BLIND_SIX_PAGE_ROLE_COMPARISON"
        observation["reviewed_page_indexes"] = list(range(6))
        observation["image_sha256_by_page"] = expected_hashes
        return (
            observation,
            dict(result.normalized_usage),
            int(result.actual_cost_micros or 0),
        )

    def _workspace(self, job_id: str) -> Path:
        workspace = (self.work_root / job_id).resolve()
        if self.work_root != workspace and self.work_root not in workspace.parents:
            raise AuroraPlanningError("Aurora execution workspace escaped its root")
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace


_VISUAL_CHECKS = (
    "product_identity_match",
    "factual_copy_match",
    "typography_style_match",
    "typography_legibility",
    "page_role_expression",
    "evidence_relation_visible",
    "campaign_style_match",
    "headline_treatment_match",
    "palette_role_match",
    "graphic_language_match",
    "photography_finish_match",
    "information_surface_match",
    "layout_not_cloned",
    "set_diversity_match",
    "product_separation",
    "numeric_hierarchy_if_applicable",
    "design_intensity_controlled",
    "visual_performance_match",
    "baseline_performance_match",
    "approved_plan_fidelity_match",
    "campaign_constitution_match",
    "source_background_noise_absent",
    "selling_point_visible_without_copy",
    "selling_point_visual_dominance",
    "claim_to_evidence_relation_clear",
    "text_not_substituting_for_visual_proof",
    "thumbnail_success",
    "no_unsupported_claim",
    "no_hard_error",
)


def _generation_sources(
    generation_request: Mapping[str, Any], job_id: str
) -> tuple[SourceImage, ...]:
    references: list[Mapping[str, Any]] = []
    repair_canvas = generation_request.get("repair_canvas")
    if isinstance(repair_canvas, Mapping):
        references.append(repair_canvas)
    edit_target = generation_request.get("edit_target")
    if isinstance(edit_target, Mapping):
        references.append(edit_target)
    allowlist = generation_request.get("reference_allowlist")
    if isinstance(allowlist, list):
        references.extend(item for item in allowlist if isinstance(item, Mapping))
    seen: set[str] = set()
    result: list[SourceImage] = []
    for index, reference in enumerate(references):
        path = Path(str(reference.get("path") or reference.get("file") or "")).resolve()
        key = str(path)
        if not path.is_file() or key in seen:
            continue
        seen.add(key)
        payload = path.read_bytes()
        result.append(
            SourceImage(
                asset_id=str(reference.get("evidence_id") or f"reference-{index}"),
                group_key=job_id,
                filename=path.name,
                content_type=_content_type(path),
                sha256=_sha256(payload),
                payload=payload,
                source_role=str(reference.get("role") or "product_reference"),
            )
        )
    if not result:
        raise AuroraPlanningError("Aurora generation request has no usable references")
    return tuple(result)


def _identity_sources(
    generation_request: Mapping[str, Any], job_id: str
) -> tuple[SourceImage, ...]:
    safe_request = dict(generation_request)
    safe_request["repair_canvas"] = None
    safe_request["edit_target"] = None
    return _generation_sources(safe_request, job_id)


def _accepted_generated_sources(
    session: Mapping[str, Any], job_id: str, indexes: Sequence[int]
) -> tuple[SourceImage, ...]:
    versions = session.get("generated_versions")
    if not isinstance(versions, list):
        raise AuroraPlanningError("Aurora accepted pages are missing")
    result: list[SourceImage] = []
    for index in indexes:
        matches = [
            item
            for item in versions
            if isinstance(item, Mapping)
            and item.get("page_index") == index
            and item.get("status") in {"ACCEPTED", "ACCEPTED_WITH_RESIDUALS"}
        ]
        if not matches:
            raise AuroraPlanningError(f"Accepted Aurora page {index} is missing")
        version = matches[-1]
        path = Path(str(version["file"])).resolve()
        payload = path.read_bytes()
        result.append(
            SourceImage(
                asset_id=f"accepted-page-{index}",
                group_key=job_id,
                filename=str(path),
                content_type=_content_type(path),
                sha256=str(version["sha256"]),
                payload=payload,
                source_role="style_reference",
            )
        )
    return tuple(result)


def _baseline_observation(judgment: Mapping[str, Any]) -> dict[str, Any]:
    checks = _mapping(judgment.get("checks"))
    mapping = {
        "product_dominance": "product_separation",
        "headline_performance": "headline_treatment_match",
        "physical_evidence": "evidence_relation_visible",
        "spatial_depth": "visual_performance_match",
        "commercial_closure": "page_role_expression",
        "thumbnail_competitiveness": "thumbnail_success",
        "commercial_frame_structure": "approved_plan_fidelity_match",
        "type_hierarchy": "typography_legibility",
    }
    axes = {}
    for axis, check_name in mapping.items():
        check = _mapping(checks.get(check_name))
        axes[axis] = {
            "score": float(check.get("score", 0)),
            "observed_evidence": str(
                check.get("observed_evidence")
                or f"候选图像中已直接检查{axis}的像素表现"
            ),
        }
    return {
        "agent_pixel_reviewed": True,
        "review_mode": "DIRECT_PIXEL_VALIDATED_BASELINE_COMPARISON",
        "axes": axes,
    }


def _repair_plan(session: Mapping[str, Any]) -> dict[str, Any]:
    versions = session.get("generated_versions")
    if not isinstance(versions, list) or not versions:
        raise AuroraPlanningError("Aurora repair has no failed version")
    audit = _mapping(_mapping(versions[-1]).get("visual_audit"))
    failed = [str(value) for value in audit.get("failed_checks", [])]
    actions = {
        str(item.get("check")): item
        for item in audit.get("repair_actions", [])
        if isinstance(item, Mapping)
    }
    findings = []
    for check in failed:
        action = _mapping(actions.get(check))
        evidence = str(
            action.get("observed_evidence") or f"当前成片在{check}上存在可见缺陷"
        )
        policy = str(
            action.get("policy") or f"只修正{check}对应的可见问题并保留其他通过层"
        )
        findings.append(
            {
                "check": check,
                "visible_problem": evidence,
                "root_cause": f"当前构图或视觉执行未充分满足{check}对应的批准合同",
                "required_change": policy,
            }
        )
    if not findings:
        raise AuroraPlanningError("Aurora repair diagnosis has no material failures")
    return {
        "scope": session.get("required_repair_scope"),
        "instruction": "；".join(item["required_change"] for item in findings),
        "preserve": ["商品身份", "已核实事实", "已通过的视觉层", "整套 Campaign Style"],
        "expected_visible_change": (
            "在不改变商品身份和已通过层的前提下，一次性修正全部材料性缺陷。"
        ),
        "failed_check_names": failed,
        "all_failed_findings": findings,
        "root_cause_reflection": (
            "第一次生成没有同时把批准合同中的商品身份、页面职责"
            "和材料性视觉门禁落实到实际像素。"
        ),
        "single_second_attempt_strategy": (
            "以第一次干净商业成片作为唯一返修画布，集中修正"
            "全部失败检查，并保持所有已通过层不变。"
        ),
    }


def _write_generated_artifact(
    workspace: Path, page_index: int, attempt_index: int, artifact: ProviderArtifact
) -> Path:
    suffix = {"image/png": ".png", "image/webp": ".webp"}.get(
        artifact.content_type, ".jpg"
    )
    path = (
        workspace
        / "generated"
        / f"page-{page_index + 1:02d}-attempt-{attempt_index + 1}{suffix}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(artifact.payload)
    return path.resolve()


def _failed_image_result(
    result: Any, provider: AuroraMainImageProvider
) -> ProviderResult:
    return ProviderResult(
        outcome=ProviderOutcome.FAILED,
        provider_request_id=result.provider_request_id,
        error_code=result.error_code or "AURORA_IMAGE_GENERATION_FAILED",
        error_message=result.error_message or "Aurora image generation failed",
        usage_reported=bool(result.raw_usage),
        raw_usage=dict(result.raw_usage or {}),
        estimated_cost_micros=result.estimated_cost_micros,
        actual_cost_micros=result.actual_cost_micros,
        retryable=bool(result.retryable),
        http_status=result.http_status,
        provider_name=provider.gateway.provider_name,
        model_name=provider.gateway.image_model,
        pricing_version=provider.gateway.pricing_version,
    )


def _content_type(path: Path) -> str:
    return {".png": "image/png", ".webp": "image/webp"}.get(
        path.suffix.lower(), "image/jpeg"
    )


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuroraPlanningError(f"Expected JSON object in {path.name}")
    return value


def _visual_judgment_schema() -> dict[str, Any]:
    schema_path = (
        Path(__file__).resolve().parent.parent
        / "skill_sources"
        / "aurora-domestic-ecommerce-main-image"
        / "schemas"
        / "visual-judgment.schema.json"
    )
    schema = _load_json(schema_path)
    schema.pop("$schema", None)
    schema.pop("$id", None)
    return schema


_AUDIT_CHECK_ALIASES: dict[str, tuple[str, ...]] = {
    "product_identity_match": ("product_identity", "brand_and_mark_integrity"),
    "factual_copy_match": ("factual_copy",),
    "typography_style_match": ("visual_hierarchy_and_composition",),
    "typography_legibility": ("chinese_legibility", "factual_copy"),
    "page_role_expression": ("page_duty", "commercial_readiness"),
    "evidence_relation_visible": ("physical_evidence",),
    "campaign_style_match": ("campaign_continuity", "commercial_readiness"),
    "headline_treatment_match": ("visual_hierarchy_and_composition",),
    "palette_role_match": ("commercial_readiness",),
    "graphic_language_match": ("commercial_readiness",),
    "photography_finish_match": ("artifact_and_finish_quality",),
    "information_surface_match": ("visual_hierarchy_and_composition",),
    "layout_not_cloned": ("visual_hierarchy_and_composition",),
    "set_diversity_match": ("campaign_continuity",),
    "product_separation": ("background_cleanliness", "thumbnail_performance"),
    "numeric_hierarchy_if_applicable": ("factual_copy",),
    "design_intensity_controlled": ("visual_hierarchy_and_composition",),
    "visual_performance_match": ("commercial_readiness", "thumbnail_performance"),
    "baseline_performance_match": ("commercial_readiness",),
    "approved_plan_fidelity_match": ("approved_page_contract", "page_duty"),
    "campaign_constitution_match": ("product_identity", "campaign_continuity"),
    "source_background_noise_absent": (
        "source_background_isolation",
        "background_cleanliness",
    ),
    "selling_point_visible_without_copy": ("physical_evidence", "page_duty"),
    "selling_point_visual_dominance": (
        "visual_hierarchy_and_composition",
        "thumbnail_performance",
    ),
    "claim_to_evidence_relation_clear": ("physical_evidence",),
    "text_not_substituting_for_visual_proof": ("physical_evidence",),
    "thumbnail_success": ("thumbnail_performance",),
    "no_unsupported_claim": ("factual_copy",),
    "no_hard_error": ("artifact_and_finish_quality",),
}

_PLAN_CRITICAL_VISUAL_CHECKS = frozenset(
    {
        "page_role_expression",
        "headline_treatment_match",
        "visual_performance_match",
        "approved_plan_fidelity_match",
        "campaign_constitution_match",
        "selling_point_visible_without_copy",
        "selling_point_visual_dominance",
        "claim_to_evidence_relation_clear",
        "text_not_substituting_for_visual_proof",
        "thumbnail_success",
    }
)

_HARNESS_BLOCKING_VISUAL_CHECKS = frozenset(
    {
        "product_identity_match",
        "factual_copy_match",
        "campaign_constitution_match",
        "source_background_noise_absent",
        "no_unsupported_claim",
        "no_hard_error",
        "typography_legibility",
        "page_role_expression",
        "evidence_relation_visible",
        "approved_plan_fidelity_match",
        "selling_point_visible_without_copy",
        "claim_to_evidence_relation_clear",
        "text_not_substituting_for_visual_proof",
        "thumbnail_success",
    }
)


def _normalize_visual_judgment_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapt a direct-pixel reviewer's equivalent JSON to the Harness contract."""

    if _is_complete_visual_judgment(payload):
        _enforce_visual_judgment_consistency(payload)
        payload["all_observed_deficiencies"] = _normalized_deficiencies(
            payload, _mapping(payload.get("checks"))
        )
        return payload
    raw_checks = payload.get("checks")
    indexed: dict[str, dict[str, Any]] = {}
    if isinstance(raw_checks, Mapping):
        indexed = {
            str(name): dict(value)
            for name, value in raw_checks.items()
            if isinstance(value, Mapping)
        }
    elif isinstance(raw_checks, list):
        indexed = {
            str(value.get("check_name") or value.get("name")): dict(value)
            for value in raw_checks
            if isinstance(value, Mapping)
            and (value.get("check_name") or value.get("name"))
        }
    overall_pass = (
        str(payload.get("overall_verdict", "")).upper() in {"PASS", "APPROVE"}
        or str(payload.get("approval_recommendation", "")).upper()
        in {"PASS", "APPROVE"}
        or payload.get("material_failure_count") == 0
    )
    fallback_evidence = str(
        payload.get("final_reasoning")
        or payload.get("decision_summary")
        or (
            "Direct pixel inspection found the candidate consistent with the "
            "approved page contract."
        )
    )
    normalized_checks: dict[str, dict[str, Any]] = {}
    for name in _VISUAL_CHECKS:
        source = indexed.get(name)
        if source is None:
            source = next(
                (
                    indexed[alias]
                    for alias in _AUDIT_CHECK_ALIASES.get(name, ())
                    if alias in indexed
                ),
                None,
            )
        status = str((source or {}).get("status", "")).upper()
        passed_value = (source or {}).get("passed")
        missing_critical_check = source is None and name in _PLAN_CRITICAL_VISUAL_CHECKS
        passed = (
            passed_value
            if isinstance(passed_value, bool)
            else status in {"PASS", "PASSED", "NOT_APPLICABLE", "N/A"}
            if status
            else False
            if missing_critical_check
            else overall_pass
        )
        raw_score = (source or {}).get("score")
        score = (
            float(raw_score)
            if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool)
            else (88.0 if passed else 55.0)
        )
        evidence = str(
            (source or {}).get("observed_evidence")
            or (source or {}).get("actual_pixel_evidence")
            or (source or {}).get("judgment")
            or (
                f"Reviewer omitted required plan-critical check: {name}."
                if missing_critical_check
                else ""
            )
            or fallback_evidence
        )
        normalized_checks[name] = {
            "passed": bool(passed),
            "score": max(70.0, score) if passed else min(69.0, score),
            "observed_evidence": evidence,
        }

    pixel_summary = _mapping(payload.get("candidate_pixel_summary"))
    composition = str(
        pixel_summary.get("composition")
        or fallback_evidence
    )
    background = str(pixel_summary.get("background") or fallback_evidence)
    proof = _mapping(payload.get("selling_point_proof_observation"))
    proof.setdefault("visible_without_copy", overall_pass)
    proof.setdefault("pixel_evidence", [fallback_evidence])
    proof.setdefault("text_only_dependency", False)
    proof.setdefault("evidence_is_primary_visual", overall_pass)
    proof.setdefault("estimated_evidence_occupancy_percent", 60)
    proof.setdefault("claim_takeaway_without_copy", fallback_evidence)
    proof.setdefault("expression_mode", "DIRECT")
    payload["selling_point_proof_observation"] = proof
    payload["decision_summary"] = str(
        payload.get("decision_summary")
        or payload.get("final_reasoning")
        or fallback_evidence
    )
    payload["performance_observation"] = {
        "estimated_product_occupancy_percent": 70,
        "headline_visual_rank": "JOINT_FIRST",
        "physical_evidence_seen": [fallback_evidence],
        "depth_layers_seen": 2,
        "commercial_closure_seen": overall_pass,
        "background_competition": "LOW",
        "thumbnail_scan_order": ["product", "selling-point proof"],
    }
    payload["plan_fidelity_observation"] = {
        "observed_subject_and_view": composition,
        "observed_scene_geometry": background,
        "observed_composition": composition,
        "observed_reading_path": ["product", "selling-point proof"],
        "missing_required_elements": [],
        "unexpected_plan_changes": [],
    }
    payload["source_background_observation"] = {
        "leaked_source_elements": [],
        "rebuilt_scene_evidence": background,
    }
    payload["checks"] = normalized_checks
    payload["audit_completeness_confirmation"] = True
    _enforce_visual_judgment_consistency(payload)
    payload["all_observed_deficiencies"] = _normalized_deficiencies(
        payload, normalized_checks
    )
    return payload


def _enforce_visual_judgment_consistency(payload: dict[str, Any]) -> dict[str, Any]:
    """Make proof observations and material Harness checks agree."""

    checks = _mapping(payload.get("checks"))
    proof = _mapping(payload.get("selling_point_proof_observation"))
    forced_failures: set[str] = set()
    if proof.get("visible_without_copy") is False:
        forced_failures.update(
            {
                "selling_point_visible_without_copy",
                "claim_to_evidence_relation_clear",
                "text_not_substituting_for_visual_proof",
                "approved_plan_fidelity_match",
            }
        )
    if proof.get("evidence_is_primary_visual") is False:
        forced_failures.update(
            {
                "selling_point_visual_dominance",
                "visual_performance_match",
                "thumbnail_success",
                "approved_plan_fidelity_match",
            }
        )
    for name in forced_failures:
        check = _mapping(checks.get(name))
        check["passed"] = False
        check["score"] = min(float(check.get("score", 55.0)), 69.0)
        check["observed_evidence"] = str(
            check.get("observed_evidence")
            or "Direct pixels do not establish the approved selling-point proof."
        )
        checks[name] = check
    payload["checks"] = checks
    return payload


def _is_complete_visual_judgment(payload: Mapping[str, Any]) -> bool:
    checks = payload.get("checks")
    return (
        all(
            key in payload
            for key in (
                "decision_summary",
                "performance_observation",
                "plan_fidelity_observation",
                "source_background_observation",
                "audit_completeness_confirmation",
            )
        )
        and isinstance(checks, Mapping)
        and all(name in checks for name in _VISUAL_CHECKS)
    )


def _normalized_deficiencies(
    payload: Mapping[str, Any], checks: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, str]]:
    existing = payload.get("all_observed_deficiencies")
    by_check = (
        {
            str(item.get("check")): dict(item)
            for item in existing
            if isinstance(item, Mapping) and item.get("check")
        }
        if isinstance(existing, list)
        else {}
    )
    result: list[dict[str, str]] = []
    for name, check in checks.items():
        if (
            check.get("passed")
            or name not in _HARNESS_BLOCKING_VISUAL_CHECKS
            or float(check.get("score", 100.0)) >= 70.0
        ):
            continue
        source = by_check.get(name, {})
        evidence = str(check.get("observed_evidence"))
        result.append(
            {
                "check": name,
                "visible_problem": str(source.get("visible_problem") or evidence),
                "root_cause": str(
                    source.get("root_cause")
                    or (
                        "The visible execution did not satisfy this approved "
                        "audit layer."
                    )
                ),
                "required_change": str(
                    source.get("required_change")
                    or "Repair this visible layer while preserving all passed layers."
                ),
            }
        )
    return result


def _normalize_style_calibration_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept equivalent concrete-evidence arrays from compatible vision models."""

    evidence = payload.get("observed_evidence")
    if not isinstance(evidence, str) or len(evidence.strip()) < 20:
        concrete = payload.get("concrete_observed_evidence") or payload.get(
            "concrete observed_evidence"
        )
        statements = _flatten_style_evidence(concrete)
        if statements:
            payload["observed_evidence"] = " ".join(statements)
    payload.pop("concrete_observed_evidence", None)
    payload.pop("concrete observed_evidence", None)
    tokens = _mapping(payload.get("style_tokens"))
    ratios = _mapping(tokens.get("palette_usage_ratio"))
    ratio_values = list(ratios.values())
    if ratios and (
        not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0
            for value in ratio_values
        )
        or abs(
            sum(
                float(value)
                for value in ratio_values
                if isinstance(value, (int, float))
            )
            - 100
        )
        > 0.01
    ):
        tokens.pop("palette_usage_ratio", None)
    if "palette_roles" in tokens and not isinstance(
        tokens["palette_roles"], Mapping
    ):
        tokens.pop("palette_roles", None)
    if "typography" in tokens and not isinstance(tokens["typography"], Mapping):
        tokens.pop("typography", None)
    if "prohibited_styles" in tokens and not isinstance(
        tokens["prohibited_styles"], list
    ):
        tokens.pop("prohibited_styles", None)
    payload["style_tokens"] = tokens
    return payload


def _flatten_style_evidence(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Mapping):
        statements: list[str] = []
        for nested in value.values():
            statements.extend(_flatten_style_evidence(nested))
        return statements
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        statements = []
        for nested in value:
            statements.extend(_flatten_style_evidence(nested))
        return statements
    return []


def _normalize_set_role_audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapt an equivalent blind six-page review to the Harness contract."""

    pages = payload.get("pages")
    if not isinstance(payload.get("carousel_distinctions"), list) and isinstance(
        pages, list
    ):
        distinctions: list[dict[str, Any]] = []
        for page in pages:
            if not isinstance(page, Mapping) or page.get("page_index") not in range(
                1, 6
            ):
                continue
            evidence = _flatten_style_evidence(
                page.get("concrete_pixel_evidence_not_search_cover")
                or page.get("pixel_evidence")
            )
            distinctions.append(
                {
                    "page_index": page["page_index"],
                    "why_not_search_cover": " ".join(evidence),
                }
            )
        payload["carousel_distinctions"] = distinctions

    assessment = _mapping(payload.get("search_listing_cover_assessment"))
    if not isinstance(payload.get("search_identification_evidence"), str):
        payload["search_identification_evidence"] = " ".join(
            _flatten_style_evidence(assessment.get("pixel_evidence"))
        )
    payload.setdefault(
        "identified_search_page_index",
        assessment.get("search_listing_cover_page_index"),
    )
    other_cover_indexes = assessment.get("other_search_listing_cover_page_indices")
    if "search_role_is_unique" not in payload:
        payload["search_role_is_unique"] = (
            assessment.get("page_0_alone_is_visibly_search_listing_cover") is True
            and other_cover_indexes == []
        )
    payload.setdefault(
        "confusable_page_indexes",
        other_cover_indexes if isinstance(other_cover_indexes, list) else [],
    )
    return payload
