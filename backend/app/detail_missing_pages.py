"""Detail 精致版: reconcile and, after explicit user confirmation, redo missing pages.

Same contract as the main image (aurora_main_image_missing_pages): the image
endpoint has no result lookup, so a page whose call never came back (or whose
outcome is unknown, e.g. an HTTP 503 after dispatch) stays fenced against a
blind resubmit. The user sees exactly which pages are missing and why, and
confirms them; only then are those pages' unresolved receipts released for one
new call in a failed-scope retry. Delivered pages are never redone, and credits
are charged per delivered page only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import detail_fast_runtime
from .credit_billing import image_unit_credits
from .detail_fast_gateway import RECEIPTS
from .domain import JobItemStatus, JobStatus, JobType
from .errors import ApiError
from .generation_image_stage import GenerationImageStage
from .models import JobItemRecord, JobPlanRecord, JobRecord, utc_now

UNRESOLVED_STATES = frozenset({"invoked", "unknown"})
ABANDONED_STATE = "abandoned_unknown"
CONFIRMATION_KEY = "_detail_missing_pages_confirmation"
_REASONS = {
    "invoked": "已发出生成请求，结果没有返回",
    "unknown": "结果未确认",
    "failed": "生成失败",
    "returned": "图片已返回但未交付",
    "storage_pending": "图片已返回但未入库",
    ABANDONED_STATE: "结果未确认（已确认重做）",
    None: "未生成",
}
CHARGE_RULE = (
    "只对成功交付的页扣费；生成失败或未交付的页不扣费，已交付的页不会重做、不会再扣费。"
)


def applicable(job: JobRecord) -> bool:
    return job.type == JobType.DETAIL_PACK.value and detail_fast_runtime.is_fast(
        job.configuration or {}
    )


def _page_titles(session: Session, job: JobRecord) -> dict[int, tuple[str, str]]:
    plan = session.scalar(
        select(JobPlanRecord)
        .where(JobPlanRecord.job_id == job.id)
        .order_by(JobPlanRecord.revision.desc())
        .limit(1)
    )
    pages = (plan.payload or {}).get("pages") if plan is not None else None
    titles: dict[int, tuple[str, str]] = {}
    for index, page in enumerate(pages if isinstance(pages, list) else []):
        if isinstance(page, Mapping):
            titles[index] = (str(page.get("title") or ""), str(page.get("role") or ""))
    return titles


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

    if not applicable(job):
        raise ApiError(
            409, "MISSING_PAGES_NOT_APPLICABLE", "只有国内详情精致版支持补齐缺页。"
        )
    items = sorted(
        session.scalars(select(JobItemRecord).where(JobItemRecord.job_id == job.id)),
        key=lambda item: item.ordinal,
    )
    receipts: Mapping[str, Any] = (job.configuration or {}).get(RECEIPTS) or {}
    stage = GenerationImageStage(stage_root, "detail") if stage_root else None
    titles = _page_titles(session, job)
    unit = image_unit_credits(JobType.DETAIL_PACK, job.configuration)
    delivered, missing = [], []
    for item in items:
        if item.status in {JobItemStatus.SUCCEEDED.value, JobItemStatus.REUSED.value}:
            delivered.append(item.ordinal)
            continue
        receipt = receipts.get(item.id) or {}
        state = receipt.get("state")
        local = state in {"returned", "storage_pending"} or bool(
            stage is not None
            and state in UNRESOLVED_STATES | {ABANDONED_STATE}
            and receipt.get("attempt_id")
            and stage.path(
                job.workspace_id, receipt["job_id"], receipt["attempt_id"]
            ).is_file()
        )
        title, role = titles.get(item.ordinal, ("", ""))
        missing.append(
            {
                "page_index": item.ordinal,
                "page_number": item.ordinal + 1,
                "page_name": title or f"第 {item.ordinal + 1} 屏",
                "page_role": role,
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
    """Record the user's confirmation and release the pages' unresolved receipts.

    The caller holds the source job row ``for_update``; only one redo per
    source job may be active, and the confirmation must equal the pages that
    are missing now.
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
        raise ApiError(409, "NO_MISSING_PAGES", "所有屏都已交付，没有需要补齐的页。")
    if sorted(set(confirmed_pages)) != missing or len(confirmed_pages) != len(missing):
        raise ApiError(
            409,
            "MISSING_PAGES_CHANGED",
            "缺页情况已变化，请刷新后重新确认。",
            {"missing_pages": missing},
        )
    now = utc_now().isoformat()
    by_ordinal = {
        item.ordinal: item.id
        for item in session.scalars(
            select(JobItemRecord).where(JobItemRecord.job_id == job.id)
        )
    }
    receipts = dict((job.configuration or {}).get(RECEIPTS) or {})
    for page in missing:
        item_id = by_ordinal.get(page)
        receipt = receipts.get(item_id) if item_id else None
        if receipt and receipt.get("state") in UNRESOLVED_STATES:
            receipts[item_id] = {
                **receipt,
                "state": ABANDONED_STATE,
                "previous_state": receipt.get("state"),
                "abandoned_at": now,
                # The supplier may have charged for the lost call; it stays an
                # unconfirmed supplier cost and is never billed to the user.
                "supplier_cost_status": "unconfirmed",
            }
    job.configuration = {
        **job.configuration,
        RECEIPTS: receipts,
        CONFIRMATION_KEY: {
            "pages": missing,
            "confirmed_at": now,
            "credits_per_page": state["credits_per_page"],
            "charge_rule": CHARGE_RULE,
        },
    }
    return missing


def released(job: JobRecord, item_ids: Sequence[str]) -> bool:
    """True when every given item's unresolved receipt was released by the user."""
    receipts = (job.configuration or {}).get(RECEIPTS) or {}
    return all(
        (receipts.get(item_id) or {}).get("state") in {ABANDONED_STATE, None, "failed"}
        for item_id in item_ids
    )
