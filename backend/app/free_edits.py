"""Every image the site generated gets a few free local edits.

The allowance belongs to the generated image a chain of edits started from:
editing an edit result spends the same allowance. Uploaded images have none.
An edit spends one free use once it is in flight or has produced a
generation; an edit that failed before generating gives its use back.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AssetRecord, JobAssetRecord, JobRecord

FREE_EDITS_PER_IMAGE = 3
ROOT_KEY = "_local_edit_root_asset_id"
FREE_KEY = "_local_edit_free_of_asset_id"
_GENERATED_ROLE = "provider_raw"


def root_asset_id(session: Session, workspace_id: str, asset_id: str) -> str | None:
    """The generated image an edit of ``asset_id`` counts against, if any."""
    edit_jobs = session.scalars(
        select(JobRecord)
        .join(JobAssetRecord, JobAssetRecord.job_id == JobRecord.id)
        .where(
            JobRecord.workspace_id == workspace_id,
            JobRecord.type == "local_edit",
            JobAssetRecord.workspace_id == workspace_id,
            JobAssetRecord.asset_id == asset_id,
            JobAssetRecord.direction != "input",
        )
        .order_by(JobRecord.created_at, JobRecord.id)
    ).all()
    if edit_jobs:
        # An edit result: continue the allowance of the image it came from.
        for job in edit_jobs:
            root = job.configuration.get(ROOT_KEY)
            if isinstance(root, str):
                return root
        return None
    generated = session.scalar(
        select(JobAssetRecord.id)
        .join(JobRecord, JobRecord.id == JobAssetRecord.job_id)
        .where(
            JobAssetRecord.workspace_id == workspace_id,
            JobAssetRecord.asset_id == asset_id,
            JobAssetRecord.direction == "output",
            JobRecord.workspace_id == workspace_id,
            JobRecord.type != "local_edit",
        )
        .limit(1)
    )
    return asset_id if generated is not None else None


def used_free_edits(
    session: Session,
    workspace_id: str,
    root: str,
    *,
    exclude_job_id: str | None = None,
) -> int:
    generated = (
        select(JobAssetRecord.id)
        .where(
            JobAssetRecord.workspace_id == workspace_id,
            JobAssetRecord.job_id == JobRecord.id,
            JobAssetRecord.role == _GENERATED_ROLE,
        )
        .exists()
    )
    query = select(func.count(JobRecord.id)).where(
        JobRecord.workspace_id == workspace_id,
        JobRecord.type == "local_edit",
        JobRecord.configuration[FREE_KEY].as_string() == root,
        (JobRecord.status.not_in(["failed", "cancelled"])) | generated,
    )
    if exclude_job_id is not None:
        query = query.where(JobRecord.id != exclude_job_id)
    return int(session.scalar(query) or 0)


def allowance(session: Session, workspace_id: str, asset_id: str) -> dict[str, Any]:
    root = root_asset_id(session, workspace_id, asset_id)
    used = used_free_edits(session, workspace_id, root) if root else 0
    return {
        "asset_id": asset_id,
        "eligible": root is not None,
        "limit": FREE_EDITS_PER_IMAGE if root else 0,
        "used": min(used, FREE_EDITS_PER_IMAGE),
        "remaining": max(0, FREE_EDITS_PER_IMAGE - used) if root else 0,
    }


def apply(session: Session, job: JobRecord) -> None:
    """Decide, once per submitted edit, whether it spends a free use.

    Called before credits are reserved, at creation and for every regeneration.
    The root image row is locked so concurrent edits cannot both take the last
    free use.
    """
    configuration = {
        key: value
        for key, value in job.configuration.items()
        if key not in {ROOT_KEY, FREE_KEY}
    }
    source = (configuration.get("input") or {}).get("source_asset_id")
    root = (
        root_asset_id(session, job.workspace_id, source)
        if isinstance(source, str)
        else None
    )
    if root is not None:
        configuration[ROOT_KEY] = root
        session.scalar(
            select(AssetRecord.id)
            .where(AssetRecord.id == root, AssetRecord.workspace_id == job.workspace_id)
            .with_for_update()
        )
        if (
            used_free_edits(session, job.workspace_id, root, exclude_job_id=job.id)
            < FREE_EDITS_PER_IMAGE
        ):
            configuration[FREE_KEY] = root
    job.configuration = configuration
    from .credit_billing import image_unit_credits

    job.estimated_credits = image_unit_credits(job.type, configuration)


def is_free(configuration: dict[str, Any]) -> bool:
    return isinstance(configuration.get(FREE_KEY), str)
