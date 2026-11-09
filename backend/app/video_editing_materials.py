"""Immutable, owner-scoped project media and path-free planning cards."""

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .errors import ApiError
from .motion_library import inside, sha256
from .video_editing_task_models import EditingMaterialRecord, EditingSourceRecord

SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}
PREFIX = "material-"


def material_file(settings: Settings, material_id: str, mime: str) -> Path:
    return inside(
        settings.video_editing_tasks_dir,
        f"materials/{UUID(material_id)}/original{SUFFIXES[mime]}",
    )


def material_changed() -> ApiError:
    return ApiError(
        409,
        "EDITING_MATERIAL_CHANGED",
        "本次选择的素材已缺失或变化，请核对原件后重新准备。",
    )


def verify_material_file(settings: Settings, row: EditingMaterialRecord) -> Path:
    try:
        path = material_file(settings, row.id, row.mime)
        if path.stat().st_size == row.bytes and sha256(path) == row.sha256:
            return path
    except (OSError, ValueError, KeyError):
        pass
    raise material_changed()


def project_material_files(
    session: Session,
    settings: Settings,
    source: EditingSourceRecord,
    asset_ids: set[str],
    *,
    verify_bytes: bool = False,
) -> dict[str, dict[str, Any]]:
    ids = {key.removeprefix(PREFIX) for key in asset_ids if key.startswith(PREFIX)}
    if not ids:
        return {}
    rows = session.scalars(
        select(EditingMaterialRecord).where(
            EditingMaterialRecord.id.in_(ids),
            EditingMaterialRecord.workspace_id == source.workspace_id,
            EditingMaterialRecord.owner_user_id == source.owner_user_id,
            EditingMaterialRecord.project_id == source.project_id,
        )
    ).all()
    if {row.id for row in rows} != ids:
        raise ApiError(404, "EDITING_MATERIAL_NOT_FOUND", "未找到本项目的补充素材。")
    return {
        PREFIX + row.id: {
            "path": str(
                verify_material_file(settings, row)
                if verify_bytes
                else material_file(settings, row.id, row.mime)
            ),
            "kind": row.kind,
            "sha256": row.sha256,
            "bytes": row.bytes,
            "semantic_use": row.description,
            "viewed_identity": row.label,
            "width": row.width,
            "height": row.height,
            "duration_ms": row.duration_ms,
            "source": "project_upload",
            "license": "project owner supplied; rights and facts unreviewed",
            **(
                {
                    "source_image_result": {
                        "job_id": row.source_job_id,
                        "asset_id": row.source_asset_id,
                    }
                }
                if row.source_job_id
                else {}
            ),
        }
        for row in rows
    }


def material_cards(assets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": asset_id,
            **{
                key: asset[key]
                for key in ("kind", "sha256", "semantic_use", "viewed_identity")
            },
            **(
                {
                    "scope": (
                        "generated illustration; not product or factual evidence"
                        if asset.get("source_image_result")
                        else "owner description; visual evidence and facts unreviewed"
                    )
                }
                if asset_id.startswith(PREFIX)
                else {}
            ),
        }
        for asset_id, asset in sorted(assets.items())
    ]


def project_image_digests(cards: list[dict]) -> dict[str, str]:
    return {
        card["id"]: card["sha256"]
        for card in cards
        if card["kind"] == "image" and card["id"].startswith(PREFIX)
    }


def verify_material_cards(
    session: Session,
    settings: Settings,
    source: EditingSourceRecord,
    cards: list[dict],
    *,
    verify_bytes: bool,
) -> dict[str, dict[str, Any]]:
    expected = [card for card in cards if card["id"].startswith(PREFIX)]
    assets = project_material_files(
        session,
        settings,
        source,
        {card["id"] for card in expected},
        verify_bytes=verify_bytes,
    )
    if material_cards(assets) != expected:
        raise material_changed()
    return assets
