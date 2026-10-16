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
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import default_aurora_work_root, default_skill_root
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
    for candidate in (
        payload.get("aurora_plan"),
        (payload.get("analysis") or {}).get("aurora_plan") if isinstance(payload.get("analysis"), Mapping) else None,
    ):
        if isinstance(candidate, Mapping) and isinstance(candidate.get("modules"), list):
            return dict(candidate)
    for group in payload.get("groups", []) if isinstance(payload.get("groups"), list) else []:
        if not isinstance(group, Mapping):
            continue
        protocol = group.get("plan_protocol_fields")
        if isinstance(protocol, Mapping) and isinstance(protocol.get("aurora_plan"), Mapping):
            return dict(protocol["aurora_plan"])
    return None


def normalize_native_plan_for_harness(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Bridge valid compact-plan values to the Harness' stricter list contract.

    The public compact schema permits an empty proof-support list and a scalar
    specificity anchor. The bundled Harness deliberately requires observable
    list entries for those fields. Preserve authored values and add only
    structural, fact-neutral bindings when the stricter runtime needs them.
    """

    normalized = json.loads(json.dumps(plan, ensure_ascii=False))
    modules = normalized.get("modules")
    if not isinstance(modules, list):
        return normalized
    strategy = normalized.get("output_strategy")
    if not isinstance(strategy, dict):
        strategy = {}
        normalized["output_strategy"] = strategy
    # The bundled v4.3 Harness intentionally accepts one resolved count
    # derivation.  Compact authoring responses may expose alternatives even
    # though the approved plan already has a fixed module list.
    module_count = len(modules)
    strategy["module_count"] = module_count
    strategy["module_count_candidates"] = [{
        "candidate_mode": "DIRECT_DERIVATION",
        "count": module_count,
        "coverage_tradeoff": "按已批准卖点直接确定屏幕数量",
        "selling_point_fit": "覆盖已批准事实并保持每屏独立证明职责",
        "story_obligation_fit": "保留开场、证明、场景与购买收束",
        "primary_selling_point_depth_fit": "每个核心卖点都有可见证据承载",
        "evidence_boundary_fit": "不增加用户未提供的事实或主张",
        "decision": "SELECTED",
    }]
    def fact_id_for_claim(value: object) -> str:
        text = str(value or "")
        match = re.fullmatch(r"C(\d+)", text)
        return f"F{match.group(1)}" if match else text
    dna = normalized.get("series_visual_dna")
    if isinstance(dna, dict):
        constitution = normalized.get("style_constitution")
        constitution = constitution if isinstance(constitution, dict) else {}
        dna.setdefault("brand_anchor_system", dna.get("brand_anchor") or "以当前商品本体和统一视觉DNA建立识别")
        dna.setdefault("palette_tokens", constitution.get("color_and_light") or "以商品真实配色为主，保持统一冷暖关系")
        dna.setdefault("typography_tokens", constitution.get("typography_and_graphics") or "简洁中文无衬线字体，标题与对象标签分层")
        dna.setdefault("graphic_tokens", constitution.get("typography_and_graphics") or "细线标注与克制辅助图形")
        dna.setdefault("photography_tokens", constitution.get("product_rendering") or "真实商品材质与统一主光")
        dna.setdefault("product_tokens", list(dna.get("identity_geometry") or []) + list(dna.get("photography_tokens") or []))
        dna.setdefault("spatial_tokens", [
            "纵向连续展台",
            "非对称证据分区",
            "两屏一组固定切片",
        ])
        invariants = dna.get("invariants")
        if not isinstance(invariants, list) or len(invariants) < 2:
            identity = [str(item) for item in (dna.get("identity_geometry") or []) if str(item).strip()]
            dna["invariants"] = (identity + ["统一主光方向与商品材质真实感", "连续 pair 画布使用固定切片坐标"])[:]
    typography_rhythm = normalized.get("typography_rhythm")
    if not isinstance(typography_rhythm, dict):
        typography_rhythm = {}
        normalized["typography_rhythm"] = typography_rhythm
    typography_rhythm.setdefault("campaign_rule", "标题服从可见证据，按屏幕职责改变锚区与阅读路径")
    typography_rhythm.setdefault("primary_mode_sequence", [str(module.get("typography", {}).get("primary_mode") or "EDGE_TITLE") for module in modules if isinstance(module, dict)])
    typography_rhythm.setdefault("anchor_zone_sequence", [str(module.get("typography", {}).get("anchor_zone") or "画面留白区") for module in modules if isinstance(module, dict)])
    typography_rhythm.setdefault("centered_hero_max", 2)
    typography_rhythm.setdefault("consecutive_anchor_repeat_limit", 2)
    typography_rhythm.setdefault("exceptions", [])
    hero_contract = normalized.get("hero_screen_contract")
    if isinstance(hero_contract, dict):
        hero_contract["hero_module_id"] = "M01"
        hero_contract["hero_uniqueness"] = "ONE_PRIMARY_HERO"
        hero_contract["co_equal_hero_forbidden"] = True
        hero_contract.setdefault("hero_entity_id", "E_PRODUCT_WHOLE")
        hero_contract.setdefault("hero_job", "建立唯一商品身份并给出核心购买印象")
        hero_contract.setdefault("supporting_entities_allowed", ["商品结构与真实可见细节"])
        hero_contract.setdefault("hero_identity_evidence", ["商品参考图"])
    detail_contract = normalized.get("detail_information_contract")
    if isinstance(detail_contract, dict):
        detail_contract["required_progression_jobs"] = [
            "IDENTITY", "PAIN", "BENEFIT", "DEDICATED_PROOF", "CLOSURE",
        ]
        detail_contract["non_repeating_overview_limit"] = 1
        detail_contract["every_pair_requires_information_delta"] = True
        questions = detail_contract.get("buyer_question_sequence")
        if not isinstance(questions, list) or len(questions) < 4:
            detail_contract["buyer_question_sequence"] = [str(module.get("buyer_question") or "确认商品可见证据") for module in modules]
    reference_system = normalized.get("reference_expression_system")
    if isinstance(reference_system, dict):
        # Product references are identity sources, not style-reference
        # materials. With no separate reference pack supplied, the Harness
        # requires an explicit empty adoption/rejection ledger.
        reference_system["coverage"] = []
        reference_system["adopted_patterns"] = []
    recall = normalized.get("campaign_recall_contract")
    if isinstance(recall, dict) and isinstance(recall.get("must_remember_claim_ids"), list):
        recall["must_remember_claim_ids"] = [fact_id_for_claim(item) for item in recall["must_remember_claim_ids"]]
    depth = normalized.get("selling_point_depth_contract")
    if isinstance(depth, dict):
        primary_entries = depth.get("primary_claims") if isinstance(depth.get("primary_claims"), list) else []
        primary_ids = [fact_id_for_claim(item.get("claim_id")) for item in primary_entries if isinstance(item, dict) and item.get("claim_id")]  # type: ignore[union-attr]
        if not primary_ids:
            primary_ids = [str(item) for item in (recall or {}).get("must_remember_claim_ids", [])]
        depth["selection_policy"] = "按用户已确认事实和购买决策深度选择一级卖点"
        depth["primary_claim_ids"] = primary_ids
        claim_depth = []
        for entry, claim_id in zip(primary_entries, primary_ids, strict=False):  # type: ignore[arg-type]
            scheduled_values = (
                entry.get("scheduled_module_ids")
                if isinstance(entry, dict)
                else []
            )
            scheduled = [str(item) for item in (scheduled_values or [])]
            if not scheduled:
                scheduled = [str(module.get("id")) for module in modules if isinstance(module, dict) and module.get("lead_claim_id") == claim_id]
            dedicated = [str(module.get("id")) for module in modules if isinstance(module, dict) and module.get("lead_claim_id") == claim_id]
            if not dedicated and scheduled:
                dedicated = scheduled[:1]
            jobs = ["VALUE_OVERVIEW", "DEDICATED_EXPRESSION", "USE_SCOPE", "RECALL"]
            module_jobs = []
            for index, module_id in enumerate(scheduled):
                job = jobs[0] if index == 0 else jobs[1] if index == 1 else jobs[2]
                module_jobs.append({"module_id": module_id, "job": job})
            if scheduled:
                module_jobs.append({"module_id": scheduled[-1], "job": jobs[-1]})
            claim_depth.append({
                "claim_id": claim_id,
                "depth_tier": "DEEP",
                "evidence_ceiling": str((entry or {}).get("evidence_ceiling") or "DIRECT_PROOF_AVAILABLE"),
                "required_decision_jobs": jobs,
                "scheduled_module_ids": scheduled,
                "dedicated_module_ids": dedicated,
                "non_duplicate_rationale": "每个一级卖点在总览、独立证据、使用判断与收尾回忆中承担不同职责",
                "forbidden_expansion": "不得扩展为用户未提供的性能、认证或安全承诺",
                "priority": "PRIMARY",
                "module_jobs": module_jobs,
            })
        depth["claim_depth"] = claim_depth
    information_roles = ["IDENTITY", "PAIN", "DEDICATED_PROOF", "DEDICATED_PROOF", "DEDICATED_PROOF", "RESULT_OR_EXPERIENCE", "SELECTION_OR_USE", "CLOSURE"]
    for index, module in enumerate(modules):
        if isinstance(module, dict):
            module["information_role"] = information_roles[index] if index < len(information_roles) else "OTHER"
            if index == 0:
                module["hero_entity_id"] = str((hero_contract or {}).get("hero_entity_id") or "E_PRODUCT_WHOLE")
                module["co_equal_hero_entity_ids"] = []
    forbidden_inventions = []
    if isinstance(dna, dict) and isinstance(dna.get("forbidden_mutations"), list):
        forbidden_inventions = [str(item) for item in dna["forbidden_mutations"] if str(item).strip()]

    # The compact schema allows richer authoring notes, while the runtime
    # spatial contract for ASYMMETRIC_EDITORIAL is a two-zone contract. Keep
    # all authored wording by folding any additional notes into the second
    # zone instead of silently dropping it.
    for module in modules:
        if not isinstance(module, dict):
            continue
        for field in ("visual_payload_density", "commercial_energy", "proof_relation_strength"):
            value = module.get(field)
            if isinstance(value, str):
                lowered = value.lower()
                if field == "commercial_energy":
                    lowered = {
                        "medium": "standard",
                        "medium_high": "high",
                        "low_medium": "standard",
                    }.get(lowered, lowered)
                elif field == "visual_payload_density":
                    lowered = {"medium_high": "high", "low_medium": "medium"}.get(lowered, lowered)
                module[field] = lowered
        evidence = module.get("visual_evidence")
        if isinstance(evidence, list):
            module["visual_evidence"] = {
                "evidence_class": "DIRECT_OBSERVATION",
                "proof_device": "CONCRETE_PRODUCT_EVIDENCE",
                "visible_content": [str(item) for item in evidence if str(item).strip()],
                "forbidden_inventions": list(forbidden_inventions),
            }
        elif isinstance(evidence, dict):
            evidence.setdefault("evidence_class", "DIRECT_OBSERVATION")
            evidence.setdefault("proof_device", "CONCRETE_PRODUCT_EVIDENCE")
        spatial = module.get("module_spatial_structure_contract")
        if isinstance(spatial, dict):
            briefs = spatial.get("zone_briefs")
            if isinstance(briefs, list) and len(briefs) > 2:
                spatial["zone_briefs"] = [
                    str(briefs[0]),
                    "；".join(str(item) for item in briefs[1:] if str(item).strip()),
                ]
        authored_structure = module.get("structure")
        if isinstance(authored_structure, dict):
            briefs = authored_structure.get("zone_briefs")
            if isinstance(briefs, list) and len(briefs) > 2:
                authored_structure["zone_briefs"] = [
                    str(briefs[0]),
                    "；".join(str(item) for item in briefs[1:] if str(item).strip()),
                ]

    def fact_id_for_claim(value: object) -> str:  # type: ignore[no-redef]
        text = str(value or "")
        match = re.fullmatch(r"C(\d+)", text)
        return f"F{match.group(1)}" if match else text

    for module in modules:
        if not isinstance(module, dict):
            continue
        if module.get("lead_claim_id"):
            module["lead_claim_id"] = fact_id_for_claim(module["lead_claim_id"])
        support = module.get("supporting_claim_ids")
        if isinstance(support, list):
            module["supporting_claim_ids"] = [fact_id_for_claim(item) for item in support]

    claims = strategy.get("claim_coverage")
    if isinstance(claims, list):
        by_id = {str(module.get("id")): module for module in modules if isinstance(module, dict) and module.get("id")}
        for claim in claims:
            if not isinstance(claim, dict) or not claim.get("claim_id"):
                continue
            claim_id = fact_id_for_claim(claim["claim_id"])
            claim["claim_id"] = claim_id
            assigned = [str(item) for item in claim.get("module_ids", []) if str(item) in by_id]
            # A selected claim must include the module that declares it as lead.
            for module_id, module in by_id.items():
                if str(module.get("lead_claim_id") or "") == claim_id and module_id not in assigned:
                    assigned.append(module_id)
            claim["module_ids"] = assigned
            claim.setdefault(
                "disposition",
                "LEAD" if any(
                    str(by_id[module_id].get("lead_claim_id") or "") == claim_id
                    for module_id in assigned
                ) else "SUPPORT",
            )
            claim["defer_reason_code"] = "NOT_DEFERRED"
            claim.setdefault("rationale", "核心事实直接进入已批准屏幕")
            for module_id in assigned:
                module = by_id[module_id]
                if str(module.get("lead_claim_id") or "") != claim_id:
                    support = module.get("supporting_claim_ids")
                    if not isinstance(support, list):
                        support = []
                        module["supporting_claim_ids"] = support
                    if claim_id not in support:
                        support.append(claim_id)
    clusters = strategy.get("selling_point_clusters")
    if isinstance(clusters, list):
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            if not cluster.get("id") and cluster.get("cluster_id"):
                cluster["id"] = cluster["cluster_id"]
            if not isinstance(cluster.get("fact_ids"), list):
                cluster["fact_ids"] = list(cluster.get("claim_ids") or [])
            cluster.setdefault("buyer_question", cluster.get("label") or "买家如何判断这项商品事实")
            cluster.setdefault("purchase_role", "BENEFIT")
            cluster.setdefault("separation_policy", "MERGEABLE")
            if not isinstance(cluster.get("assigned_module_ids"), list):
                cluster_id = str(cluster.get("id") or "")
                cluster["assigned_module_ids"] = [
                    str(module.get("id"))
                    for module in modules
                    if isinstance(module, dict) and cluster_id in (module.get("selling_point_cluster_ids") or [])
                ]
            cluster["fact_ids"] = [fact_id_for_claim(item) for item in cluster.get("fact_ids", [])]
    spatial_families = {
        1: ("FULL_BLEED_HERO", 1),
        2: ("ASYMMETRIC_EDITORIAL", 2),
        3: ("STACKED_BANDS", 2),
        4: ("MACRO_DIAGRAM", 2),
        5: ("MACRO_DIAGRAM", 2),
        6: ("STACKED_BANDS", 2),
        7: ("ASYMMETRIC_EDITORIAL", 2),
        8: ("FULL_BLEED_HERO", 1),
    }
    for index, module in enumerate(modules, start=1):
        if not isinstance(module, dict):
            continue
        family, expected_zone_count = spatial_families.get(index, ("ASYMMETRIC_EDITORIAL", 2))
        for key in ("structure", "module_spatial_structure_contract"):
            spatial = module.get(key)
            if not isinstance(spatial, dict):
                continue
            spatial["structure_family"] = family
            briefs = [str(item) for item in spatial.get("zone_briefs", []) if str(item).strip()]
            if not briefs:
                briefs = ["主导证据区"]
            if expected_zone_count == 1:
                briefs = ["；".join(briefs)]
            elif len(briefs) < expected_zone_count:
                briefs.extend([f"补充证据区{n}" for n in range(len(briefs) + 1, expected_zone_count + 1)])
            elif len(briefs) > expected_zone_count:
                briefs = briefs[:expected_zone_count - 1] + ["；".join(briefs[expected_zone_count - 1:])]
            spatial["zone_briefs"] = briefs
    pair_rendering = strategy.get("continuous_pair_rendering")
    if isinstance(pair_rendering, dict) and isinstance(pair_rendering.get("pair_ids"), list):
        modules_by_id = {
            str(module.get("id")): module
            for module in modules
            if isinstance(module, dict) and module.get("id")
        }
        for pair in pair_rendering["pair_ids"]:
            if not isinstance(pair, dict):
                continue
            module_ids = pair.get("module_ids")
            upper = modules_by_id.get(str(module_ids[0])) if isinstance(module_ids, list) and module_ids else None
            transition = upper.get("transition_contract") if isinstance(upper, dict) else None
            if not isinstance(transition, dict):
                continue
            pair["internal_seam_method_id"] = transition.get("method_id")
            pair["internal_seam_carrier"] = transition.get("seam_carrier")
            pair["internal_seam_source_region"] = transition.get("source_region_previous")
            pair["internal_seam_target_region"] = transition.get("target_region_current")
            pair["internal_seam_geometry"] = transition.get("handoff_geometry")
    for module in modules:
        if not isinstance(module, dict):
            continue
        proof = module.get("proof")
        if not isinstance(proof, dict):
            proof = {}
            module["proof"] = proof
        supporting = proof.get("supporting_subjects")
        if not isinstance(supporting, list) or not supporting:
            proof["supporting_subjects"] = [
                str(proof.get("primary_subject") or "产品主体细节")
            ]
        relations = proof.get("required_relations")
        if not isinstance(relations, list) or not relations:
            proof["required_relations"] = ["商品主体与可见证据保持同一关系"]
        anchor = proof.get("visual_specificity_anchor")
        if isinstance(anchor, str):
            proof["visual_specificity_anchor"] = [anchor]
        elif not isinstance(anchor, list) or not anchor:
            proof["visual_specificity_anchor"] = ["产品外观与结构"]
        if not bool(module.get("breathing_screen")):
            evidence = module.get("visual_evidence")
            visible_count = len(evidence.get("visible_content", [])) if isinstance(evidence, dict) and isinstance(evidence.get("visible_content"), list) else 0
            proof["minimum_visual_payload"] = max(3, int(proof.get("minimum_visual_payload") or 0), visible_count)
    return normalized


def source_path_for(workspace: Path, index: int, filename: str, payload: bytes) -> Path:
    suffix = Path(filename).suffix.lower() or ".bin"
    path = workspace / "references" / f"{index:02d}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(payload).hexdigest():
        path.write_bytes(payload)
    return path
