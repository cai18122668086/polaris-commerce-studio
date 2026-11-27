"""Reconcile and, after explicit user confirmation, redo only missing pages.

The image endpoint has no result lookup, so "what the supplier returned" is
what this system holds for the page: its delivered asset, its receipt and the
image staged for that receipt's attempt. A page is missing when none of these
delivered it. Pages whose image is in the local stage are recovered without a
new call; only the rest are generated again, and only after the user confirms
the exact page list shown to them. Credits are charged per delivered page,
once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .aurora_main_image_fast_provider import RECEIPTS_KEY
from .aurora_main_image_planner import PAGE_ROLES
from .credit_billing import image_unit_credits
from .domain import JobItemStatus, JobStatus, JobType
from .errors import ApiError
from .generation_image_stage import GenerationImageStage
from .models import JobItemRecord, JobRecord, utc_now

UNRESOLVED_STATES = frozenset({"invoked", "unknown"})
ABANDONED_STATE = "abandoned_unknown"
CONFIRMATION_KEY = "_main_image_missing_pages_confirmation"
_PAGE_NAMES = ("搜索主图", "身份主视觉", "核心卖点", "场景使用", "细节信任", "规格收口")
_REASONS = {
    "invoked": "已发出生成请求，结果没有返回",
    "unknown": "结果未确认",
    "rejected": "生成失败",
    "returned": "图片已返回但未交付",
    "storage_pending": "图片已返回但未入库",
    ABANDONED_STATE: "结果未确认（已确认重做）",
    None: "未生成",
}
CHARGE_RULE = (
    "只对成功交付的页扣费；生成失败或未交付的页不扣费，已交付的页不会重做、不会再扣费。"
)


def _is_fast_main_image(job: JobRecord) -> bool:
    settings = (job.configuration or {}).get("settings") or {}
    return (
        job.type == JobType.DOMESTIC_MAIN_IMAGE.value
        and settings.get("main_image_speed") == "native_fast"
    )


def existing_redo(session: Session, job: JobRecord) -> JobRecord | None:
    """The redo already started from this job (not failed or cancelled), if any."""
    return session.scalar(
        select(JobRecord)
        .where(
            JobRecord.retry_of_job_id == job.id,
            JobRecord.workspace_id == job.workspace_id,
            JobRecord.status.not_in(
                [JobStatus.FAILED.value, JobStatus.CANCELLED.value]
            ),
        )
        .order_by(JobRecord.created_at.desc())
        .limit(1)
    )


def reconcile(
    session: Session, job: JobRecord, stage_root: Path | None
) -> dict[str, Any]:
    """Which pages are delivered, recoverable locally, or really missing."""

    if not _is_fast_main_image(job):
        raise ApiError(
            409, "MISSING_PAGES_NOT_APPLICABLE", "只有主图六件套支持补齐缺页。"
        )
    items = {
        item.ordinal: item
        for item in session.scalars(
            select(JobItemRecord).where(JobItemRecord.job_id == job.id)
        )
    }
    receipts: Mapping[str, Any] = (job.configuration or {}).get(RECEIPTS_KEY) or {}
    stage = GenerationImageStage(stage_root, "main-image") if stage_root else None
    unit = image_unit_credits(JobType.DOMESTIC_MAIN_IMAGE, job.configuration)
    delivered, missing = [], []
    for ordinal in range(len(PAGE_ROLES)):
        item = items.get(ordinal)
        if item is not None and item.status in {
            JobItemStatus.SUCCEEDED.value,
            JobItemStatus.REUSED.value,
        }:
            delivered.append(ordinal)
            continue
        receipt = receipts.get(str(ordinal)) or {}
        state = receipt.get("state")
        # A late receipt that already holds the image, or an image waiting in
        # the local stage for this receipt, is recovered without a new call.
        local = state in {"returned", "storage_pending"} or bool(
            stage is not None
            and state in UNRESOLVED_STATES | {ABANDONED_STATE}
            and receipt.get("attempt_id")
            and stage.path(
                job.workspace_id, receipt["job_id"], receipt["attempt_id"]
            ).is_file()
        )
        missing.append(
            {
                "page_index": ordinal,
                "page_number": ordinal + 1,
                "page_name": _PAGE_NAMES[ordinal],
                "page_role": PAGE_ROLES[ordinal],
                "reason": _REASONS.get(state, _REASONS[None]),
                "recover_from_local_result": local,
            }
        )
    return {
        "job_id": job.id,
        "delivered_pages": delivered,
        "missing_pages": missing,
        "credits_per_page": unit,
        "max_credits": unit * len(missing),
        "charge_rule": CHARGE_RULE,
        **_redo_fields(session, job),
    }


def _redo_fields(session: Session, job: JobRecord) -> dict[str, Any]:
    redo = existing_redo(session, job)
    return {
        "redo_job_id": redo.id if redo else None,
        "redo_job_status": redo.status if redo else None,
    }


def confirm_and_release(
    session: Session,
    job: JobRecord,
    confirmed_pages: Sequence[int],
    stage_root: Path | None,
) -> list[int]:
    """Record the user's confirmation and release unresolved receipts.

    The source job row is locked by the caller (``for_update``), so double
    clicks and concurrent requests are serialized; only one redo per source
    job may exist, and the confirmation must match the pages missing now.
    """

    if job.status not in {JobStatus.PARTIAL.value, JobStatus.FAILED.value}:
        raise ApiError(
            409, "JOB_NOT_RETRYABLE", "只有部分成功或失败的任务可以补齐缺页。"
        )
    redo = existing_redo(session, job)
    existing = redo.id if redo is not None else None
    if existing is not None:
        raise ApiError(
            409,
            "MISSING_PAGES_REDO_EXISTS",
            "这个任务已经在补齐缺页，请勿重复提交。",
            {"retry_job_id": existing},
        )
    state = reconcile(session, job, stage_root)
    missing = sorted(page["page_index"] for page in state["missing_pages"])
    if not missing:
        raise ApiError(409, "NO_MISSING_PAGES", "六张图都已交付，没有需要补齐的页。")
    if sorted(set(confirmed_pages)) != missing or len(confirmed_pages) != len(missing):
        raise ApiError(
            409,
            "MISSING_PAGES_CHANGED",
            "缺页情况已变化，请刷新后重新确认。",
            {"missing_pages": missing},
        )
    now = utc_now().isoformat()
    receipts = dict((job.configuration or {}).get(RECEIPTS_KEY) or {})
    for page in missing:
        receipt = receipts.get(str(page))
        if receipt and receipt.get("state") in UNRESOLVED_STATES:
            receipts[str(page)] = {
                **receipt,
                "state": ABANDONED_STATE,
                "previous_state": receipt.get("state"),
                "abandoned_at": now,
                # The supplier may have charged for the lost call; it stays
                # an unconfirmed supplier cost and is never billed to the user.
                "supplier_cost_status": "unconfirmed",
            }
    job.configuration = {
        **job.configuration,
        RECEIPTS_KEY: receipts,
        CONFIRMATION_KEY: {
            "pages": missing,
            "confirmed_at": now,
            "credits_per_page": state["credits_per_page"],
            "charge_rule": CHARGE_RULE,
        },
    }
    return missing
