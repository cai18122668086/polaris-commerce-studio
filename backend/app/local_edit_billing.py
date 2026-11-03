"""Charge each completed generation before private image bytes become visible."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import ApiError
from .models import (
    AssetRecord,
    CreditLedgerEntryRecord,
    CreditReservationRecord,
    JobAssetRecord,
    JobRecord,
)
from .services import credit_enforcement_enabled, release_credits, settle_credits

BILLING_POLICY = "local-edit-generated-image-v1"


def receipt_for(session: Session, asset: AssetRecord) -> CreditReservationRecord | None:
    paid_job = (asset.asset_metadata or {}).get("billing_paid_job_id")
    receipts = []
    if isinstance(paid_job, str):
        direct = session.scalar(
            select(CreditReservationRecord).where(
                CreditReservationRecord.workspace_id == asset.workspace_id,
                CreditReservationRecord.job_id == paid_job,
                CreditReservationRecord.status == "settled",
                CreditReservationRecord.settled_credits > 0,
            )
        )
        if direct is not None:
            receipts.append(direct)
    # Older raw assets have no receipt metadata. Preserve paid generations and
    # block unpaid diagnostic originals without rewriting historical bills.
    receipts.extend(
        session.scalars(
            select(CreditReservationRecord)
            .join(JobRecord, JobRecord.id == CreditReservationRecord.job_id)
            .join(JobAssetRecord, JobAssetRecord.job_id == JobRecord.id)
            .where(
                CreditReservationRecord.workspace_id == asset.workspace_id,
                JobRecord.workspace_id == asset.workspace_id,
                JobRecord.type == "local_edit",
                JobAssetRecord.workspace_id == asset.workspace_id,
                JobAssetRecord.asset_id == asset.id,
                JobAssetRecord.role.in_(
                    ["provider_raw", "locked_candidate", "local_edit_result"]
                ),
                CreditReservationRecord.status == "settled",
                CreditReservationRecord.settled_credits > 0,
            )
        ).all()
    )
    for receipt in receipts:
        if not credit_enforcement_enabled(asset.workspace_id):
            return receipt
        debit = session.scalar(
            select(CreditLedgerEntryRecord.id)
            .where(
                CreditLedgerEntryRecord.reservation_id == receipt.id,
                CreditLedgerEntryRecord.workspace_id == asset.workspace_id,
                CreditLedgerEntryRecord.entry_type == "settle",
                CreditLedgerEntryRecord.delta_balance_credits
                == -receipt.settled_credits,
            )
            .limit(1)
        )
        if debit is not None:
            return receipt
    return None


def require_image_access(session: Session, asset: AssetRecord) -> None:
    metadata = asset.asset_metadata or {}
    legacy_masked_candidate = str(metadata.get("workflow_version", "")).startswith(
        "masked-repair-"
    ) and (
        metadata.get("immutable_provider_raw") is True
        or metadata.get("immutable_locked_candidate") is True
    )
    if metadata.get("billing_policy") != BILLING_POLICY and not legacy_masked_candidate:
        return
    if not credit_enforcement_enabled(asset.workspace_id):
        return
    if receipt_for(session, asset) is None:
        raise ApiError(
            409, "LOCAL_EDIT_IMAGE_NOT_SETTLED", "图片尚未完成结算，原图暂不可访问。"
        )


def has_paid_generation(session: Session, job: JobRecord) -> bool:
    raw = session.scalar(
        select(AssetRecord)
        .join(JobAssetRecord, JobAssetRecord.asset_id == AssetRecord.id)
        .where(
            JobAssetRecord.workspace_id == job.workspace_id,
            AssetRecord.workspace_id == job.workspace_id,
            JobAssetRecord.job_id == job.id,
            JobAssetRecord.role == "provider_raw",
        )
    )
    return raw is not None and receipt_for(session, raw) is not None


def settle_generation(session: Session, job_id: str, locked: AssetRecord) -> None:
    job = session.get(JobRecord, job_id, with_for_update=True)
    if job is None or job.status != "processing":
        raise RuntimeError("The generation is no longer authorized for publication.")
    raw = session.scalar(
        select(AssetRecord)
        .join(JobAssetRecord, JobAssetRecord.asset_id == AssetRecord.id)
        .where(
            JobAssetRecord.workspace_id == job.workspace_id,
            AssetRecord.workspace_id == job.workspace_id,
            JobAssetRecord.job_id == job.id,
            JobAssetRecord.role == "provider_raw",
        )
        .with_for_update(of=AssetRecord)
    )
    if raw is None:
        raise RuntimeError("Generation receipt is missing its immutable raw image.")
    paid = receipt_for(session, raw)
    if paid is not None and paid.job_id != job.id:
        # Recovery/review of an already paid generation never becomes a second bill.
        job.configuration = {
            **job.configuration,
            "_local_edit_generation_already_paid": True,
            "_local_edit_paid_source_job_id": paid.job_id,
        }
        release_credits(session, job)
        job.actual_credits = 0
    else:
        settle_credits(session, job, int(job.estimated_credits or 0))
        paid = session.scalar(
            select(CreditReservationRecord).where(
                CreditReservationRecord.workspace_id == job.workspace_id,
                CreditReservationRecord.job_id == job.id,
                CreditReservationRecord.status == "settled",
                CreditReservationRecord.settled_credits > 0,
            )
        )
    if credit_enforcement_enabled(job.workspace_id) and paid is None:
        raise RuntimeError("Image settlement did not complete; publication is blocked.")
    for asset in (raw, locked):
        asset.asset_metadata = {
            **(asset.asset_metadata or {}),
            "billing_policy": BILLING_POLICY,
            "billing_paid_job_id": paid.job_id if paid is not None else None,
        }
    session.flush()
