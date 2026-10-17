# ruff: noqa: E501
"""Native Aurora domestic detail v4.3 Harness boundary.

The detail provider keeps the durable Polaris job model, but every storyboard
and generation transition is delegated to the bundled Skill Harness.  This
module contains only the subprocess boundary and the small adapter needed to
turn the existing, fact-grounded job payload into the v4.3 input contract.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import default_aurora_work_root, default_skill_root
from .domestic_detail.contracts import (
    normalize_native_plan_for_harness as normalize_native_plan_for_harness,
)
from .domestic_detail.plans import resolve_native_plan
from .skill_runtime import SkillManifestRegistry

DETAIL_SKILL_ID = "aurora-domestic-ecommerce-detail-page"
DETAIL_VERSION = "4.3.0"


class AuroraDetailHarnessError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AuroraDetailHarnessRunner:
    skill_root: Path = default_skill_root(DETAIL_SKILL_ID)
    timeout_seconds: float = 90

    def run(
        self,
        command: str,
        workspace: Path,
        arguments: Mapping[str, str | Path],
    ) -> dict[str, Any]:
        try:
            SkillManifestRegistry.bundled().verify_source(DETAIL_SKILL_ID, self.skill_root)
        except Exception as exc:
            raise AuroraDetailHarnessError("AURORA_DETAIL_SOURCE_MISMATCH", str(exc)) from exc
        allowed = {
            "start": {"input", "session"},
            "lock-identity": {"session", "identity"},
            "compile-plan": {"session", "plan"},
            "authorize": {"session", "approval-text", "approved-module-count", "approved-pair-canvas-aspect-ratio", "approval-document-sha256", "delivery-mode"},
            "generate-next": {"session", "out"},
            "record-generation": {"session", "token", "image"},
            "audit-pair": {"session", "judgment"},
            "prepare-repair": {"session", "repair-plan"},
            "assemble": {"session", "output"},
            "audit-long-page": {"session", "judgment"},
            "finalize": {"session", "output", "approval-text"},
            "auto-finalize": {"session", "output"},
            "inspect": {"session"},
        }.get(command)
        if allowed is None:
            raise AuroraDetailHarnessError("HARNESS_COMMAND_NOT_ALLOWED", command)
        if set(arguments) - allowed:
            raise AuroraDetailHarnessError(
                "HARNESS_ARGUMENT_NOT_ALLOWED",
                f"Unsupported arguments for {command}: {sorted(set(arguments) - allowed)}",
            )
        root = workspace.resolve()
        root.mkdir(parents=True, exist_ok=True)
        argv = [sys.executable, str(self.harness_path), command]
        for name, raw in arguments.items():
            value = str(raw)
            if name not in {"approval-text", "token", "delivery-mode", "approved-module-count", "approved-pair-canvas-aspect-ratio", "approval-document-sha256"}:
                value = str(self._workspace_path(root, Path(value)))
            argv.extend((f"--{name}", value))
        try:
            completed = subprocess.run(
                argv,
                cwd=self.skill_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AuroraDetailHarnessError("HARNESS_TIMEOUT", "Aurora detail Harness timed out") from exc
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            detail = completed.stderr.strip()[-1000:]
            try:
                error_payload = json.loads(completed.stderr)
                detail = str(error_payload.get("error") or detail)
            except json.JSONDecodeError:
                pass
            raise AuroraDetailHarnessError(
                "HARNESS_INVALID_OUTPUT",
                f"Aurora detail Harness did not return JSON (exit={completed.returncode}; stderr={detail})",
            ) from exc
        if completed.returncode != 0 or result.get("status") == "BLOCKED":
            raise AuroraDetailHarnessError(
                "HARNESS_BLOCKED",
                str(result.get("error") or "Aurora detail Harness blocked the transition"),
            )
        return result

    @property
    def harness_path(self) -> Path:
        path = (self.skill_root / "scripts" / "harness.py").resolve()
        if not path.is_file() or self.skill_root.resolve() not in path.parents:
            raise AuroraDetailHarnessError("HARNESS_MISSING", "Aurora detail Harness is missing")
        return path

    @staticmethod
    def _workspace_path(root: Path, value: Path) -> Path:
        candidate = value if value.is_absolute() else root / value
        resolved = candidate.resolve()
        if resolved != root and root not in resolved.parents:
            raise AuroraDetailHarnessError(
                "HARNESS_PATH_OUTSIDE_WORKSPACE",
                "Harness file arguments must remain inside the job workspace",
            )
        return resolved


def write_contract(path: Path, value: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def detail_workspace(job_id: str, *, root: Path | None = None) -> Path:
    if not job_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in job_id):
        raise AuroraDetailHarnessError("INVALID_JOB_ID", "Invalid detail job identifier")
    base = (root or (default_aurora_work_root() / "domestic-detail")).resolve()
    workspace = (base / job_id).resolve()
    if base != workspace and base not in workspace.parents:
        raise AuroraDetailHarnessError("WORKSPACE_ESCAPE", "Detail workspace escaped its root")
    try:
        workspace.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AuroraDetailHarnessError(
            "WORKSPACE_NOT_WRITABLE",
            "Aurora detail workspace is not writable (%s)." % (exc.strerror or type(exc).__name__),
        ) from exc
    return workspace


def _text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def build_native_input(
    settings: Mapping[str, Any],
    *,
    product_images: Sequence[Mapping[str, Any]],
    image_paths: Sequence[str],
) -> dict[str, Any]:
    """Normalize Polaris' compact settings into the v4.3 input contract."""

    facts: list[dict[str, Any]] = []
    raw_facts = settings.get("verified_facts", [])
    if isinstance(raw_facts, list):
        for index, raw in enumerate(raw_facts, start=1):
            if isinstance(raw, Mapping):
                fact = dict(raw)
                fact.setdefault("id", f"F{index:02d}")
                fact.setdefault("text", str(raw.get("value") or raw.get("fact") or "已确认商品事实"))
                fact.setdefault("source_class", "USER_FACT")
                fact.setdefault("evidence_ref", "user_input")
                fact.setdefault("claim_kind", "OTHER")
                fact.setdefault("display_intent", "SHOW_IF_RELEVANT")
                fact.setdefault("user_prominence", "SUPPORTING_POINT")
                fact.setdefault("named_elements", [str(fact["text"])])
            else:
                text = str(raw).strip()
                if not text:
                    continue
                fact = {
                    "id": f"F{index:02d}",
                    "text": text,
                    "source_class": "USER_FACT",
                    "evidence_ref": "user_input",
                    "claim_kind": "OTHER",
                    "display_intent": "SHOW_IF_RELEVANT",
                    "user_prominence": "SUPPORTING_POINT",
                    "named_elements": [text],
                }
            facts.append(fact)
    if not facts:
        facts.append({
            "id": "F01", "text": "以用户提供的真实商品素材为准",
            "source_class": "OBSERVED_PRODUCT_EVIDENCE", "evidence_ref": "product_images",
            "claim_kind": "PRODUCT_IDENTITY", "display_intent": "MUST_SHOW",
            "user_prominence": "CORE_SELLING_POINT", "named_elements": ["真实商品素材"],
        })
    platform = settings.get("platform_profile")
    if not isinstance(platform, Mapping):
        platform = {}
    width = int(platform.get("canvas_width_px") or 1440)
    height = int(platform.get("module_height_px") or 1920)
    profile = {
        "target_platform": str(platform.get("target_platform") or settings.get("platform_code") or "taobao_tmall"),
        "profile_name": str(platform.get("profile_name") or "INTERNAL_REVIEW_1440_3_4"),
        "selection_mode": str(platform.get("selection_mode") or "INTERNAL_ONLY"),
        "selection_rationale": str(platform.get("selection_rationale") or "采用国内详情页移动端 3:4 单屏与相邻 3:8 双屏画布，保证固定窗口切片和连续阅读。"),
        "source": str(platform.get("source") or "INTERNAL_REVIEW_PROFILE"),
        "aspect_ratio": {"width_units": 3, "height_units": 4, "label": "3:4"},
        "canvas_width_px": width,
        "module_height_px": height,
        "safe_margin_px": int(platform.get("safe_margin_px") or 96),
        "slice_height_px": int(platform.get("slice_height_px") or height),
        "format": "PNG",
        "max_file_bytes": platform.get("max_file_bytes"),
        "verification_status": str(platform.get("verification_status") or "INTERNAL_ONLY"),
    }
    # The Harness only permits ADAPTIVE_PLANNED with a verified backend profile;
    # otherwise the explicit internal review profile is the safe contract.
    if profile["selection_mode"] not in {"USER_SPECIFIED", "PLATFORM_VERIFIED", "ADAPTIVE_PLANNED"}:
        profile["selection_mode"] = "USER_SPECIFIED"
    raw_references = settings.get("reference_materials") or []
    references: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_references, start=1):
        if isinstance(raw, Mapping):
            reference = dict(raw)
        else:
            reference = {"id": f"REF{index:02d}", "path": str(raw)}
        reference.setdefault("id", f"REF{index:02d}")
        reference.setdefault("path", str(reference.get("id")))
        reference.setdefault("category", "style_reference")
        reference.setdefault("analysis_status", "ANALYZED")
        unit = {
            "id": f"{reference['id']}-U01",
            "source_region": "完整画面",
            "page_duty": "提供视觉语法参考",
            "visual_carrier": "构图、层级与信息表面",
            "composition_logic": "保留视觉语法，不复制商品、品牌或文案",
            "typography_logic": "保持清晰的中文信息层级",
            "observed_expression_method": "采用参考图的视觉语法并适配当前商品证据。",
        }
        reference.setdefault("analyzed_units", [unit])
        reference.setdefault("observed_expression_methods", [unit["observed_expression_method"]])
        references.append(reference)
    raw_conflicts = settings.get("source_conflicts") or []
    conflicts = [dict(item) for item in raw_conflicts if isinstance(item, Mapping)]
    conflict_scan_value = settings.get("conflict_scan")
    conflict_scan = dict(conflict_scan_value) if isinstance(conflict_scan_value, Mapping) else {}
    conflict_scan.setdefault("status", "CONFLICTS_FOUND" if conflicts else "CLEAR")
    if conflict_scan.get("status") == "NO_MATERIAL_CONFLICTS_REPORTED":
        conflict_scan["status"] = "CONFLICTS_FOUND" if conflicts else "CLEAR"
    conflict_scan.setdefault("scanned_topics", ["identity", "specification", "formula", "performance", "audience", "compliance"])
    conflict_scan["conflict_ids"] = [str(item.get("id")) for item in conflicts]
    return {
        "intake_route": "USER_SELLING_POINT_LED" if settings.get("selling_points") else "PHOTO_TO_PRODUCT_STRATEGY",
        "product_name": str(settings.get("product_name") or "未命名商品"),
        "category": str(settings.get("category") or "国内电商商品"),
        "target_buyer": str(settings.get("target_buyer") or "需要了解商品真实结构与使用价值的购买者"),
        "primary_scenario": str(settings.get("primary_scenario") or "日常使用场景"),
        "product_images": [
            {"id": str(item.get("id")), "path": str(image_paths[index]), "role": str(item.get("role") or "product_reference")}
            for index, item in enumerate(product_images)
        ],
        "verified_facts": facts,
        "conflict_scan": conflict_scan,
        "source_conflicts": conflicts,
        "reference_materials": references,
        "platform_profile": profile,
        "coverage_directive": "MAXIMIZE_USER_SUPPLIED_RELEVANT_FACTS",
        "question_budget": 0,
        "conflict_policy": "BLOCK_PLAN_AND_BATCH_ASK",
    }


def build_native_identity(settings: Mapping[str, Any], product_image_ids: Sequence[str]) -> dict[str, Any]:
    name = str(settings.get("product_name") or "未命名商品")
    return {
        "canonical_name": name,
        "category": str(settings.get("category") or "国内电商商品"),
        "reference_image_ids": list(product_image_ids),
        "invariant_features": [
            "截面形状、外轮廓边界与整体比例严格以用户商品参考图的可见像素为准。",
            "正面宽:总高比例、主体占比与透视关系严格以用户商品参考图的可见像素为准。",
            "结构分段、部件接缝、部件数量与相对位置严格以用户商品参考图的可见像素为准。",
            "颜色分区、材质外观、纹理状态以及可见标识严格以用户商品参考图为准。",
        ],
        "allowed_states": ["正面展示", "侧面展示", "局部结构展示", "真实使用场景展示"],
        "uncertain_features": [],
        "forbidden_mutations": ["不得新增、删除或改造用户素材中未出现的商品部件。", "不得改变商品型号、颜色、比例、结构或身份标识。", "不得把视觉参考图的商品、品牌或文案带入当前商品。"],
        "forbidden_background_elements": ["竞争品牌标志", "未授权认证或参数", "会与商品身份混淆的替代商品"],
        "brand_logo_source": {"mode": "BRANDLESS", "image_id": "NONE", "authorization_basis": "NOT_APPLICABLE", "readability": "NOT_APPLICABLE", "usage": "FORBIDDEN_ALL_SCREENS", "brandless_evidence": "当前接入仅授权用户提供的商品素材，未收到可独立授权的品牌标识源。"},
    }


def extract_native_plan(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    return resolve_native_plan(payload)



def source_path_for(workspace: Path, index: int, filename: str, payload: bytes) -> Path:
    suffix = Path(filename).suffix.lower() or ".bin"
    path = workspace / "references" / f"{index:02d}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(payload).hexdigest():
        path.write_bytes(payload)
    return path
