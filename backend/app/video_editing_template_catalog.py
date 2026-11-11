"""Presentation metadata beside, never inside, immutable planning snapshots."""

from pathlib import Path
from typing import Literal

from pydantic import Field

from .config import Settings
from .errors import ApiError
from .motion_library import read_json, sha256
from .motion_library_validation import group_status, motion_evidence_directory
from .video_editing_overlay_templates import overlay_templates
from .video_studio_schemas import StrictVideoModel


class TemplateExample(StrictVideoModel):
    title: str
    url: str
    poster_url: str | None = None
    round: Literal["first", "replan", "recorded_response_replay"]
    distinct_groups: int = Field(ge=5)
    occurrences: int = Field(ge=5)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class TemplateCatalogCard(StrictVideoModel):
    id: str
    version: str
    name: str
    category: str
    featured: bool
    description: str
    visual_features: list[str]
    material_requirements: list[str]
    material_mode: Literal["speech", "images", "clips", "special"]
    group_ids: list[str]
    sampled_group_count: int
    pending_original_group_ids: list[str]
    status: Literal["sample_backed", "unverified", "pending_originals", "internal_only"]
    status_label: str
    business_review: Literal["pending"] = "pending"
    example: TemplateExample | None = None


_CURATED = {
    "product-explainer-v1": {
        "description": "让商品看点、规格和使用场景跟着口播展开，适合产品介绍与功能讲解。",
        "visual_features": ["金色重点", "横竖分屏", "撕纸与手机图卡"],
        "material_requirements": [
            "9:16 竖屏口播，建议无内嵌字幕",
            "建议准备 3 张不同的商品或界面图，并说明各自用途；无配图时仅选适用成员",
        ],
        "material_mode": "images",
        "category": "产品与案例",
    },
    "knowledge-talk-v1": {
        "description": "用追问、分层论点和结论卡，把观点与方法讲清楚。适合知识分享和判断分析。",
        "visual_features": ["黑白资料板", "分层论点", "圆窗与结论接力"],
        "material_requirements": [
            "9:16 竖屏口播，建议无内嵌字幕",
            "无需补充图片；数字、并列事项与条件以实际口播为准",
        ],
        "material_mode": "speech",
        "category": "观点与知识",
    },
    "chenxi-broll-v1": {
        "description": "操作画面与同期讲解人物交替出现，适合软件教程和真实操作演示。",
        "visual_features": ["实景分屏", "人物圆窗", "纸条说明"],
        "material_requirements": [
            "9:16 竖屏、无内嵌字幕的讲解口播",
            "上传已分好步骤的短录屏，并说明每段操作；短片需覆盖使用段",
            "纸纹版式另需一张底图；长录屏自动找操作起止尚未接入",
        ],
        "material_mode": "clips",
        "category": "实景与教程",
    },
}
_PENDING = {"CX-G05", "CX-G08", "CX-G09", "CX-G10", "HY-A1"}


def example_file(settings: Settings, template_id: str, kind: str) -> tuple[dict, Path]:
    """Only explicitly installed, hash-bound examples may cross project boundaries."""
    try:
        directory = settings.video_editing_template_examples_dir
        if directory is None or kind not in {"video", "poster"}:
            raise ValueError("No installed example")
        root = directory.resolve()
        manifest = read_json(root / "manifest.json")
        entry = manifest["examples"][template_id]
        relative = Path(entry[kind]["file"])
        path = (root / relative).resolve()
        if (
            relative.is_absolute()
            or not path.is_relative_to(root)
            or not path.is_file()
        ):
            raise ValueError("Invalid example path")
        if path.suffix.lower() != (".mp4" if kind == "video" else ".jpg"):
            raise ValueError("Invalid example media")
        if sha256(path) != entry[kind]["sha256"]:
            raise ValueError("Example bytes changed")
        return entry, path
    except (OSError, ValueError, KeyError, TypeError):
        raise ApiError(
            404, "EDITING_TEMPLATE_EXAMPLE_UNAVAILABLE", "此模板的示例暂不可用。"
        ) from None


def template_catalog(settings: Settings, workspace_id: str) -> list[dict]:
    templates = overlay_templates()
    evidence = motion_evidence_directory(settings)
    sampled = {
        gid: group_status(evidence, gid)["runtime_validation"]
        in {"sample_rendered", "mixed_samples"}
        for gid in {
            slot["group_id"] for template in templates for slot in template["slots"]
        }
    }
    cards = []
    for template in templates:
        tid = template["id"]
        groups = [slot["group_id"] for slot in template["slots"]]
        b_variant = tid == "question-card-b-story-v1"
        pending = sorted(set(groups) & _PENDING | ({"AH-S03"} if b_variant else set()))
        internal = any(gid.startswith("HY-") for gid in groups)
        meta = _CURATED.get(tid)
        if meta is None:
            mode = (
                "special"
                if internal
                else "images"
                if any(g.startswith(("W-", "CX-", "AZL")) for g in groups)
                else "speech"
            )
            meta = {
                "description": " · ".join(
                    slot["purpose"].split("。")[0] for slot in template["slots"][:2]
                ),
                "visual_features": ["原生版式", "按实录词点入场"],
                "material_requirements": [
                    "9:16 竖屏口播",
                    "依所选版式补充本期素材；准备剪辑后会核对实际可选成员",
                ],
                "material_mode": mode,
                "category": "内部原生场景"
                if internal
                else "图片与资料"
                if mode == "images"
                else "文字与叙事",
            }
        count = sum(sampled[gid] for gid in groups)
        if b_variant and sampled.get("AH-S03"):
            count -= 1
            count += group_status(evidence, "AH-S03", native_branch="input-B")[
                "runtime_validation"
            ] in {"sample_rendered", "mixed_samples"}
        status = (
            "internal_only"
            if internal
            else "pending_originals"
            if pending
            else "sample_backed"
            if count == len(groups)
            else "unverified"
        )
        example = None
        try:
            entry, _ = example_file(settings, tid, "video")
            base = f"/api/v1/video-studio/workspaces/{workspace_id}/editing-template-catalog/{tid}/example"
            poster = None
            try:
                example_file(settings, tid, "poster")
                poster = base + "/poster"
            except ApiError:
                pass
            example = TemplateExample.model_validate(
                {**entry["metadata"], "url": base + "/video", "poster_url": poster}
            ).model_dump()
        except (ApiError, ValueError, KeyError, TypeError):
            pass
        cards.append(
            TemplateCatalogCard.model_validate(
                {
                    "id": tid,
                    "version": tid.rsplit("-", 1)[-1],
                    "name": template["name"],
                    "featured": tid in _CURATED,
                    "group_ids": groups,
                    "sampled_group_count": count,
                    "pending_original_group_ids": pending,
                    "status": status,
                    "status_label": {
                        "internal_only": "内部运行条件待核对",
                        "pending_originals": "部分原件待补",
                        "sample_backed": "成员有编码样本 · 本期效果待预览",
                        "unverified": "样本记录未齐 · 先核对条件",
                    }[status],
                    "example": example,
                    **meta,
                }
            ).model_dump()
        )
    return cards
