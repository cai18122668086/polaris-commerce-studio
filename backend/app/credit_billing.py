"""Customer credits are charged for successful output images, not API calls."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .domain import JobItemStatus, JobType
from .errors import ApiError
from .models import (
    AssetRecord,
    CreditReservationRecord,
    JobAssetRecord,
    JobItemRecord,
    JobRecord,
)

PRICING_VERSION = "image-credits-5-15-v1"
SINGLE_IMAGE_CREDITS = 5
PLANNED_IMAGE_CREDITS = 15
PRICING_KEY = "customer_credit_pricing"


def image_unit_credits(
    job_type: str, configuration: Mapping[str, Any] | None = None
) -> int:
    """Classify every executable job, including product-image presets."""
    kind = JobType(job_type)
    if kind == JobType.DOMESTIC_DETAIL_REVIEW:
        return 0  # Review/export/reconciliation produces no new customer image.
    if kind in {JobType.LOCAL_EDIT, JobType.MODEL_POSE_TRANSFER}:
        return SINGLE_IMAGE_CREDITS
    if kind == JobType.PRODUCT_IMAGE:
        settings = (configuration or {}).get("settings", configuration or {})
        return (
            PLANNED_IMAGE_CREDITS
            if settings.get("task_type") == "scene_main"
            else SINGLE_IMAGE_CREDITS
        )
    # Creative compositions, remix, domestic/cross-border detail, domestic
    # main-image campaigns and Amazon suites all include planning.
    return PLANNED_IMAGE_CREDITS


def bind_image_reservation(
    session: Session, job: JobRecord
) -> tuple[int, dict[str, Any]]:
    """Freeze a server-owned tariff and the exact runnable item IDs once.

    Preserved REUSED items are excluded. This also covers retry/clone children
    and the local-revision constructor, whose old estimate was always zero.
    """
    session.flush()
    ids = list(
        session.scalars(
            select(JobItemRecord.id)
            .where(
                JobItemRecord.workspace_id == job.workspace_id,
                JobItemRecord.job_id == job.id,
                JobItemRecord.status == JobItemStatus.PENDING.value,
            )
            .order_by(JobItemRecord.ordinal)
        )
    )
    unit = image_unit_credits(job.type, job.configuration)
    if not ids and job.expected_item_count and unit:
        raise ApiError(
            409, "CREDIT_ITEMS_NOT_READY", "创作图片数量尚未确定，请重新提交。"
        )
    job.estimated_credits = unit * len(ids)
    return job.estimated_credits, {
        "version": PRICING_VERSION,
        "credits_per_image": unit,
        "item_ids": ids,
    }


def successful_image_credits(session: Session, job: JobRecord) -> int | None:
    """None means a historical reservation: preserve its original accounting.

    A selected image recovered from its original call may become REUSED; it is
    charged once on this reservation, whereas preserved sibling IDs are absent.
    """
    reservation = session.scalar(
        select(CreditReservationRecord).where(
            CreditReservationRecord.workspace_id == job.workspace_id,
            CreditReservationRecord.job_id == job.id,
        )
    )
    if reservation is None:
        return None
    pricing = reservation.pricing_snapshot
    if not isinstance(pricing, dict) or pricing.get("version") != PRICING_VERSION:
        return None
    # Later reviews, retention or output removal must not rewrite a settled bill.
    if reservation.status in {"settled", "released"}:
        return reservation.settled_credits
    unit = pricing["credits_per_image"]
    ids = pricing["item_ids"]
    billable: ColumnElement[bool] = JobItemRecord.status.in_(
        [JobItemStatus.SUCCEEDED.value, JobItemStatus.REUSED.value]
    )
    if job.type == JobType.REFERENCE_REMIX.value and job.configuration.get(
        "replica_session_id"
    ):
        # Replica images can be downloaded before the group attempt settles.
        # A later stop/failure must not refund images already delivered. The
        # server-owned marker survives soft deletion; distinct item IDs still
        # charge each image once and exclude preserved retry siblings.
        billable = or_(
            billable,
            and_(
                AssetRecord.workspace_id == job.workspace_id,
                AssetRecord.origin_kind == "generated",
                AssetRecord.asset_metadata["replica_incremental"]
                .as_boolean()
                .is_(True),
            ),
        )
    succeeded = (
        session.scalar(
            select(func.count(func.distinct(JobItemRecord.id)))
            .select_from(JobItemRecord)
            .join(JobAssetRecord, JobAssetRecord.job_item_id == JobItemRecord.id)
            .join(AssetRecord, AssetRecord.id == JobAssetRecord.asset_id)
            .where(
                JobAssetRecord.workspace_id == job.workspace_id,
                JobAssetRecord.job_id == job.id,
                JobAssetRecord.direction == "output",
                JobAssetRecord.is_deliverable.is_(True),
                JobItemRecord.workspace_id == job.workspace_id,
                JobItemRecord.job_id == job.id,
                JobItemRecord.id.in_(ids),
                billable,
            )
        )
        or 0
    )
    return int(succeeded) * int(unit)


def pricing_catalog() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for kind in JobType:
        if kind == JobType.PRODUCT_IMAGE:
            for preset in (
                "scene_main",
                "white_background",
                "model_image",
                "change_model",
                "try_on",
                "change_scene",
                "change_background",
                "change_color",
            ):
                items.append(
                    {
                        "job_type": kind.value,
                        "task_type": preset,
                        "credits_per_image": image_unit_credits(
                            kind.value, {"task_type": preset}
                        ),
                    }
                )
        else:
            items.append(
                {
                    "job_type": kind.value,
                    "task_type": None,
                    "credits_per_image": image_unit_credits(kind.value),
                }
            )
    return items
