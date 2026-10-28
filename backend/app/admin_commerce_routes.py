"""Customer operations over the authoritative payment and credit ledger."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .admin_auth import (
    AdminDependency,
    SessionDependency,
    get_admin_record,
    is_super_admin,
)
from .admin_commerce_models import (
    CreditAdjustmentRecord,
    CustomerSupportRecord,
    ManualRefundRecord,
    SupportCaseRecord,
)
from .admin_log_routes import _safe_error
from .auth import Principal
from .credit_memberships import aware, expire, grant, refresh
from .credit_payment_routes import _query_gateway_order, _settle_verified_purchase
from .errors import ApiError
from .models import (
    AuditEventRecord,
    CreditGrantRecord,
    CreditLedgerEntryRecord,
    CreditMembershipRecord,
    CreditPurchaseRecord,
    JobRecord,
    UserRecord,
    WorkspaceCreditAccountRecord,
    WorkspaceRecord,
    utc_now,
)
from .services import credit_enforcement_enabled, new_id, require_idempotency_key


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/admin/commerce",
    tags=["admin-commerce"],
    dependencies=[Depends(no_store)],
)


def check_permission(
    request: Request, session: Session, actor: Principal, permission: str
) -> None:
    if is_super_admin(actor, session, request.app.state.settings):
        return
    record = get_admin_record(session, actor.user_id)
    if record is None or permission not in record.permissions:
        raise ApiError(
            403, "COMMERCE_PERMISSION_REQUIRED", "没有执行此项客户运营操作的权限。"
        )


def reader(
    request: Request, session: SessionDependency, actor: AdminDependency
) -> Principal:
    check_permission(request, session, actor, "commerce:read")
    return actor


Reader = Annotated[Principal, Depends(reader)]


def audit(
    session: Session,
    request: Request,
    actor: Principal,
    workspace: str,
    action: str,
    resource: str,
    identifier: str,
    details: dict[str, Any],
) -> None:
    session.add(
        AuditEventRecord(
            workspace_id=workspace,
            actor_user_id=actor.user_id,
            action="commerce." + action,
            resource_type=resource,
            resource_id=identifier,
            request_id=getattr(request.state, "request_id", None),
            details=details,
        )
    )


def stamp(value: datetime | None) -> str | None:
    return aware(value).isoformat() if value else None


def page(
    session: Session, statement: Any, limit: int, offset: int
) -> tuple[list[Any], dict[str, Any]]:
    total = (
        session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        or 0
    )
    return list(session.execute(statement.limit(limit).offset(offset))), {
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }


def wallet(session: Session, workspace: str) -> WorkspaceCreditAccountRecord:
    return refresh(session, workspace)


def entry(
    session: Session,
    account: WorkspaceCreditAccountRecord,
    kind: str,
    balance: int,
    reserved: int,
    description: str,
) -> CreditLedgerEntryRecord:
    row = CreditLedgerEntryRecord(
        workspace_id=account.workspace_id,
        entry_type=kind,
        delta_balance_credits=balance,
        delta_reserved_credits=reserved,
        balance_after_credits=account.balance_credits,
        reserved_after_credits=account.reserved_credits,
        description=description[:200],
    )
    session.add(row)
    session.flush()
    return row


def order_lots(
    session: Session, order: CreditPurchaseRecord
) -> list[CreditGrantRecord]:
    return list(
        session.scalars(
            select(CreditGrantRecord)
            .where(
                CreditGrantRecord.workspace_id == order.workspace_id,
                or_(
                    CreditGrantRecord.source_key == order.id,
                    CreditGrantRecord.source_key.startswith(
                        order.id + ":", autoescape=True
                    ),
                ),
            )
            .order_by(CreditGrantRecord.created_at, CreditGrantRecord.id)
        )
    )


def refund_item(row: ManualRefundRecord) -> dict[str, Any]:
    return {
        k: getattr(row, k)
        for k in [
            "id",
            "purchase_id",
            "workspace_id",
            "amount_fen",
            "credits",
            "status",
            "reason",
            "receipt_reference",
            "result_note",
            "actor_user_id",
            "confirmed_by_user_id",
            "hold_ledger_entry_id",
            "result_ledger_entry_id",
        ]
    } | {
        "created_at": stamp(row.created_at),
        "confirmed_at": stamp(row.confirmed_at),
        "gateway_result": "人工退款流程，未调用自动退款接口",
    }


def order_item(
    session: Session, row: CreditPurchaseRecord, email: str | None = None
) -> dict[str, Any]:
    lots = order_lots(session, row)
    refunds = list(
        session.scalars(
            select(ManualRefundRecord).where(ManualRefundRecord.purchase_id == row.id)
        )
    )
    paid_back = sum(r.amount_fen for r in refunds if r.status == "completed")
    pending = sum(r.amount_fen for r in refunds if r.status == "processing")
    remaining = sum(lot.remaining for lot in lots)
    held = sum(lot.held for lot in lots)
    revoked = sum(r.credits for r in refunds if r.status == "completed")
    issued = sum(lot.amount for lot in lots)
    terms = row.product_snapshot or {}
    return {
        k: getattr(row, k)
        for k in [
            "id",
            "workspace_id",
            "created_by_user_id",
            "package_id",
            "package_name",
            "amount_fen",
            "credits",
            "status",
            "gateway_trade_no",
            "ledger_entry_id",
        ]
    } | {
        "email": email,
        "created_at": stamp(row.created_at),
        "paid_at": stamp(row.paid_at),
        "product_kind": terms.get("kind", "pack"),
        "bonus_credits": terms.get("bonus_credits"),
        "months": terms.get("months", 0),
        "issued_credits": issued,
        "remaining_credits": remaining,
        "held_credits": held,
        "used_or_expired_credits": max(0, issued - remaining - revoked),
        "refunded_fen": paid_back,
        "processing_refund_fen": pending,
        "refundable_fen": max(0, row.amount_fen - paid_back - pending)
        if row.status == "paid"
        else 0,
        "refundable_credits": sum(
            lot.remaining - lot.held
            for lot in lots
            if lot.expires_at is None or aware(lot.expires_at) > aware(utc_now())
        ),
        "refunds": [refund_item(r) for r in refunds],
    }


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteBody(StrictBody):
    note: str = Field(max_length=4000)


class AdjustmentBody(StrictBody):
    kind: Literal["gift", "compensation"]
    credits: int = Field(gt=0, le=100000, strict=True)
    reason: str = Field(min_length=3, max_length=500)
    job_id: str | None = Field(default=None, max_length=40)

    @field_validator("reason")
    @classmethod
    def reason_nonblank(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("请填写具体原因")
        return value.strip()


class CaseBody(StrictBody):
    workspace_id: str = Field(max_length=40)
    job_id: str | None = Field(default=None, max_length=40)
    issue: str = Field(min_length=3, max_length=4000)


class CaseUpdate(StrictBody):
    status: Literal["open", "in_progress", "resolved"]
    resolution: str = Field(max_length=4000)


class RefundBody(StrictBody):
    amount_fen: int = Field(gt=0, strict=True)
    credits: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=3, max_length=500)
    cancel_future_membership: bool = False


class RefundResult(StrictBody):
    status: Literal["completed", "rejected"]
    confirm_order_id: str = Field(max_length=40)
    receipt_reference: str = Field(default="", max_length=500)
    result_note: str = Field(min_length=3, max_length=500)
    receipt_verified: bool = False


@router.get("/access")
def access(
    request: Request, session: SessionDependency, actor: Reader
) -> dict[str, Any]:
    permissions = []
    for permission in [
        "commerce:read",
        "credits:manage",
        "refunds:manage",
        "support:manage",
    ]:
        try:
            check_permission(request, session, actor, permission)
            permissions.append(permission)
        except ApiError:
            pass
    return {
        "permissions": permissions,
        "global_enforcement_enabled": credit_enforcement_enabled(),
        "refund_mode": "manual",
    }


@router.get("/overview")
def overview(session: SessionDependency, _actor: Reader) -> dict[str, Any]:
    return {
        "customers": session.scalar(
            select(func.count()).select_from(WorkspaceCreditAccountRecord)
        )
        or 0,
        "paid_fen": session.scalar(
            select(func.coalesce(func.sum(CreditPurchaseRecord.amount_fen), 0)).where(
                CreditPurchaseRecord.status == "paid"
            )
        )
        or 0,
        "refunded_fen": session.scalar(
            select(func.coalesce(func.sum(ManualRefundRecord.amount_fen), 0)).where(
                ManualRefundRecord.status == "completed"
            )
        )
        or 0,
        "pending_refunds": session.scalar(
            select(func.count())
            .select_from(ManualRefundRecord)
            .where(ManualRefundRecord.status == "processing")
        )
        or 0,
        "open_cases": session.scalar(
            select(func.count())
            .select_from(SupportCaseRecord)
            .where(SupportCaseRecord.status != "resolved")
        )
        or 0,
    }


@router.get("/customers")
def customers(
    session: SessionDependency,
    _actor: Reader,
    search: str = Query("", max_length=320),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    statement = (
        select(WorkspaceRecord, UserRecord, WorkspaceCreditAccountRecord)
        .join(UserRecord, UserRecord.id == WorkspaceRecord.created_by_user_id)
        .join(
            WorkspaceCreditAccountRecord,
            WorkspaceCreditAccountRecord.workspace_id == WorkspaceRecord.id,
        )
    )
    if search.strip():
        statement = statement.where(
            or_(
                UserRecord.email_normalized.icontains(search.strip(), autoescape=True),
                UserRecord.display_name.icontains(search.strip(), autoescape=True),
                WorkspaceRecord.id.icontains(search.strip(), autoescape=True),
            )
        )
    rows, pagination = page(
        session,
        statement.order_by(WorkspaceRecord.created_at.desc(), WorkspaceRecord.id),
        limit,
        offset,
    )
    ids = [w.id for w, _, _ in rows]
    totals = {
        workspace: amount
        for workspace, amount in session.execute(
            select(
                CreditPurchaseRecord.workspace_id,
                func.sum(CreditPurchaseRecord.amount_fen),
            )
            .where(
                CreditPurchaseRecord.workspace_id.in_(ids),
                CreditPurchaseRecord.status == "paid",
            )
            .group_by(CreditPurchaseRecord.workspace_id)
        ).all()
    }
    usage = {
        workspace: last
        for workspace, last in session.execute(
            select(JobRecord.workspace_id, func.max(JobRecord.created_at))
            .where(JobRecord.workspace_id.in_(ids))
            .group_by(JobRecord.workspace_id)
        ).all()
    }
    profiles = {
        r.workspace_id: r
        for r in session.scalars(
            select(CustomerSupportRecord).where(
                CustomerSupportRecord.workspace_id.in_(ids)
            )
        )
    }
    spent = {
        workspace: amount
        for workspace, amount in session.execute(
            select(
                CreditLedgerEntryRecord.workspace_id,
                -func.sum(CreditLedgerEntryRecord.delta_balance_credits),
            )
            .where(
                CreditLedgerEntryRecord.workspace_id.in_(ids),
                CreditLedgerEntryRecord.entry_type == "settle",
            )
            .group_by(CreditLedgerEntryRecord.workspace_id)
        ).all()
    }
    items = [
        {
            "workspace_id": w.id,
            "workspace_name": w.name,
            "user_id": u.id,
            "email": u.email_normalized,
            "display_name": u.display_name,
            "status": u.status,
            "balance_credits": a.balance_credits,
            "reserved_credits": a.reserved_credits,
            "available_credits": a.balance_credits - a.reserved_credits,
            "paid_fen": totals.get(w.id, 0),
            "consumed_credits": spent.get(w.id, 0),
            "last_used_at": stamp(usage.get(w.id)),
            "last_login_at": stamp(u.last_login_at),
            "note": profiles[w.id].note if w.id in profiles else "",
            "enforcement_enabled": credit_enforcement_enabled(w.id),
        }
        for w, u, a in rows
    ]
    return {"items": items, "pagination": pagination}


@router.patch("/customers/{workspace_id}/note")
def customer_note(
    workspace_id: str,
    body: NoteBody,
    request: Request,
    session: SessionDependency,
    actor: Reader,
) -> dict[str, Any]:
    check_permission(request, session, actor, "support:manage")
    if session.get(WorkspaceRecord, workspace_id) is None:
        raise ApiError(404, "CUSTOMER_NOT_FOUND", "客户工作区不存在。")
    row = session.get(CustomerSupportRecord, workspace_id, with_for_update=True)
    if row is None:
        row = CustomerSupportRecord(
            workspace_id=workspace_id, updated_by_user_id=actor.user_id
        )
        session.add(row)
    row.note = body.note
    row.updated_by_user_id = actor.user_id
    audit(
        session,
        request,
        actor,
        workspace_id,
        "note_updated",
        "customer",
        workspace_id,
        {"note": body.note},
    )
    session.commit()
    return {"saved": True}


@router.post("/customers/{workspace_id}/adjustments", status_code=201)
def adjust(
    workspace_id: str,
    body: AdjustmentBody,
    request: Request,
    session: SessionDependency,
    actor: Reader,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    check_permission(request, session, actor, "credits:manage")
    key = require_idempotency_key(idempotency_key)
    account = wallet(session, workspace_id)
    existing = session.scalar(
        select(CreditAdjustmentRecord).where(
            CreditAdjustmentRecord.workspace_id == workspace_id,
            CreditAdjustmentRecord.actor_user_id == actor.user_id,
            CreditAdjustmentRecord.request_key == key,
        )
    )
    if existing:
        if (existing.kind, existing.credits, existing.reason, existing.job_id) != (
            body.kind,
            body.credits,
            body.reason,
            body.job_id,
        ):
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "操作内容已改变，请重新确认。")
        return {"id": existing.id, "ledger_entry_id": existing.ledger_entry_id}
    if body.job_id:
        job = session.get(JobRecord, body.job_id)
        if job is None or job.workspace_id != workspace_id:
            raise ApiError(422, "JOB_WORKSPACE_MISMATCH", "关联任务不属于该客户。")
    if body.kind == "compensation" and not body.job_id:
        raise ApiError(422, "COMPENSATION_JOB_REQUIRED", "补偿必须关联原生成任务。")
    identifier = new_id("adj")
    lot = grant(
        session,
        account,
        identifier,
        body.credits,
        None,
        ("人工赠送" if body.kind == "gift" else "售后补偿") + " · " + body.reason[:120],
        kind=body.kind,
    )
    assert lot.ledger_entry_id is not None
    session.add(
        CreditAdjustmentRecord(
            id=identifier,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            request_key=key,
            kind=body.kind,
            credits=body.credits,
            reason=body.reason,
            job_id=body.job_id,
            ledger_entry_id=lot.ledger_entry_id,
        )
    )
    ledger = session.get(CreditLedgerEntryRecord, lot.ledger_entry_id)
    assert ledger is not None
    ledger.job_id = body.job_id
    audit(
        session,
        request,
        actor,
        workspace_id,
        "credits_" + body.kind,
        "credit_adjustment",
        identifier,
        body.model_dump(),
    )
    session.commit()
    return {"id": identifier, "ledger_entry_id": lot.ledger_entry_id}


@router.get("/orders")
def orders(
    session: SessionDependency,
    _actor: Reader,
    workspace_id: str | None = None,
    search: str = Query("", max_length=320),
    status: Literal["pending", "paid"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    statement = select(CreditPurchaseRecord, UserRecord.email_normalized).join(
        UserRecord, UserRecord.id == CreditPurchaseRecord.created_by_user_id
    )
    if workspace_id:
        statement = statement.where(CreditPurchaseRecord.workspace_id == workspace_id)
    if status:
        statement = statement.where(CreditPurchaseRecord.status == status)
    if since:
        statement = statement.where(CreditPurchaseRecord.created_at >= since)
    if until:
        statement = statement.where(CreditPurchaseRecord.created_at < until)
    if search.strip():
        statement = statement.where(
            or_(
                UserRecord.email_normalized.icontains(search.strip(), autoescape=True),
                CreditPurchaseRecord.id.icontains(search.strip(), autoescape=True),
                CreditPurchaseRecord.gateway_trade_no.icontains(
                    search.strip(), autoescape=True
                ),
            )
        )
    rows, pagination = page(
        session,
        statement.order_by(
            CreditPurchaseRecord.created_at.desc(), CreditPurchaseRecord.id
        ),
        limit,
        offset,
    )
    return {
        "items": [order_item(session, r, email) for r, email in rows],
        "pagination": pagination,
    }


@router.post("/orders/{purchase_id}/reconcile")
def reconcile(
    purchase_id: str, request: Request, session: SessionDependency, actor: Reader
) -> dict[str, Any]:
    check_permission(request, session, actor, "credits:manage")
    row = session.get(CreditPurchaseRecord, purchase_id)
    if row is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "订单不存在。")
    merchant, workspace = row.merchant_pid, row.workspace_id
    session.rollback()
    data = _query_gateway_order(request.app.state.settings, merchant, purchase_id)
    if data["status"] == 1:
        parameters = {
            k: data[k]
            for k in [
                "pid",
                "out_trade_no",
                "trade_no",
                "type",
                "name",
                "money",
                "param",
            ]
        }
        parameters["trade_status"] = "TRADE_SUCCESS"
        _settle_verified_purchase(session, parameters)
    row = session.get(CreditPurchaseRecord, purchase_id, populate_existing=True)
    assert row is not None
    audit(
        session,
        request,
        actor,
        workspace,
        "payment_reconciled",
        "credit_purchase",
        purchase_id,
        {"gateway_paid": data["status"] == 1, "local_status": row.status},
    )
    session.commit()
    return {"order": order_item(session, row), "gateway_paid": data["status"] == 1}


@router.get("/ledger")
def ledger(
    session: SessionDependency,
    _actor: Reader,
    workspace_id: str | None = None,
    entry_type: str | None = None,
    search: str = Query("", max_length=320),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    statement = (
        select(CreditLedgerEntryRecord)
        .join(
            WorkspaceRecord, WorkspaceRecord.id == CreditLedgerEntryRecord.workspace_id
        )
        .join(UserRecord, UserRecord.id == WorkspaceRecord.created_by_user_id)
    )
    if workspace_id:
        statement = statement.where(
            CreditLedgerEntryRecord.workspace_id == workspace_id
        )
    if entry_type:
        statement = statement.where(CreditLedgerEntryRecord.entry_type == entry_type)
    if search.strip():
        statement = statement.where(
            or_(
                UserRecord.email_normalized.icontains(search.strip(), autoescape=True),
                CreditLedgerEntryRecord.job_id.icontains(
                    search.strip(), autoescape=True
                ),
                CreditLedgerEntryRecord.description.icontains(
                    search.strip(), autoescape=True
                ),
            )
        )
    rows, pagination = page(
        session, statement.order_by(CreditLedgerEntryRecord.id.desc()), limit, offset
    )
    ids = [row.id for (row,) in rows]
    origins = {
        lot.ledger_entry_id: lot.source_key.split(":")[0]
        for lot in session.scalars(
            select(CreditGrantRecord).where(CreditGrantRecord.ledger_entry_id.in_(ids))
        )
    }
    for order in session.scalars(
        select(CreditPurchaseRecord).where(
            CreditPurchaseRecord.ledger_entry_id.in_(ids)
        )
    ):
        origins[order.ledger_entry_id] = order.id
    refunds = {
        eid: r
        for r in session.scalars(
            select(ManualRefundRecord).where(
                or_(
                    ManualRefundRecord.hold_ledger_entry_id.in_(ids),
                    ManualRefundRecord.result_ledger_entry_id.in_(ids),
                )
            )
        )
        for eid in [r.hold_ledger_entry_id, r.result_ledger_entry_id]
        if eid is not None
    }
    adjustments = {
        a.ledger_entry_id: a
        for a in session.scalars(
            select(CreditAdjustmentRecord).where(
                CreditAdjustmentRecord.ledger_entry_id.in_(ids)
            )
        )
    }
    items = []
    for (row,) in rows:
        refund = refunds.get(row.id)
        adjustment = adjustments.get(row.id)
        items.append(
            {
                k: getattr(row, k)
                for k in [
                    "id",
                    "workspace_id",
                    "job_id",
                    "entry_type",
                    "description",
                    "delta_balance_credits",
                    "delta_reserved_credits",
                    "balance_after_credits",
                    "reserved_after_credits",
                ]
            }
            | {
                "created_at": stamp(row.created_at),
                "purchase_id": refund.purchase_id
                if refund
                else origins.get(row.id)
                if (origins.get(row.id) or "").startswith("pay_")
                else None,
                "refund_id": refund.id if refund else None,
                "adjustment_id": adjustment.id if adjustment else None,
                "actor_user_id": adjustment.actor_user_id
                if adjustment
                else refund.confirmed_by_user_id or refund.actor_user_id
                if refund
                else None,
            }
        )
    return {"items": items, "pagination": pagination}


@router.get("/jobs")
def jobs(
    session: SessionDependency,
    _actor: Reader,
    workspace_id: str | None = None,
    search: str = Query("", max_length=320),
    status: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    statement = (
        select(JobRecord, UserRecord.email_normalized)
        .join(WorkspaceRecord, WorkspaceRecord.id == JobRecord.workspace_id)
        .join(UserRecord, UserRecord.id == WorkspaceRecord.created_by_user_id)
    )
    if workspace_id:
        statement = statement.where(JobRecord.workspace_id == workspace_id)
    if status:
        statement = statement.where(JobRecord.status == status)
    if search.strip():
        statement = statement.where(
            or_(
                JobRecord.id.icontains(search.strip(), autoescape=True),
                UserRecord.email_normalized.icontains(search.strip(), autoescape=True),
            )
        )
    rows, pagination = page(
        session,
        statement.order_by(JobRecord.created_at.desc(), JobRecord.id),
        limit,
        offset,
    )
    return {
        "items": [
            {
                k: getattr(j, k)
                for k in [
                    "id",
                    "workspace_id",
                    "type",
                    "status",
                    "display_name",
                    "expected_item_count",
                    "succeeded_item_count",
                    "failed_item_count",
                    "estimated_credits",
                    "actual_credits",
                    "error_code",
                ]
            }
            | {
                "email": email,
                "error_message": _safe_error(j.error_code, j.error_message),
                "created_at": stamp(j.created_at),
                "finished_at": stamp(j.finished_at),
            }
            for j, email in rows
        ],
        "pagination": pagination,
    }


@router.get("/cases")
def cases(
    session: SessionDependency,
    _actor: Reader,
    workspace_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    statement = select(SupportCaseRecord)
    if workspace_id:
        statement = statement.where(SupportCaseRecord.workspace_id == workspace_id)
    rows, pagination = page(
        session,
        statement.order_by(SupportCaseRecord.updated_at.desc(), SupportCaseRecord.id),
        limit,
        offset,
    )
    return {
        "items": [
            {
                k: getattr(r, k)
                for k in [
                    "id",
                    "workspace_id",
                    "job_id",
                    "issue",
                    "resolution",
                    "status",
                    "actor_user_id",
                ]
            }
            | {"created_at": stamp(r.created_at), "updated_at": stamp(r.updated_at)}
            for (r,) in rows
        ],
        "pagination": pagination,
    }


@router.post("/cases", status_code=201)
def create_case(
    body: CaseBody, request: Request, session: SessionDependency, actor: Reader
) -> dict[str, Any]:
    check_permission(request, session, actor, "support:manage")
    if session.get(WorkspaceRecord, body.workspace_id) is None:
        raise ApiError(404, "CUSTOMER_NOT_FOUND", "客户不存在。")
    if body.job_id:
        job = session.get(JobRecord, body.job_id)
        if job is None or job.workspace_id != body.workspace_id:
            raise ApiError(422, "JOB_WORKSPACE_MISMATCH", "关联任务不属于该客户。")
    if len(body.issue.strip()) < 3:
        raise ApiError(422, "ISSUE_REQUIRED", "请填写具体问题。")
    row = SupportCaseRecord(
        id=new_id("case"), **body.model_dump(), actor_user_id=actor.user_id
    )
    session.add(row)
    audit(
        session,
        request,
        actor,
        body.workspace_id,
        "case_created",
        "support_case",
        row.id,
        body.model_dump(),
    )
    session.commit()
    return {"id": row.id}


@router.patch("/cases/{case_id}")
def update_case(
    case_id: str,
    body: CaseUpdate,
    request: Request,
    session: SessionDependency,
    actor: Reader,
) -> dict[str, Any]:
    check_permission(request, session, actor, "support:manage")
    row = session.get(SupportCaseRecord, case_id, with_for_update=True)
    if row is None:
        raise ApiError(404, "CASE_NOT_FOUND", "售后记录不存在。")
    if body.status == "resolved" and len(body.resolution.strip()) < 3:
        raise ApiError(422, "RESOLUTION_REQUIRED", "请填写处理结果后再结案。")
    row.status = body.status
    row.resolution = body.resolution
    row.actor_user_id = actor.user_id
    audit(
        session,
        request,
        actor,
        row.workspace_id,
        "case_updated",
        "support_case",
        row.id,
        body.model_dump(),
    )
    session.commit()
    return {"saved": True}


@router.get("/refunds")
def refunds(
    session: SessionDependency,
    _actor: Reader,
    workspace_id: str | None = None,
    status: Literal["processing", "completed", "rejected"] | None = None,
    search: str = Query("", max_length=320),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    statement = (
        select(ManualRefundRecord, UserRecord.email_normalized)
        .join(
            CreditPurchaseRecord,
            CreditPurchaseRecord.id == ManualRefundRecord.purchase_id,
        )
        .join(UserRecord, UserRecord.id == CreditPurchaseRecord.created_by_user_id)
    )
    if workspace_id:
        statement = statement.where(ManualRefundRecord.workspace_id == workspace_id)
    if status:
        statement = statement.where(ManualRefundRecord.status == status)
    if search.strip():
        statement = statement.where(
            or_(
                ManualRefundRecord.purchase_id.icontains(
                    search.strip(), autoescape=True
                ),
                UserRecord.email_normalized.icontains(search.strip(), autoescape=True),
                ManualRefundRecord.receipt_reference.icontains(
                    search.strip(), autoescape=True
                ),
            )
        )
    rows, pagination = page(
        session,
        statement.order_by(ManualRefundRecord.created_at.desc(), ManualRefundRecord.id),
        limit,
        offset,
    )
    return {
        "items": [refund_item(r) | {"email": email} for r, email in rows],
        "pagination": pagination,
    }


@router.post("/orders/{purchase_id}/refunds", status_code=201)
def prepare_refund(
    purchase_id: str,
    body: RefundBody,
    request: Request,
    session: SessionDependency,
    actor: Reader,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    check_permission(request, session, actor, "refunds:manage")
    key = require_idempotency_key(idempotency_key)
    order = session.get(
        CreditPurchaseRecord, purchase_id, with_for_update=True, populate_existing=True
    )
    if order is None or order.status != "paid":
        raise ApiError(409, "PAID_ORDER_REQUIRED", "仅可处理已确认到账的原充值订单。")
    account = wallet(session, order.workspace_id)
    previous = list(
        session.scalars(
            select(ManualRefundRecord).where(
                ManualRefundRecord.purchase_id == purchase_id
            )
        )
    )
    for row in previous:
        if row.request_key == key:
            if (row.amount_fen, row.credits, row.reason, row.actor_user_id) != (
                body.amount_fen,
                body.credits,
                body.reason,
                actor.user_id,
            ):
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "退款内容已改变。")
            return refund_item(row)
    if any(r.status == "processing" for r in previous):
        raise ApiError(409, "REFUND_ALREADY_PROCESSING", "该订单已有退款处理中。")
    if (
        sum(r.amount_fen for r in previous if r.status == "completed") + body.amount_fen
        > order.amount_fen
    ):
        raise ApiError(
            422, "REFUND_AMOUNT_EXCEEDED", "累计退款金额不能超过原订单实付金额。"
        )
    if len(body.reason.strip()) < 3:
        raise ApiError(422, "REFUND_REASON_REQUIRED", "请填写退款原因。")
    lots = order_lots(session, order)
    available = sum(
        lot.remaining - lot.held
        for lot in lots
        if lot.expires_at is None or aware(lot.expires_at) > aware(utc_now())
    )
    membership = session.scalar(
        select(CreditMembershipRecord).where(
            CreditMembershipRecord.purchase_id == purchase_id
        )
    )
    if membership and (
        not body.cancel_future_membership
        or any(lot.held for lot in lots)
        or body.credits != available
    ):
        raise ApiError(
            422,
            "MEMBERSHIP_REFUND_REVIEW_REQUIRED",
            "会员退款须终止该订单后续发放并扣回全部未使用积分；请先等待相关生成冻结结算。",
        )
    if body.credits > available:
        raise ApiError(
            422,
            "REFUND_CREDITS_EXCEEDED",
            "本单可扣回积分不足，不能扣取其他订单或赠送积分。",
        )
    remaining_fen = order.amount_fen - sum(
        prior.amount_fen for prior in previous if prior.status == "completed"
    )
    if body.amount_fen == remaining_fen and (
        body.credits != available or any(lot.held for lot in lots)
    ):
        raise ApiError(
            422,
            "FULL_REFUND_CREDITS_REQUIRED",
            "退还本单全部剩余金额前须扣回全部未使用积分，并等待原任务冻结结算。",
        )
    needed = body.credits
    allocations = {}
    for lot in lots:
        if lot.expires_at and aware(lot.expires_at) <= aware(utc_now()):
            continue
        value = min(needed, lot.remaining - lot.held)
        if value:
            lot.held += value
            allocations[lot.id] = value
            needed -= value
    assert needed == 0
    account.reserved_credits += body.credits
    account.version += 1
    hold = entry(
        session,
        account,
        "refund_hold",
        0,
        body.credits,
        "人工退款待核验 · " + purchase_id,
    )
    row = ManualRefundRecord(
        id=new_id("ref"),
        purchase_id=purchase_id,
        workspace_id=order.workspace_id,
        request_key=key,
        amount_fen=body.amount_fen,
        credits=body.credits,
        reason=body.reason,
        allocations=allocations,
        actor_user_id=actor.user_id,
        hold_ledger_entry_id=hold.id,
    )
    session.add(row)
    audit(
        session,
        request,
        actor,
        order.workspace_id,
        "refund_prepared",
        "manual_refund",
        row.id,
        body.model_dump(),
    )
    session.commit()
    return refund_item(row)


@router.post("/refunds/{refund_id}/resolve")
def resolve_refund(
    refund_id: str,
    body: RefundResult,
    request: Request,
    session: SessionDependency,
    actor: Reader,
) -> dict[str, Any]:
    check_permission(request, session, actor, "refunds:manage")
    row = session.get(ManualRefundRecord, refund_id)
    if row is None:
        raise ApiError(404, "REFUND_NOT_FOUND", "退款记录不存在。")
    order = session.get(
        CreditPurchaseRecord,
        row.purchase_id,
        with_for_update=True,
        populate_existing=True,
    )
    assert order is not None
    account = wallet(session, order.workspace_id)
    row = session.get(
        ManualRefundRecord, refund_id, with_for_update=True, populate_existing=True
    )
    assert row is not None
    if body.confirm_order_id != order.id:
        raise ApiError(422, "ORDER_CONFIRMATION_REQUIRED", "请输入完整原订单号确认。")
    if row.status != "processing":
        if (
            row.status == body.status
            and row.receipt_reference == body.receipt_reference
            and row.result_note == body.result_note
        ):
            return refund_item(row)
        raise ApiError(409, "REFUND_ALREADY_RESOLVED", "该退款已处理，不可重复变更。")
    if len(body.result_note.strip()) < 3:
        raise ApiError(422, "REFUND_RESULT_REQUIRED", "请填写核验或驳回原因。")
    if body.status == "completed" and (
        not body.receipt_verified or len(body.receipt_reference.strip()) < 6
    ):
        raise ApiError(
            422,
            "REFUND_RECEIPT_REQUIRED",
            "确认退款完成前必须人工核验真实退款凭证并填写交易/凭证编号。",
        )
    for identifier, value in row.allocations.items():
        lot = session.get(CreditGrantRecord, identifier)
        if (
            lot is None
            or lot.workspace_id != row.workspace_id
            or lot.held < value
            or lot.remaining < value
        ):
            raise ApiError(409, "REFUND_HOLD_MISMATCH", "原订单退款冻结记录需要复核。")
        lot.held -= value
        if body.status == "completed":
            lot.remaining -= value
    account.reserved_credits -= row.credits
    account.version += 1
    if body.status == "completed":
        account.balance_credits -= row.credits
        member = session.scalar(
            select(CreditMembershipRecord).where(
                CreditMembershipRecord.purchase_id == row.purchase_id
            )
        )
        if member:
            member.cancelled_at = utc_now()
    result = entry(
        session,
        account,
        "refund" if body.status == "completed" else "refund_release",
        -row.credits if body.status == "completed" else 0,
        -row.credits,
        "人工退款"
        + ("已核验" if body.status == "completed" else "已驳回")
        + " · "
        + row.purchase_id,
    )
    row.status = body.status
    row.receipt_reference = body.receipt_reference
    row.result_note = body.result_note
    row.confirmed_by_user_id = actor.user_id
    row.confirmed_at = utc_now()
    row.result_ledger_entry_id = result.id
    session.flush()
    expire(session, account, aware(utc_now()))
    audit(
        session,
        request,
        actor,
        row.workspace_id,
        "refund_" + body.status,
        "manual_refund",
        row.id,
        body.model_dump(),
    )
    session.commit()
    return refund_item(row)


@router.get("/audit")
def audit_history(
    session: SessionDependency,
    _actor: Reader,
    workspace_id: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    statement = select(AuditEventRecord).where(
        AuditEventRecord.action.startswith("commerce.")
    )
    if workspace_id:
        statement = statement.where(AuditEventRecord.workspace_id == workspace_id)
    rows, pagination = page(
        session, statement.order_by(AuditEventRecord.id.desc()), limit, offset
    )
    return {
        "items": [
            {
                k: getattr(r, k)
                for k in [
                    "id",
                    "workspace_id",
                    "actor_user_id",
                    "action",
                    "resource_id",
                    "details",
                ]
            }
            | {"occurred_at": stamp(r.occurred_at)}
            for (r,) in rows
        ],
        "pagination": pagination,
    }
