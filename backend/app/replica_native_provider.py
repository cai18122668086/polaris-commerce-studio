# ruff: noqa: E501
"""Image provider driven by the original replica Skill state machines."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from PIL import Image

from .models import JobItemRecord, JobRecord, ReplicaDocumentRecord, utc_now
from .provider import ProviderArtifact, ProviderOutcome, ProviderRequest, ProviderResult
from .replica_native import (
    NativeReplicaRun,
    ReplicaNativeError,
    digest,
    native_accounting,
    read_json,
    write_json,
)


class ReplicaImageOutcomeUnknown(ReplicaNativeError):
    code = "PROVIDER_OUTCOME_UNKNOWN"


class NativeReplicaProvider:
    name = "replica-native"
    model = "gpt-image-2"
    pricing_version = "replica-native-20260923"

    def __init__(self, session_factory: Any, gateway: Any, storage: Any) -> None:
        self.session_factory, self.gateway, self.storage = (
            session_factory,
            gateway,
            storage,
        )

    def _load(self, request: ProviderRequest) -> tuple[dict[str, Any], str, int]:
        with self.session_factory() as session:
            job = session.get(JobRecord, request.job_id)
            item = session.get(JobItemRecord, request.job_item_id)
            document_id = job.configuration.get("replica_session_id") if job else None
            row = (
                session.get(ReplicaDocumentRecord, document_id) if document_id else None
            )
            if (
                row is None
                or item is None
                or job is None
                or row.workspace_id != request.workspace_id
                or job.id not in row.payload.get("job_ids", [])
                or job.configuration.get("settings", {}).get("replica_plan_hash")
                != row.payload.get("plan_hash")
                or not row.payload.get("confirmed_instructions_hash")
            ):
                raise ReplicaNativeError("未找到当前工作区已确认的原生复刻方案。")
            return dict(row.payload), row.id, item.ordinal

    async def _save(
        self, run: NativeReplicaRun, job_id: str, *, delivery: list[str] | None = None
    ) -> None:
        snapshot = await run.snapshot()
        with self.session_factory() as session:
            row = session.get(
                ReplicaDocumentRecord, run.document_id, with_for_update=True
            )
            values = dict(row.payload)
            executions = dict(values.get("native_executions", {}))
            executions[job_id] = {
                "snapshot": snapshot,
                "delivery": delivery or [],
                "state": run.state()["state"],
            }
            row.payload = {**values, "native_executions": executions}
            row.updated_at = utc_now()
            session.commit()

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        run = None
        initial_calls = 0
        try:
            values, document_id, ordinal = self._load(request)
            execution = values.get("native_executions", {}).get(request.job_id, {})
            snapshot = execution.get("snapshot") or values["native_snapshot"]
            run = NativeReplicaRun(
                values["replication_method"],
                document_id,
                request.workspace_id,
                self.gateway,
                self.storage,
                root=Path(snapshot["root"]),
            )
            await run.restore(snapshot)
            initial_calls = len(run.usage)
            delivery = execution.get("delivery", [])
            if not delivery:
                if ordinal != 0:
                    raise ReplicaNativeError("前序复刻尚未通过完整验收。")
                if run.method == "exact":
                    delivery = await self._exact(run, request)
                else:
                    delivery = await self._style(run, request)
                if len(delivery) != len(values["plans"]):
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
                    "native_visual_audited": True,
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
            return ProviderResult(
                outcome=ProviderOutcome.OUTCOME_UNKNOWN
                if isinstance(exc, ReplicaImageOutcomeUnknown)
                else ProviderOutcome.FAILED,
                error_code=getattr(exc, "code", "REPLICA_SKILL_BLOCKED"),
                error_message=(
                    "生图结果尚未核实，已停止自动重发。请稍后查看任务，避免重复提交。"
                    if isinstance(exc, ReplicaImageOutcomeUnknown)
                    else "本次复刻暂未完成，进度已保留。可按原方案重新复刻整组。"
                ),
                retryable=False,
                usage_reported=run is not None and accounting["reported"],
                raw_usage={
                    **accounting,
                    "native_calls": run.usage[initial_calls:] if run else [],
                    "metrics": {"native_error": str(exc)[:1200]},
                },
                actual_cost_micros=accounting["actual_cost_micros"],
                estimated_cost_micros=accounting["estimated_cost_micros"],
            )

    async def _render(
        self,
        run: NativeReplicaRun,
        request: ProviderRequest,
        native: dict[str, Any],
        prompt: str,
        paths: list[Path],
        canvas: list[int],
        key: str,
    ) -> Path:
        from .xinghe_agent import ImageEditRequest

        ledger_path = run.root / "invocations.json"
        ledger = read_json(ledger_path) if ledger_path.exists() else {}
        token = native["token"]
        prior = ledger.get(token)
        if prior:
            if prior.get("path") and run.path(prior["path"]).is_file():
                if digest(run.path(prior["path"]).read_bytes()) != prior.get("sha256"):
                    raise ReplicaNativeError(
                        "已记录的生图产物哈希发生变化，已停止恢复。"
                    )
                return run.path(prior["path"])
            raise ReplicaImageOutcomeUnknown(
                "此令牌的生图结果尚未核实，系统不会自动重复调用。请新建明确的重试任务。"
            )
        ledger[token] = {"state": "invoked", "job_id": request.job_id, "target": key}
        write_json(ledger_path, ledger)
        # The invocation fence is durable BEFORE the network call.
        await self._save(run, request.job_id)
        before = getattr(self.gateway, "external_network_request_count", None)
        result = await self.gateway.edit(
            ImageEditRequest(
                workspace_id=request.workspace_id,
                job_id=request.job_id,
                job_item_id=request.job_item_id,
                attempt_id=request.attempt_id,
                page_number=1,
                group_key=key,
                sources=run.sources(paths),
                prompt=prompt,
                quality="high",
                idempotency_key=f"replica-native:{request.job_id}:{token}",
                size=f"{canvas[0]}x{canvas[1]}",
                preserve_provider_artifact=True,
                single_dispatch=False,
            )
        )
        after = getattr(self.gateway, "external_network_request_count", None)
        requests = (
            max(1, after - before) if type(before) is int and type(after) is int else 1
        )
        run.record_usage(result, "image", requests)
        run.usage[-1].update(
            http_status=result.http_status,
            error_code=result.error_code,
            metrics=(result.raw_usage or {}).get("metrics", {}),
        )
        if result.outcome == ProviderOutcome.OUTCOME_UNKNOWN:
            raise ReplicaImageOutcomeUnknown(
                result.error_message or "生图结果尚未核实。"
            )
        if result.outcome != ProviderOutcome.SUCCEEDED or result.artifact is None:
            ledger[token] = {
                **ledger[token],
                "state": "rejected",
                "http_status": result.http_status,
                "error_code": result.error_code,
            }
            write_json(ledger_path, ledger)
            await self._save(run, request.job_id)
            raise ReplicaNativeError(result.error_message or "生图未返回可核实产物。")
        if result.artifact.locally_resampled:
            raise ReplicaNativeError("供应商返回了本地缩放产物，原生画幅验收未通过。")
        path = run.root / "artwork" / f"{request.job_id}-{key}-{token}.png"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(result.artifact.payload)
        ledger[token] = {
            **ledger[token],
            "state": "returned",
            "path": str(path),
            "sha256": digest(path.read_bytes()),
        }
        write_json(ledger_path, ledger)
        await self._save(run, request.job_id)
        return path

    async def _exact(
        self, run: NativeReplicaRun, request: ProviderRequest
    ) -> list[str]:
        while run.state()["state"] not in {"SET_COMPLETE", "FINALIZED"}:
            state = run.state()
            if state["state"] in {"READY", "REPAIR_PREPARED"}:
                path = run.root / "request.json"
                run.cli("generate-next", session=run.run / "session.json", out=path)
                await self._save(run, request.job_id)
            native = read_json(run.root / "request.json")
            if run.state()["state"] == "AWAITING_ARTWORK":
                canvas = native["canvas"]
                image = await self._render(
                    run,
                    request,
                    native,
                    native["prompt"],
                    [Path(p) for p in native["reference_images"]],
                    [canvas["width"], canvas["height"]],
                    native["module_id"],
                )
                run.cli(
                    "record-artwork",
                    session=run.run / "session.json",
                    token=native["token"],
                    image=image,
                )
                await self._save(run, request.job_id)
            if run.state()["state"] == "AWAITING_AUDIT":
                state = run.state()
                module = state["plan"]["modules"][state["module_index"]]
                artwork = state["modules"][state["module_index"]]["attempts"][-1][
                    "artwork"
                ]
                await run.contract(
                    "exact-pixel-audit-" + native["token"],
                    "Fresh side-by-side PIXEL audit. Return judgment schema, unique observations/evidence per dimension. "
                    "Also compare actual product cross-section, ratios, segments, layers, exact label spelling and complete numerals. "
                    "product_geometry_match must truthfully reflect actual pixels; list all material deltas. No all-pass template.",
                    {
                        "module": module,
                        "artwork": artwork,
                        "artwork_sha256": digest(Path(artwork).read_bytes()),
                        "geometry": state["input"]["product_geometry"],
                        "user_context": run.context,
                    },
                    "audit-current",
                    "judgment",
                    schemas=("judgment.schema.json",),
                    paths=[
                        *sorted((run.root / "inputs").glob("product-*")),
                        Path(module["reference_path"]),
                        Path(artwork),
                    ],
                )
                await self._save(run, request.job_id)
            state = run.state()
            if state["state"] == "REPAIR_READY":
                await run.contract(
                    "exact-repair-" + native["token"],
                    "Return {material_failures:[every observed major_mismatches in exact order],single_edit_instruction:one integrated targeted repair}. Preserve correct regions and product identity.",
                    state,
                    "prepare-repair",
                    "repair-plan",
                )
            elif state["state"] not in {"READY", "REPAIR_PREPARED", "SET_COMPLETE"}:
                raise ReplicaNativeError("一比一原生状态无法继续：" + state["state"])
        if run.state()["state"] != "FINALIZED":
            run.cli(
                "finalize",
                session=run.run / "session.json",
                output=run.root / "delivery.json",
            )
        return [x["artwork"] for x in read_json(run.root / "delivery.json")["outputs"]]

    @staticmethod
    def _style_render_inputs(
        run: NativeReplicaRun, native: dict[str, Any], handoff: dict[str, Any], key: str
    ) -> tuple[str, list[Path]]:
        prompt = Path(handoff["prompt_path"]).read_text(encoding="utf-8-sig")
        paths = [Path(p) for p in handoff["referenced_image_paths"]]
        if native.get("revision_index", 0):
            state = run.state()
            audit = next(
                (
                    row
                    for row in reversed(state["audits"])
                    if row["target_id"] == key and row["pass"] is False
                ),
                None,
            )
            artwork = next(
                (row for row in reversed(state["artwork"]) if row["target_id"] == key),
                None,
            )
            if audit is None or artwork is None:
                raise ReplicaNativeError("修复缺少当前目标的真实失败审计或初稿。")
            image = run.path(artwork["path"])
            if digest(image.read_bytes()) != audit["artwork_sha256"]:
                raise ReplicaNativeError("修复初稿与失败审计哈希不一致。")
            paths.append(image)
            prompt += (
                "\n【本次唯一一次修复】最后一张参考图是当前商品初稿，不是风格参考。保留已正确的画面、产品身份和实体标签，只修复下列实际差异；全部文字仍由模型原生生成，禁止后期叠字。\n"
                + json.dumps(audit["evidence"], ensure_ascii=False)
            )
        return prompt, paths

    async def _style(
        self, run: NativeReplicaRun, request: ProviderRequest
    ) -> list[str]:
        state = run.state()
        if state["state"] == "DELIVERED":
            return [
                x["path"]
                for x in read_json(run.run / "artifacts/delivery-manifest.json")[
                    "files"
                ]
            ]
        detail = state["route"] == "DETAIL_PAGE"
        pool_name, target_arg = (
            ("groups", "group-id") if detail else ("units", "unit-id")
        )
        suffix = "pair" if detail else "single"
        for key in state[pool_name]:
            while run.state()[pool_name][key]["status"] != "accepted":
                state = run.state()
                status = state[pool_name][key]["status"]
                if status == "failed_continue":
                    raise ReplicaNativeError(
                        "风格复刻在一次修复后仍未通过80%及商品一致性验收。"
                    )
                if status == "revision_allowed":
                    run.cli(
                        "prepare-revision" if detail else "prepare-single-revision",
                        workspace=run.run,
                        **{target_arg: key},
                    )
                    status = "pending"
                if status == "pending":
                    run.cli(
                        f"generate-{suffix}-request",
                        workspace=run.run,
                        **{target_arg: key},
                    )
                    await self._save(run, request.job_id)
                native_path = run.run / f"artifacts/generation-request-{key}.json"
                native = read_json(native_path)
                if run.state()[pool_name][key]["status"] == "awaiting_artwork":
                    # Run the source adapter's exact generation gate and prompt compiler;
                    # use Polaris' existing Artflow/Tengli transport for credentials/failover.
                    handoff = await asyncio.to_thread(
                        self._style_handoff, run, native_path
                    )
                    prompt, image_paths = self._style_render_inputs(
                        run, native, handoff, key
                    )
                    image = await self._render(
                        run,
                        request,
                        native,
                        prompt,
                        image_paths,
                        native["render_contract"]["native_generation_size"],
                        key,
                    )
                    receipt = run.root / "artwork" / (image.stem + ".receipt.json")
                    self._provenance(run, native_path, image, receipt)
                    run.cli(
                        f"record-{suffix}-artwork",
                        workspace=run.run,
                        artwork=image,
                        **{target_arg: key, "render-receipt": receipt},
                    )
                    await self._save(run, request.job_id)
                state = run.state()
                item = state[pool_name][key]
                if item["status"] == "audit_required":
                    artwork = item["artwork"]["path"]
                    await run.contract(
                        "style-pixel-audit-" + native["token"],
                        "Inspect actual artwork against all product originals and mapped reference panels. Return native audit.schema.json. "
                        "review_kind=visual_model, artwork_sha256 matches supplied bytes, truthful per-mechanism scores and dimensions, "
                        "density_checks/transition_checks, product_identity and fact_safety. All eight scores must be >=0.8 to pass; "
                        "identity/shape/label/numeral or contamination errors are hard failures. Do not forge passing evidence.",
                        {"workflow": state, "request": native, "current_target": key},
                        f"audit-{suffix}",
                        "audit",
                        schemas=("audit.schema.json",),
                        **{target_arg: key},
                        paths=[
                            *sorted((run.root / "inputs").glob("product-*")),
                            *[
                                Path(p["source_crop_path"])
                                for p in state["overview_detection"]["panels"]
                            ],
                            Path(artwork),
                        ],
                    )
                    await self._save(run, request.job_id)
            run.cli(f"accept-{suffix}", workspace=run.run, **{target_arg: key})
        if run.state()["state"] not in {"FINALIZED", "DELIVERED"}:
            await run.contract(
                "style-global-audit",
                "Fresh full-set audit: check complete order, identity, visual consistency, no missing/extra screens or contamination. Return {review_kind:visual_model,pass,ordered_ids,evidence:[concrete set findings]}. Fail honestly.",
                run.state(),
                "audit-global",
                "audit",
                paths=[
                    Path(x["artwork"]["path"]) for x in run.state()[pool_name].values()
                ],
            )
            run.cli("finalize", workspace=run.run)
        if run.state()["state"] != "DELIVERED":
            run.cli(
                "export-single-screens" if detail else "export-single",
                workspace=run.run,
            )
        return [
            x["path"]
            for x in read_json(run.run / "artifacts/delivery-manifest.json")["files"]
        ]

    @staticmethod
    def _style_handoff(run: NativeReplicaRun, native_path: Path) -> dict[str, Any]:
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                str(run.skill_root / "scripts/imagegen_adapter.py"),
                "--workspace",
                str(run.run),
                "--request",
                str(native_path),
                "--output",
                str(run.root / "native-output.png"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            shell=False,
        )
        if result.returncode:
            raise ReplicaNativeError((result.stderr or result.stdout)[-3000:])
        import json

        return json.loads(result.stdout)

    @staticmethod
    def _provenance(
        run: NativeReplicaRun, native_path: Path, image: Path, receipt: Path
    ) -> None:
        import subprocess
        import sys

        if receipt.exists():
            return
        result = subprocess.run(
            [
                sys.executable,
                str(run.skill_root / "scripts/render_provenance.py"),
                "--request",
                str(native_path),
                "--native-output",
                str(image),
                "--artwork",
                str(image),
                "--output",
                str(receipt),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            shell=False,
        )
        if result.returncode:
            raise ReplicaNativeError((result.stderr or result.stdout)[-3000:])
