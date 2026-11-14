"""Presentation metadata beside, never inside, immutable planning snapshots."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from .config import Settings
from .errors import ApiError
from .motion_library import read_json, sha256
from .motion_library_validation import group_status, motion_evidence_directory
from .video_editing_apple_pipeline import suite_card
from .video_editing_overlay_templates import overlay_templates
from .video_editing_template_styles import FEATURED, PUBLIC_TEMPLATE_IDS, STYLES
from .video_studio_schemas import StrictVideoModel


class TemplateExample(StrictVideoModel):
    title: str
    url: str
    poster_url: str | None = None
    round: Literal["first", "replan", "recorded_response_replay", "operator_authored"]
    origin: Literal["tengli_gateway", "operator_candidate"] | None = None
    distinct_groups: int = Field(ge=1)
    occurrences: int = Field(ge=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class TemplateCatalogCard(StrictVideoModel):
    engine: str | None = Field(default=None, exclude_if=lambda value: value is None)
    capabilities: list[str] = Field(
        default_factory=list, exclude_if=lambda value: not value
    )
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
    signature_group_ids: list[str]
    style_preview: "TemplateStylePreview | None" = None


class TemplateStylePreview(StrictVideoModel):
    title: str
    url: str
    poster_url: str | None = None
    group_id: str
    native_branch: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    scope: Literal["native_sample"] = "native_sample"


_PENDING = {"CX-G05", "CX-G08", "CX-G09", "CX-G10", "HY-A1"}


def _file_revision(path: Path) -> tuple[int, ...]:
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


@lru_cache(maxsize=8)
def _example_manifest(path: Path, revision: tuple[int, ...]) -> dict:
    manifest = read_json(path)
    if _file_revision(path) != revision:
        raise ValueError("Example manifest changed while reading")
    return manifest


@lru_cache(maxsize=256)
def _example_digest(path: Path, revision: tuple[int, ...]) -> str:
    digest = sha256(path)
    if _file_revision(path) != revision:
        raise ValueError("Example changed while checking")
    return digest


def example_file(
    settings: Settings, template_id: str, kind: str, *, collection: str = "examples"
) -> tuple[dict, Path]:
    """Only explicitly installed, hash-bound examples may cross project boundaries."""
    try:
        directory = settings.video_editing_template_examples_dir
        if directory is None or kind not in {"video", "poster"}:
            raise ValueError("No installed example")
        root = directory.resolve()
        manifest_path = root / "manifest.json"
        manifest = _example_manifest(manifest_path, _file_revision(manifest_path))
        if collection not in {"examples", "style_previews"}:
            raise ValueError("Invalid media collection")
        entry = manifest[collection][template_id]
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
        # The installed store is read-only. Reuse verification only while the
        # exact file revision is unchanged; ownership/path checks run every time.
        if _example_digest(path, _file_revision(path)) != entry[kind]["sha256"]:
            raise ValueError("Example bytes changed")
        return entry, path
    except (OSError, ValueError, KeyError, TypeError):
        raise ApiError(
            404, "EDITING_TEMPLATE_EXAMPLE_UNAVAILABLE", "此模板的示例暂不可用。"
        ) from None


def template_catalog(settings: Settings, workspace_id: str) -> list[dict]:
    all_templates = {template["id"]: template for template in overlay_templates()}
    templates = [all_templates[tid] for tid in PUBLIC_TEMPLATE_IDS]
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
        profile = STYLES[tid]
        meta = {
            key: profile[key]
            for key in (
                "description",
                "visual_features",
                "material_requirements",
                "material_mode",
                "category",
            )
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
            base = (
                f"/api/v1/video-studio/workspaces/{workspace_id}"
                f"/editing-template-catalog/{tid}/example"
            )
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
        preview = None
        try:
            entry, _ = example_file(settings, tid, "video", collection="style_previews")
            if entry["metadata"]["group_id"] not in profile["signature_group_ids"]:
                raise ValueError("Preview does not show this style's signature")
            if b_variant and entry["metadata"].get("native_branch") != "input-B":
                raise ValueError("Preview must match the B branch")
            base = (
                f"/api/v1/video-studio/workspaces/{workspace_id}"
                f"/editing-template-catalog/{tid}/style-preview"
            )
            poster = None
            try:
                example_file(settings, tid, "poster", collection="style_previews")
                poster = base + "/poster"
            except ApiError:
                pass
            preview = TemplateStylePreview.model_validate(
                {**entry["metadata"], "url": base + "/video", "poster_url": poster}
            ).model_dump()
        except (ApiError, ValueError, KeyError, TypeError):
            pass
        cards.append(
            TemplateCatalogCard.model_validate(
                {
                    "id": tid,
                    "version": tid.rsplit("-", 1)[-1],
                    "name": profile["name"],
                    "featured": tid in FEATURED,
                    "signature_group_ids": profile["signature_group_ids"],
                    "style_preview": preview,
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
    apple = suite_card(settings, workspace_id)
    if apple is not None:
        try:
            entry, _ = example_file(settings, apple["id"], "video")
            url = (
                f"/api/v1/video-studio/workspaces/{workspace_id}"
                f"/editing-template-catalog/{apple['id']}/example"
            )
            poster = None
            try:
                example_file(settings, apple["id"], "poster")
                poster = url + "/poster"
            except ApiError:
                pass
            apple["example"] = TemplateExample.model_validate(
                {**entry["metadata"], "url": url + "/video", "poster_url": poster}
            ).model_dump()
        except (ApiError, KeyError, ValueError):
            pass
        cards.insert(0, TemplateCatalogCard.model_validate(apple).model_dump())
    from .bihuo_suite.registry import cards as bihuo_cards

    for card in bihuo_cards():
        try:
            entry, _ = example_file(settings, card["id"], "video")
            url = (
                f"/api/v1/video-studio/workspaces/{workspace_id}"
                f"/editing-template-catalog/{card['id']}/example"
            )
            poster = None
            try:
                example_file(settings, card["id"], "poster")
                poster = url + "/poster"
            except ApiError:
                pass
            card["example"] = TemplateExample.model_validate(
                {**entry["metadata"], "url": url + "/video", "poster_url": poster}
            ).model_dump()
        except (ApiError, KeyError, ValueError):
            pass
        cards.append(TemplateCatalogCard.model_validate(card).model_dump())
    return cards
