"""Complete physical style evidence before planning; resume the failed stage.

The immutable native Skill still owns all workflow transitions and plan audits.
This adapter materializes crop corrections before a fresh pixel review, instead
of trying to repair absent generation references by rewriting page copy.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .replica_native import (
    NativeReplicaRun,
    ReplicaNativeError,
    digest,
    read_json,
    write_json,
)

VERSION = "style-physical-evidence-v1"
CURSOR = "style-analysis-cursor.json"
PROVENANCE = "style-crop-provenance.json"
FROZEN_ANALYSIS = (
    "overview_detection",
    "source_content_analysis",
    "narrative_logic",
    "source_semantics",
    "benchmark_sequence",
)
FLAGS = (
    "source_product_presence",
    "source_brand_presence",
    "source_packaging_presence",
    "source_logo_presence",
    "source_sku_presence",
    "competitor_presence",
    "source_copy_presence",
    "source_environment_presence",
)


class StyleEvidenceInvalid(ReplicaNativeError):
    code = "REPLICA_STYLE_EVIDENCE_INVALID"
    message = "部分参考步骤缺少经过复查的真实风格裁图，已有分析已保留，可继续修正。"


def revision_checkpoint(payload: dict[str, Any]) -> bool:
    snapshot = payload.get("_analysis_checkpoint", {})
    record = snapshot.get("files", {}).get(CURSOR, {})
    value = record.get("text")
    if (
        snapshot.get("method") != "style"
        or not isinstance(value, str)
        or digest(value.encode()) != record.get("sha256")
    ):
        return False
    try:
        cursor = json.loads(value)
    except ValueError:
        return False
    audit = cursor.get("last_plan_audit") if isinstance(cursor, dict) else None
    return bool(
        isinstance(cursor, dict)
        and cursor.get("version") == VERSION
        and cursor.get("stage") == "plan"
        and isinstance(audit, dict)
        and audit.get("pass") is False
    )


def crop_errors(
    analysis: dict[str, Any], provenance: dict[str, Any], references: dict[str, Any]
) -> list[str]:
    """Bind every source step to real crops within its physical source panel."""
    errors: list[str] = []
    panels = {p["panel_id"]: p for p in analysis["overview_detection"]["panels"]}
    steps = analysis["source_content_analysis"]["sequence"]
    step_ids = {s["id"] for s in steps}
    usable = []
    for unit in analysis.get("units", []):
        uid = unit.get("id", "?")
        path = Path(unit.get("source_crop_path", ""))
        record = provenance.get(str(path))
        if (
            not record
            or not path.is_file()
            or digest(path.read_bytes()) != record["crop_sha256"]
        ):
            errors.append(f"{uid}: crop needs server-created physical provenance")
            continue
        source = references.get(unit.get("reference_input_id"))
        if (
            not source
            or record["source_path"] != source["path"]
            or record["source_sha256"] != source["sha256"]
        ):
            errors.append(f"{uid}: crop must come from its registered reference")
            continue
        if (
            any(unit.get(flag) is not False for flag in FLAGS)
            or unit.get("review_status") != "visual_model"
        ):
            errors.append(
                f"{uid}: fresh visual review must confirm all contamination flags"
            )
            continue
        bound = unit.get("source_content_step_ids")
        if (
            not isinstance(bound, list)
            or not bound
            or not set(bound).issubset(step_ids)
        ):
            errors.append(f"{uid}: bind actual known source_content_step_ids")
            continue
        usable.append((unit, record))
    for step in steps:
        matched = False
        for unit, record in usable:
            if step["id"] not in unit["source_content_step_ids"]:
                continue
            for pid in step.get("source_panel_ids", []):
                panel = panels.get(pid)
                if (
                    not panel
                    or unit.get("reference_input_id") != panel["reference_input_id"]
                ):
                    continue
                left, top, right, bottom = record["bbox"]
                pl, pt, pr, pb = panel["bbox"]
                if pl <= left < right <= pr and pt <= top < bottom <= pb:
                    matched = True
        if not matched:
            errors.append(
                f"{step['id']}: missing reviewed crop inside its source panel"
            )
    return errors


class StyleReplicaRun(NativeReplicaRun):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.method != "style":
            raise ReplicaNativeError("Style analysis only supports style replication")
        self.cursor: dict[str, Any] = {"version": VERSION}
        self.context: dict[str, Any] = {}
        self.on_checkpoint: Any = None
        self._restored = False

    def cli(self, command: str, **arguments: Any) -> dict[str, Any]:
        result = super().cli(command, **arguments)
        stage = {
            "compile-visual-passport": "facts",
            "register-product-facts": "plan",
        }.get(command)
        if stage:
            self.cursor["stage"] = stage
            write_json(self.root / CURSOR, self.cursor)
        return result

    def crop(self, source: Path, bbox: list[int], target: Path) -> Path:
        path = super().crop(source, bbox, target)
        if path.name.startswith("style-"):
            file = self.root / PROVENANCE
            rows = read_json(file) if file.exists() else {}
            rows[str(path)] = {
                "source_path": str(source.resolve()),
                "source_sha256": digest(source.read_bytes()),
                "bbox": bbox,
                "crop_sha256": digest(path.read_bytes()),
            }
            write_json(file, rows)
        return path

    async def checkpoint(self) -> None:
        if not self.cursor.get("stage"):
            return
        write_json(self.root / CURSOR, self.cursor)
        write_json(self.root / "context.json", self.context)
        if self.on_checkpoint is not None:
            await self.on_checkpoint()

    async def restore(self, snapshot: dict[str, Any]) -> None:
        prefix = f"{self.workspace_id}/replica/{self.document_id}/"
        if any(
            "object_key" in r and not r["object_key"].startswith(prefix)
            for r in snapshot["files"].values()
        ):
            raise ReplicaNativeError("Style analysis snapshot belongs to another task")
        await super().restore(snapshot)
        self.cursor = read_json(self.root / CURSOR)
        if self.cursor.get("version") != VERSION:
            raise ReplicaNativeError(
                "Style analysis protocol changed; preserve the previous checkpoint"
            )
        self._restored = True

    def _apply_specs(self, analysis: dict[str, Any]) -> bool:
        specs = analysis.pop("crop_specs", [])
        if not isinstance(specs, list):
            raise StyleEvidenceInvalid("crop_specs must be a list")
        units = {u["id"]: u for u in analysis.get("units", [])}
        refs = {
            r["id"]: r
            for r in self.state()["inputs"]
            if r["role"] == "benchmark_reference"
        }
        seen = set()
        changed = False
        for spec in specs:
            uid = spec.get("id", "")
            rid = spec.get("reference_input_id")
            if (
                not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", uid)
                or uid in seen
                or uid not in units
                or rid not in refs
            ):
                raise StyleEvidenceInvalid(
                    "crop_specs must cite unique units and registered references"
                )
            seen.add(uid)
            source = self.path(refs[rid]["path"])
            if digest(source.read_bytes()) != refs[rid]["sha256"]:
                raise StyleEvidenceInvalid("Original reference bytes changed")
            target = self.root / "crops" / f"style-{uid}.png"
            old = digest(target.read_bytes()) if target.exists() else None
            self.crop(source, spec["bbox"], target)
            units[uid]["source_crop_path"] = str(target)
            units[uid]["reference_input_id"] = rid
            changed |= old != digest(target.read_bytes())
        return changed

    async def _review_crops(self, analysis: dict[str, Any]) -> dict[str, Any]:
        baseline = deepcopy(self.cursor.get("source_analysis", analysis))
        self.cursor.update(
            stage="crop_review", source_analysis=baseline, candidate=analysis
        )
        errors: list[str] = []
        for attempt in range(self.contract_attempts):
            await self.checkpoint()
            reviewed = await super().ask(
                f"style-crop-review-{attempt}",
                "Inspect ACTUAL sanitized crop pixels and physical source panels. "
                "Return complete analysis. Preserve overview_detection, "
                "source_content_analysis, narrative_logic, source_semantics and "
                "benchmark_sequence exactly. Review all contamination flags honestly. "
                "Every step needs a useful safe crop from its OWN physical panel; "
                "do not bind one swatch to unrelated panels. Full analysis panels "
                "support global composition and reading path. Crops supplement them "
                "with actual type/material/action evidence where available, without "
                "readable source wording, products, logos or literal environments. "
                "Partial unreadable glyph/stroke fragments and face-free/product-free "
                "action details are allowed. For recrops return crop_specs: "
                "[{id,reference_input_id,bbox:[l,t,r,b]}] in ORIGINAL coordinates, "
                "plus corresponding units. The server crops first; another fresh "
                "pixel review inspects those new bytes. Never declare unseen crops "
                "safe or edit source steps to hide missing coverage.",
                {
                    "analysis": analysis,
                    "workflow": self.state(),
                    "validation_errors": errors,
                },
            )
            if any(reviewed.get(k) != baseline.get(k) for k in FROZEN_ANALYSIS):
                errors = [
                    "Preserve observed physical panels, source steps and narrative"
                ]
                continue
            changed = self._apply_specs(reviewed)
            self.cursor["candidate"] = analysis = reviewed
            await self.checkpoint()
            if changed:
                errors = ["New physical crop bytes require a fresh visual review"]
                continue
            provenance = (
                read_json(self.root / PROVENANCE)
                if (self.root / PROVENANCE).exists()
                else {}
            )
            refs = {
                r["id"]: r
                for r in self.state()["inputs"]
                if r["role"] == "benchmark_reference"
            }
            errors = crop_errors(reviewed, provenance, refs)
            if not errors:
                return reviewed
            corrected = await super().ask(
                f"style-crop-repair-{attempt}",
                "Correct only missing/invalid crops in validation_errors. Return "
                "COMPLETE analysis and crop_specs: "
                "[{id,reference_input_id,bbox:[l,t,r,b]}] for new/replaced crops, "
                "using ORIGINAL reference pixels. Preserve panel metadata, content "
                "steps, narrative and source semantics exactly. Bind useful actual "
                "type/material/action crops to their own source_content_step_ids. "
                "Never just relabel swatches, claim PASS or rewrite page copy.",
                {
                    "analysis": analysis,
                    "validation_errors": errors,
                    "workflow": self.state(),
                },
            )
            if any(corrected.get(k) != baseline.get(k) for k in FROZEN_ANALYSIS):
                errors = ["Crop correction changed frozen source observations"]
                continue
            self._apply_specs(corrected)
            self.cursor["candidate"] = analysis = corrected
            await self.checkpoint()
        raise StyleEvidenceInvalid("; ".join(errors))

    async def ask(
        self, stage: str, instruction: str, context: Any, **kwargs: Any
    ) -> dict[str, Any]:
        if stage == "style-crop-review":
            return await self._review_crops(context["analysis"])
        if stage.startswith(("style-plan", "style-facts")):
            self.cursor["stage"] = "facts" if stage == "style-facts" else "plan"
            await self.checkpoint()
        value = await super().ask(stage, instruction, context, **kwargs)
        if stage.startswith("style-plan-audit"):
            self.cursor["last_plan_audit"] = value
        await self.checkpoint()
        return value

    async def prepare(
        self, payload: dict[str, Any], records: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if not self._restored:
            result = await super().prepare(payload, records)
        else:
            for role, ids in (
                ("product", payload["product_asset_ids"]),
                ("reference", [r["asset_id"] for r in payload["references"]]),
            ):
                for index, asset_id in enumerate(ids):
                    path = self.root / "inputs" / f"{role}-{index:02}.img"
                    if (
                        not path.is_file()
                        or digest(path.read_bytes()) != records[asset_id][2]
                    ):
                        raise ReplicaNativeError("Style input bytes or order changed")
            for field, key in (
                ("user_facts", "facts"),
                ("references", "references"),
                ("language", "language"),
                ("platform", "platform_code"),
            ):
                if self.context.get(field) != payload.get(key):
                    raise ReplicaNativeError("Style facts or input context changed")
            stage = self.cursor.get("stage")
            if stage not in {"crop_review", "facts", "plan"}:
                raise ReplicaNativeError(
                    "This style checkpoint cannot restart analysis"
                )
            if stage == "crop_review":
                analysis = await self._review_crops(self.cursor["candidate"])
                template = self.root / "contracts/reference-analysis.json"
                write_json(template, analysis)
                if self.state()["state"] in {
                    "ROUTE_CLASSIFIED",
                    "REFERENCE_DECOMPOSED",
                }:
                    self.cli(
                        "compile-reference-crops", workspace=self.run, analysis=template
                    )
                if self.state()["state"] == "REFERENCE_DECOMPOSED":
                    self.cli(
                        "compile-visual-passport", workspace=self.run, analysis=template
                    )
            if self.state()["state"] == "VISUAL_PASSPORT_READY":
                await self.contract(
                    "style-facts",
                    "Return native facts,evidence_inventory,product_category "
                    "and palette_contract. "
                    "Include concrete geometry (>=3 facts) and product evidence ids. "
                    "User copy is authorized; reference claims aren't facts.",
                    {
                        "workflow": self.state(),
                        "user_context": self.context,
                        "geometry": read_json(self.root / "identity-segmentation.json")[
                            "product_geometry"
                        ],
                    },
                    "register-product-facts",
                    "facts",
                )
            if self.state()["state"] not in {
                "PRODUCT_FACTS_READY",
                "PLAN_AUDIT_REQUIRED",
            }:
                raise ReplicaNativeError(
                    "Style recovery cannot restart an image execution"
                )
            result = await self.finish_style_planning(
                self.cursor.get("last_plan_audit")
            )
        self.cursor["stage"] = "approved"
        await self.checkpoint()
        return result
