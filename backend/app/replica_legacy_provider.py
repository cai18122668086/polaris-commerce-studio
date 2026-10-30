"""Page-local delivery for unbound legacy jobs; frozen protocol code is unchanged."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from PIL import Image

from .provider import ProviderArtifact, ProviderOutcome, ProviderRequest, ProviderResult
from .replica_native import (
    NativeReplicaRun,
    ReplicaAnalysisUnavailable,
    ReplicaInputTooLarge,
    ReplicaNativeError,
    ReplicaPlanAuditRejected,
    digest,
    native_accounting,
    read_json,
    write_json,
)
from .replica_native_provider import (
    NativeReplicaProvider,
    ReplicaCanvasMismatch,
    ReplicaImageOutcomeUnknown,
)
from .replica_progress import native_progress


class LegacyPageDeliveryProvider(NativeReplicaProvider):
    async def execute(self, request: ProviderRequest) -> ProviderResult:
        try:
            values, _, _ = self._load(request)
        except Exception:
            return await super().execute(request)
        execution = values.get("native_executions", {}).get(request.job_id, {})
        snapshot = execution.get("snapshot") or values.get("native_snapshot", {})
        if (
            values.get("replication_method") != "exact"
            or snapshot.get("model_protocol")
        ):
            return await super().execute(request)
        return await self._execute_legacy(request)

    async def _execute_legacy(self, request: ProviderRequest) -> ProviderResult:
        run = None
        initial_calls = 0
        try:
            values, document_id, ordinal = self._load(request)
            execution = values.get("native_executions", {}).get(request.job_id, {})
            snapshot = execution.get("snapshot") or values["native_snapshot"]
            from . import replica_direct_delivery
            from .replica_execution_resume import (
                budget_resume_source,
                restore_execution,
            )

            direct_source = (
                None
                if execution
                else replica_direct_delivery.retry_source(
                    values, request, self.session_factory
                )
            )

            resumed = (
                None
                if execution or direct_source
                else budget_resume_source(values, request, self.session_factory)
            )
            if resumed:
                snapshot = resumed[0]
            if direct_source:
                snapshot = direct_source[0]
            run_type = NativeReplicaRun
            if snapshot.get("model_protocol"):
                from .replica_exact_compact import CompactExactReplicaRun, run_class

                run_type = (
                    CompactExactReplicaRun
                    if resumed
                    or (
                        direct_source
                        and snapshot["model_protocol"].get("version")
                        not in {
                            "exact-compact-v5",
                            "exact-compact-v6",
                            "exact-compact-v7",
                            "exact-compact-v8",
                            "exact-compact-v9",
                            "exact-compact-v10",
                        }
                    )
                    else run_class(
                        values["replication_method"], snapshot["model_protocol"]
                    )
                )
            if values["replication_method"] == "exact":
                from .replica_platform_delivery import delivery_run_type

                run_type = delivery_run_type(run_type)
            run = run_type(
                values["replication_method"],
                document_id,
                request.workspace_id,
                self.gateway,
                self.storage,
                root=Path(snapshot["root"]),
            )
            if (
                direct_source
                and snapshot.get("model_protocol")
                and snapshot.get("model_protocol", {}).get("version")
                not in {
                    "exact-compact-v5",
                    "exact-compact-v6",
                    "exact-compact-v7",
                    "exact-compact-v8",
                    "exact-compact-v9",
                    "exact-compact-v10",
                }
            ):
                await replica_direct_delivery.restore_source(
                    run, snapshot, direct_source[1]
                )
            elif resumed:
                await restore_execution(run, snapshot, resumed[1])
            else:
                await run.restore(snapshot)
            initial_calls = len(run.usage)
            page_local = run.method == "exact" and not callable(
                getattr(run, "image_prompt_for_module", None)
            )
            delivery = execution.get("delivery", [])
            if len(delivery) <= ordinal:
                from .replica_streaming import starts_group

                if not page_local and not starts_group(self, request, ordinal):
                    raise ReplicaNativeError("前序复刻尚未通过完整验收。")
                if run.method == "exact":
                    delivery = await _execute_pages(self, run, request, ordinal)
                else:
                    delivery = await self._style(run, request)
                if len(delivery) != len(values["plans"]) and not (
                    page_local and len(delivery) > ordinal
                ):
                    raise ReplicaNativeError("验收图片数量与确认方案不一致。")
                await self._save(run, request.job_id, delivery=delivery)
            path = run.path(delivery[ordinal])
            data = path.read_bytes()
            with Image.open(path) as image:
                width, height = image.size
                content_type = Image.MIME.get(image.format or "", "image/png")
                suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[
                    image.format or "PNG"
                ]
            accounting = native_accounting(run.usage[initial_calls:])
            return ProviderResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_request_id=f"replica:{request.job_id}:{ordinal}",
                usage_reported=accounting["reported"],
                raw_usage={
                    **accounting,
                    "skill_id": run.skill_id,
                    "skill_content_hash": run.source_hash,
                    "replication_method": run.method,
                    "native_state": run.state()["state"],
                    "native_visual_audited": not getattr(
                        run, "direct_execution", False
                    ),
                    "post_generation_review": "disabled"
                    if getattr(run, "direct_execution", False)
                    else "enabled",
                    "native_calls": run.usage[initial_calls:],
                },
                actual_cost_micros=accounting["actual_cost_micros"],
                estimated_cost_micros=accounting["estimated_cost_micros"],
                artifact=ProviderArtifact(
                    payload=data,
                    filename=f"replica-{ordinal + 1:03}{suffix}",
                    content_type=content_type,
                    width=width,
                    height=height,
                    sha256=digest(data),
                ),
                provider_name=self.gateway.provider_name,
                model_name=self.gateway.image_model,
                pricing_version=self.gateway.pricing_version,
            )
        except Exception as exc:
            # Generated files and issued tokens survive audit/transport failures.
            if run is not None:
                with suppress(Exception):
                    await self._save(run, request.job_id)
            accounting = native_accounting(run.usage[initial_calls:] if run else [])
            from .provider_diagnostics import retained_metrics

            diagnostics = next(
                (
                    retained_metrics(call)
                    for call in reversed(run.usage[initial_calls:] if run else [])
                    if retained_metrics(call)
                ),
                {},
            )
            progress: dict[str, Any] = {}
            if run is not None and run.method == "exact":
                with suppress(Exception):
                    progress = native_progress(run.state())
            safe_message = (
                f"{progress['total']} 屏中 {progress['rejected']} 屏未通过审图，"
                "整组暂未交付。请查看逐屏原因后重试。"
                if progress.get("rejected")
                else "本次复刻暂未完成，进度已保留。可按原方案重新复刻整组。"
            )
            return ProviderResult(
                outcome=ProviderOutcome.OUTCOME_UNKNOWN
                if isinstance(exc, ReplicaImageOutcomeUnknown)
                else ProviderOutcome.FAILED,
                error_code=getattr(exc, "code", "REPLICA_SKILL_BLOCKED"),
                error_message=(
                    "生图结果尚未核实，已停止自动重发。请稍后查看任务，避免重复提交。"
                    if isinstance(exc, ReplicaImageOutcomeUnknown)
                    else exc.message
                    if isinstance(
                        exc,
                        (
                            ReplicaInputTooLarge,
                            ReplicaAnalysisUnavailable,
                            ReplicaPlanAuditRejected,
                            ReplicaCanvasMismatch,
                        ),
                    )
                    else safe_message
                ),
                retryable=False,
                usage_reported=run is not None and accounting["reported"],
                raw_usage={
                    **accounting,
                    "native_calls": run.usage[initial_calls:] if run else [],
                    "metrics": {"native_error": str(exc)[:1200], **diagnostics},
                },
                actual_cost_micros=accounting["actual_cost_micros"],
                estimated_cost_micros=accounting["estimated_cost_micros"],
            )



async def _execute_pages(
    provider: Any, run: Any, request: Any, ordinal: int
) -> list[str]:
    from . import replica_direct_delivery as direct

    direct.activate(run)
    await run.checkpoint()
    limit = ordinal
    for index in range(min(limit + 1, len(run.state()["modules"]))):
        state = run.state()
        state["module_index"] = index
        record, module = state["modules"][index], state["plan"]["modules"][index]
        if record["status"] == "GENERATED":
            continue
        native = record.get("request")
        ledger_path = run.root / "invocations.json"
        ledger = read_json(ledger_path) if ledger_path.exists() else {}
        prior = ledger.get(native.get("token"), {}) if native else {}
        if (
            prior.get("state") in {"rejected", "canvas_rejected"}
            and prior.get("job_id") != request.job_id
            and prior.get("target") == module["id"]
        ):
            record.setdefault("previous_requests", []).append(record.pop("request"))
            native = None
        if native is None:
            native = direct.generation_request(run, state, index)
            record.update(
                status="AWAITING_ARTWORK",
                request=native,
                attempts=[{"token": native["token"]}],
            )
        state["state"] = "AWAITING_ARTWORK"
        write_json(run.root / "direct-session.json", state)
        await provider._save(run, request.job_id)
        image = await provider._render(
            run,
            request,
            native,
            native["prompt"],
            [Path(p) for p in native["reference_images"]],
            [native["canvas"]["width"], native["canvas"]["height"]],
            module["id"],
        )
        record.update(direct.inspect_artwork(run, str(image), module["output_canvas"]))
        record["status"] = "GENERATED"
        write_json(run.root / "direct-session.json", state)
        await provider._save(run, request.job_id)
    direct.validate_direct_state(run)
    state = run.state()
    if any(r["status"] != "GENERATED" for r in state["modules"]):
        return [r["artwork"] for r in state["modules"][: limit + 1]]
    state.update(state="DELIVERED", module_index=len(state["modules"]))
    write_json(run.root / "direct-session.json", state)
    write_json(
        run.root / "direct-delivery.json",
        {
            "delivery_policy": direct.POLICY,
            "review_status": "NOT_REVIEWED",
            "plan_sha256": state["plan_sha256"],
            "modules": [
                {k: r[k] for k in ("id", "artwork", "sha256", "size", "review_status")}
                for r in state["modules"]
            ],
        },
    )
    return [r["artwork"] for r in state["modules"]]

