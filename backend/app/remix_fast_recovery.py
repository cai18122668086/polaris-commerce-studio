"""Publish a retained fast-remix candidate without another provider request."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    AssetRecord,
    AuditEventRecord,
    JobAssetRecord,
    JobItemRecord,
    JobRecord,
)
from .remix_fast_provider import STATE_KEY
from .services import new_id, utc_now
from .storage import ImageStorage

REVIEW_ERRORS = {
    "REMIX_FAST_QUICK_CHECK_FAILED",
    "REMIX_FAST_ASPECT_RATIO_FAILED",
    "REMIX_FAST_REVIEW_UNAVAILABLE",
}


async def recover_delivery(
    session_factory: sessionmaker[Session],
    storage: ImageStorage,
    job_id: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    with session_factory() as session:
        job = session.get(JobRecord, job_id, with_for_update=True)
        if job is None or job.type != "reference_remix":
            raise ValueError("Not a fast-remix job")
        if job.status == "completed":
            return {"job_id": job_id, "status": "completed", "changed": False}
        items = session.scalars(
            select(JobItemRecord)
            .where(JobItemRecord.job_id == job_id)
            .with_for_update()
        ).all()
        if job.status != "failed" or job.expected_item_count != 1 or len(items) != 1:
            raise ValueError("Recovery requires one terminal failed item")
        item = items[0]
        state = dict((item.configuration or {}).get(STATE_KEY) or {})
        cached = state.get("artifact") or {}
        if (
            item.workspace_id != job.workspace_id
            or item.status != "failed"
            or item.error_code not in REVIEW_ERRORS
            or state.get("owner_job_id") != job_id
            or not cached.get("object_key", "").startswith(
                f"{job.workspace_id}/remix-fast/"
            )
        ):
            raise ValueError("Job has no recoverable retained candidate")
        _, stored = await storage.read_stored_image(cached["object_key"])
        if (stored.sha256, stored.width, stored.height, stored.content_type) != (
            cached.get("sha256"),
            cached.get("width"),
            cached.get("height"),
            cached.get("content_type"),
        ):
            raise ValueError("Retained candidate changed")
        result = {
            "job_id": job_id,
            "sha256": stored.sha256,
            "width": stored.width,
            "height": stored.height,
            "external_requests": 0,
            "changed": apply,
            "status": "completed" if apply else "ready",
        }
        if not apply:
            return result
        asset = session.scalar(
            select(AssetRecord).where(
                AssetRecord.storage_provider == stored.storage_provider,
                AssetRecord.storage_bucket == stored.storage_bucket,
                AssetRecord.object_key == stored.object_key,
                AssetRecord.object_version == stored.object_version,
            )
        )
        if asset is None:
            asset = AssetRecord(
                id=new_id("asset"),
                workspace_id=job.workspace_id,
                media_kind="image",
                origin_kind="generated",
                lifecycle_status="ready",
                original_filename=cached["filename"],
                content_type=stored.content_type,
                byte_size=stored.byte_size,
                width=stored.width,
                height=stored.height,
                sha256=stored.sha256,
                storage_provider=stored.storage_provider,
                storage_bucket=stored.storage_bucket,
                object_key=stored.object_key,
                object_version=stored.object_version,
                etag=stored.etag,
                asset_metadata={"post_generation_review": "disabled"},
            )
            session.add(asset)
            session.flush()
        elif (
            asset.workspace_id != job.workspace_id
            or asset.deleted_at is not None
            or asset.lifecycle_status != "ready"
            or asset.sha256 != stored.sha256
        ):
            raise ValueError("Stored asset is unavailable")
        if (
            session.scalar(
                select(JobAssetRecord.id).where(
                    JobAssetRecord.job_id == job_id,
                    JobAssetRecord.direction == "output",
                )
            )
            is not None
        ):
            raise ValueError("An output already exists")
        session.add(
            JobAssetRecord(
                workspace_id=job.workspace_id,
                job_id=job_id,
                job_item_id=item.id,
                asset_id=asset.id,
                direction="output",
                role="reference_remix_result",
                ordinal=item.ordinal,
                is_deliverable=True,
                validation={
                    "sha256": stored.sha256,
                    "post_generation_review": "disabled",
                },
            )
        )
        session.add(
            AuditEventRecord(
                workspace_id=job.workspace_id,
                action="remix_fast.delivery_recovered",
                resource_type="job",
                resource_id=job_id,
                details={
                    "previous_error_code": item.error_code,
                    "sha256": stored.sha256,
                    "external_requests": 0,
                    "post_generation_review": "disabled",
                },
            )
        )
        state["phase"] = "generated"
        item.configuration = {**item.configuration, STATE_KEY: state}
        item.status, item.stage, item.result_source = (
            "succeeded",
            "completed",
            "generated",
        )
        item.error_code = item.error_message = item.error_details = None
        item.state_version += 1
        job.status, job.stage, job.progress = "completed", "completed", 100
        job.succeeded_item_count, job.failed_item_count = 1, 0
        job.error_code = job.error_message = job.error_details = None
        job.finished_at = utc_now()
        job.state_version += 1
        # Existing attempts, usage events and settled charges describe the real
        # historical requests. Publishing their saved bytes adds no new charge.
        session.commit()
        result["asset_id"] = asset.id
        return result
