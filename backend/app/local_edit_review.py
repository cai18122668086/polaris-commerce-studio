"""Human decisions on immutable, strictly locked local-edit candidates."""

import hashlib
from io import BytesIO
from typing import Literal

from PIL import Image, ImageChops, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import JobItemStatus, JobStatus
from .errors import ApiError
from .models import (
    AssetRecord,
    AuditEventRecord,
    JobAssetRecord,
    JobItemRecord,
    JobRecord,
    utc_now,
)
from .services import add_outbox_event, settle_credits, transition_job
from .storage import ImageStorage

CandidateVariant = Literal["locked", "original"]


def _outside_change_measurement(
    source: Image.Image, authority: Image.Image, output: Image.Image
) -> tuple[int, str]:
    """Compare only; never resize, composite or rewrite the chosen delivery bytes."""
    basis = "source_canvas"
    if output.size != source.size:
        from .masked_repair import _build_provider_canvas

        canvas = _build_provider_canvas(source, authority)
        source = Image.open(BytesIO(canvas.source_png)).convert("RGBA")
        api_mask = Image.open(BytesIO(canvas.api_mask_png)).convert("RGBA")
        authority = ImageOps.invert(api_mask.getchannel("A"))
        basis = "provider_input_canvas"
        if source.size != output.size:
            source = ImageOps.fit(source, output.size, Image.Resampling.LANCZOS)
            authority = ImageOps.fit(authority, output.size, Image.Resampling.NEAREST)
            basis = "provider_input_canvas_fitted_to_original"
    diff = ImageChops.difference(source, output)
    changed = ImageChops.lighter(
        ImageChops.lighter(diff.getchannel("R"), diff.getchannel("G")),
        ImageChops.lighter(diff.getchannel("B"), diff.getchannel("A")),
    )
    outside = ImageChops.multiply(changed, ImageOps.invert(authority))
    return outside.width * outside.height - outside.histogram()[0], basis


def candidate(
    session: Session, job: JobRecord, variant: CandidateVariant = "locked"
) -> tuple[JobAssetRecord, AssetRecord] | None:
    row = session.execute(
        select(JobAssetRecord, AssetRecord)
        .join(AssetRecord, AssetRecord.id == JobAssetRecord.asset_id)
        .where(
            JobAssetRecord.workspace_id == job.workspace_id,
            JobAssetRecord.job_id == job.id,
            JobAssetRecord.role
            == ("provider_raw" if variant == "original" else "locked_candidate"),
            AssetRecord.workspace_id == job.workspace_id,
            AssetRecord.lifecycle_status == "ready",
            AssetRecord.deleted_at.is_(None),
        )
        .order_by(JobAssetRecord.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    if variant == "original":
        if (row[1].asset_metadata or {}).get("immutable_provider_raw") is not True:
            return None
    elif row[0].validation.get("strict_lock_success") is not True:
        return None
    return row[0], row[1]


def requires_decision(session: Session, job: JobRecord) -> bool:
    if job.type != "local_edit" or candidate(session, job) is None:
        return False
    return (
        session.scalar(
            select(JobItemRecord.id)
            .where(
                JobItemRecord.job_id == job.id,
                JobItemRecord.error_code.like("LOCAL_EDIT_VISUAL_REVIEW%"),
            )
            .limit(1)
        )
        is not None
    )


async def resolve(
    session: Session,
    job: JobRecord,
    storage: ImageStorage,
    *,
    action: str,
    expected_sha256: str,
    actor_id: str,
    variant: CandidateVariant = "locked",
    allow_outside_selection_changes: bool = False,
) -> None:
    completed_selection = (
        action == "accept"
        and job.status == JobStatus.COMPLETED.value
        and candidate(session, job) is not None
    )
    if job.type != "local_edit" or (
        job.status != JobStatus.AWAITING_FINAL_REVIEW.value and not completed_selection
    ):
        raise ApiError(
            409, "LOCAL_EDIT_NOT_AWAITING_REVIEW", "当前任务没有待确认的修改版。"
        )
    if variant == "original" and (
        action != "accept" or not allow_outside_selection_changes
    ):
        raise ApiError(
            409,
            "LOCAL_EDIT_ORIGINAL_CHOICE_REQUIRED",
            "采用完整生成版需要明确同意保留选区外变化。",
        )
    found = candidate(session, job, variant)
    if action == "accept":
        # A regenerated version waits for explicit selection. The currently
        # reserved edit can adopt a better ancestor without another image call.
        ancestor = job
        for _ in range(16):
            if found is not None and found[1].sha256 == expected_sha256:
                break
            if not ancestor.retry_of_job_id:
                break
            parent = session.get(JobRecord, ancestor.retry_of_job_id)
            if (
                parent is None
                or parent.workspace_id != job.workspace_id
                or parent.type != "local_edit"
            ):
                break
            if any(
                parent.configuration.get(k) != job.configuration.get(k)
                for k in ("input", "settings")
            ):
                break
            ancestor = parent
            found = candidate(session, ancestor, variant)
    if found is None or found[1].sha256 != expected_sha256:
        raise ApiError(
            409, "LOCAL_EDIT_CANDIDATE_CHANGED", "候选已变化，请刷新后查看。"
        )
    relation, asset = found
    from .local_edit_billing import require_image_access

    require_image_access(session, asset)
    item = session.scalar(
        select(JobItemRecord).where(JobItemRecord.job_id == job.id).with_for_update()
    )
    if item is None or item.workspace_id != job.workspace_id:
        raise ApiError(409, "LOCAL_EDIT_CANDIDATE_MISSING", "候选缺少对应的任务条目。")
    previous_asset_ids: list[str] = []
    adoption_audit: dict[str, object] = {}
    if action == "review":
        if job.configuration.get("_local_edit_manual_review_count", 0) >= 1:
            raise ApiError(
                409,
                "LOCAL_EDIT_REVIEW_LIMIT_REACHED",
                "已复核过这张图，请预览后选择采用或重新生成。",
            )
        job.configuration = {
            **job.configuration,
            "_local_edit_review_only": True,
            "_local_edit_review_candidate_sha256": expected_sha256,
            "_local_edit_manual_review_count": 1,
        }
        item.status = JobItemStatus.PENDING.value
        item.stage = "queued_review"
        item.error_code = item.error_message = item.error_details = None
        item.finished_at = None
        item.state_version += 1
        job.error_code = job.error_message = job.error_details = None
        transition_job(job, JobStatus.PROCESSING, stage="visual_review", progress=90)
        add_outbox_event(
            session,
            workspace_id=job.workspace_id,
            job_id=job.id,
            event_type="job.dispatch_requested",
            suffix=f"local-review-{job.state_version}",
        )
    else:
        # Both variants must be immutable, paid and bound to these exact inputs.
        # Only an explicit full-image choice can authorize changes outside the mask.
        inputs = job.configuration.get("input", {})
        source = session.get(AssetRecord, inputs.get("source_asset_id"))
        mask = session.get(AssetRecord, inputs.get("selection_mask_asset_id"))
        if (
            source is None
            or mask is None
            or any(a.workspace_id != job.workspace_id for a in (source, mask))
        ):
            raise ApiError(
                409, "LOCAL_EDIT_INPUT_BINDING_INVALID", "原图或选区不可用。"
            )
        metadata = asset.asset_metadata or {}
        if (
            metadata.get("source_sha256") != source.sha256
            or metadata.get("mask_sha256") != mask.sha256
        ):
            raise ApiError(
                409, "LOCAL_EDIT_INPUT_BINDING_INVALID", "候选与当前原图或选区不一致。"
            )
        blobs = [await storage.read_bytes(a.object_key) for a in (source, mask, asset)]
        if any(
            hashlib.sha256(blob).hexdigest() != a.sha256
            for a, blob in zip((source, mask, asset), blobs, strict=True)
        ):
            raise ApiError(
                409, "LOCAL_EDIT_CANDIDATE_CHANGED", "图片内容已变化，本次采用已停止。"
            )
        with (
            Image.open(BytesIO(blobs[0])) as source_input,
            Image.open(BytesIO(blobs[1])) as selection_input,
            Image.open(BytesIO(blobs[2])) as output_input,
        ):
            src = ImageOps.exif_transpose(source_input).convert("RGBA")
            selection = ImageOps.exif_transpose(selection_input).convert("RGBA")
            output = output_input.convert("RGBA")
            alpha = selection.getchannel("A")
            basis = (
                alpha
                if alpha.getextrema() != (255, 255)
                else ImageOps.grayscale(selection)
            )
            authority = basis.point(lambda v: 255 if v > 127 else 0)
            if output.size != (asset.width, asset.height):
                raise ApiError(
                    409, "LOCAL_EDIT_CANDIDATE_CHANGED", "候选尺寸与保存记录不一致。"
                )
            if authority.size != src.size or (
                variant == "locked" and src.size != output.size
            ):
                raise ApiError(
                    409, "LOCAL_EDIT_PIXEL_LOCK_FAILED", "候选尺寸与原图不一致。"
                )
            outside_changed, measurement_basis = _outside_change_measurement(
                src, authority, output
            )
            if variant == "locked" and outside_changed:
                raise ApiError(
                    409,
                    "LOCAL_EDIT_PIXEL_LOCK_FAILED",
                    "候选存在选区外变化，不能采用。",
                )
        adoption_audit = {
            "source_sha256": source.sha256,
            "mask_sha256": mask.sha256,
            "outside_changed_pixels": outside_changed,
            "outside_change_measurement_basis": measurement_basis,
            "result_dimensions": [asset.width, asset.height],
        }
        deliveries = session.scalars(
            select(JobAssetRecord).where(
                JobAssetRecord.job_id == job.id,
                JobAssetRecord.job_item_id == item.id,
                JobAssetRecord.direction == "output",
                JobAssetRecord.is_deliverable.is_(True),
            )
        ).all()
        if any(row.asset_id == asset.id for row in deliveries):
            raise ApiError(
                409, "LOCAL_EDIT_ALREADY_ADOPTED", "这张图已经是当前采用结果。"
            )
        previous_asset_ids = [row.asset_id for row in deliveries]
        for delivery in deliveries:
            delivery.is_deliverable = False
        selected_output = session.scalar(
            select(JobAssetRecord).where(
                JobAssetRecord.job_id == job.id,
                JobAssetRecord.job_item_id == item.id,
                JobAssetRecord.direction == "output",
                JobAssetRecord.role == "local_edit_result",
                JobAssetRecord.ordinal == 0,
            )
        )
        if selected_output is None:
            selected_output = JobAssetRecord(
                workspace_id=job.workspace_id,
                job_id=job.id,
                job_item_id=item.id,
                asset_id=asset.id,
                direction="output",
                role="local_edit_result",
                ordinal=0,
            )
            session.add(selected_output)
        selected_output.asset_id = asset.id
        selected_output.is_deliverable = True
        selected_output.validation = {
            **relation.validation,
            "sha256": asset.sha256,
            "user_accepted": True,
            "candidate_variant": variant,
            "outside_selection_changes_authorized": variant == "original",
            "strict_lock_success": variant == "locked",
            "outside_changed_pixels": outside_changed,
            "outside_change_measurement_basis": measurement_basis,
            "delivery_status": "user_selected_original"
            if variant == "original"
            else "user_selected_locked",
        }
        if variant == "locked":
            selected_output.validation = {
                **selected_output.validation,
                "reviewed_artifact_sha256": asset.sha256,
            }
        else:
            selected_output.validation.pop("reviewed_artifact_sha256", None)
        item.status = JobItemStatus.SUCCEEDED.value
        item.stage = "generated"
        item.result_source = "generated"
        item.error_code = item.error_message = item.error_details = None
        item.finished_at = utc_now()
        item.state_version += 1
        job.succeeded_item_count, job.failed_item_count = 1, 0
        job.error_code = job.error_message = job.error_details = None
        if completed_selection:
            job.state_version += 1
        else:
            transition_job(job, JobStatus.COMPLETED, stage="completed", progress=100)
        session.flush()
        if not completed_selection:
            settle_credits(session, job, int(job.estimated_credits or 0))
    session.add(
        AuditEventRecord(
            workspace_id=job.workspace_id,
            actor_user_id=actor_id,
            action=f"masked_repair.user_{action}",
            resource_type="job",
            resource_id=job.id,
            request_id=actor_id,
            details={
                "candidate_sha256": expected_sha256,
                "asset_id": asset.id,
                "new_generation_requested": False,
                "candidate_variant": variant,
                "outside_selection_changes_authorized": variant == "original",
                "previous_asset_ids": previous_asset_ids if action == "accept" else [],
                **adoption_audit,
            },
        )
    )
