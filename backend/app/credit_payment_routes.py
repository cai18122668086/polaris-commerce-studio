"""Epay V1 checkout and atomic credit fulfillment for the workspace pilot."""

import hashlib
import hmac
import re
from datetime import UTC
from typing import Annotated, Any, Literal, cast
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .auth import SessionDependency, WorkspaceDependency, WorkspaceWriteDependency
from .config import Settings
from .credit_memberships import add_months, aware, grant, membership_state, refresh
from .credit_products import LEGACY_PACK_ID, PRODUCTS
from .errors import ApiError
from .models import (
    AuditEventRecord,
    CreditLedgerEntryRecord,
    CreditMembershipRecord,
    CreditPurchaseRecord,
    utc_now,
)
from .services import credit_enforcement_enabled, new_id, require_idempotency_key


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(tags=["credit payments"], dependencies=[Depends(_no_store)])
PACKAGE_ID = "credits_1500"
PACKAGE_NAME = "创作积分包 · 1,500 积分"
AMOUNT_FEN = 9900
PACKAGE_CREDITS = 1500


def epay_sign(parameters: dict[str, str], key: str) -> str:
    """Match audited MPAY EpayV1Signer: raw UTF-8 values and ASCII keys."""
    if not key or any(not isinstance(value, str) for value in parameters.values()):
        raise ValueError("Invalid Epay signing input")
    parts = [
        f"{name}={parameters[name]}"
        for name in sorted(parameters)
        if name not in {"sign", "sign_type"} and parameters[name] != ""
    ]
    return hashlib.md5(("&".join(parts) + key).encode("utf-8")).hexdigest()


def parse_epay_form(payload: bytes) -> dict[str, str]:
    if len(payload) > 8192:
        raise ApiError(413, "PAYMENT_CALLBACK_TOO_LARGE", "支付通知过长。")
    try:
        raw = payload.decode("utf-8", errors="strict")
        if re.search(r"%(?![0-9A-Fa-f]{2})", raw):
            raise ValueError("Invalid percent encoding")
        pairs = parse_qsl(
            raw, keep_blank_values=True, errors="strict", max_num_fields=128
        )
    except (ValueError, UnicodeError) as error:
        raise ApiError(400, "INVALID_PAYMENT_CALLBACK", "支付通知格式错误。") from error
    result: dict[str, str] = {}
    for name, value in pairs:
        if (
            not re.fullmatch(r"[A-Za-z0-9_]{1,128}", name)
            or name in result
            or len(value.encode("utf-8")) > 2048
        ):
            raise ApiError(400, "INVALID_PAYMENT_CALLBACK", "支付通知字段无效。")
        result[name] = value
    return result


def money_fen(value: str) -> int:
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?", value):
        raise ApiError(400, "INVALID_PAYMENT_AMOUNT", "支付金额格式错误。")
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0") or "0")


def _creation_key(settings: Settings) -> str:
    if not settings.credit_payments_enabled:
        raise ApiError(503, "PAYMENTS_UNAVAILABLE", "充值暂未开放。")
    secret = settings.credit_epay_keys.get(settings.credit_epay_active_key_id)
    if (
        secret is None
        or len(secret.get_secret_value()) < 16
        or not re.fullmatch(r"[1-9][0-9]{0,31}", settings.credit_epay_pid)
    ):
        raise ApiError(503, "PAYMENTS_UNAVAILABLE", "充值暂未开放。")
    for address, host in (
        (settings.credit_epay_base_url, "pay.tengliapi.xyz"),
        (settings.credit_epay_notify_url, "www.tengliapi.xyz"),
        (settings.credit_epay_return_url, "www.tengliapi.xyz"),
    ):
        parsed = urlsplit(address)
        if (
            parsed.scheme != "https"
            or parsed.hostname != host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.query
            or parsed.fragment
        ):
            raise ApiError(503, "PAYMENTS_UNAVAILABLE", "充值暂未开放。")
    return secret.get_secret_value()


class CreditPackage(BaseModel):
    id: str
    name: str
    amount_fen: int
    credits: int
    kind: str
    plan_id: str | None
    months: int
    validity_months: int


class CreditPackageCatalog(BaseModel):
    enabled: bool
    packages: list[CreditPackage]


class CreditPurchaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: str


class CreditPurchaseResponse(BaseModel):
    id: str
    package_name: str
    amount_fen: int
    credits: int
    status: str
    checkout_url: str | None
    created_at: str
    paid_at: str | None
    product_kind: str
    membership_starts_at: str | None
    membership_ends_at: str | None
    months: int


def _response(order: CreditPurchaseRecord) -> CreditPurchaseResponse:
    return CreditPurchaseResponse(
        id=order.id,
        package_name=order.package_name,
        amount_fen=order.amount_fen,
        credits=order.credits,
        status=order.status,
        created_at=aware(order.created_at).isoformat(),
        paid_at=aware(order.paid_at).isoformat() if order.paid_at else None,
        product_kind=(order.product_snapshot or {}).get("kind", "pack"),
        membership_starts_at=(order.product_snapshot or {}).get("starts_at"),
        membership_ends_at=(order.product_snapshot or {}).get("ends_at"),
        months=(order.product_snapshot or {}).get("months", 0),
        checkout_url=order.checkout_url if order.status == "pending" else None,
    )


@router.get(
    "/api/v1/workspaces/{workspace_id}/credits/packages",
    response_model=CreditPackageCatalog,
)
def packages(
    request: Request, workspace: WorkspaceDependency, include_memberships: bool = False
) -> CreditPackageCatalog:
    settings: Settings = request.app.state.settings
    enabled = credit_enforcement_enabled(workspace.workspace_id)
    if enabled:
        try:
            _creation_key(settings)
        except ApiError:
            enabled = False
    return CreditPackageCatalog(
        enabled=enabled,
        packages=[
            CreditPackage(**product.snapshot())
            for product in PRODUCTS.values()
            if product.id != LEGACY_PACK_ID
            and (include_memberships or product.kind == "pack")
        ]
        if enabled
        else [],
    )


@router.post(
    "/api/v1/workspaces/{workspace_id}/credits/purchases",
    response_model=CreditPurchaseResponse,
    status_code=201,
)
def create_purchase(
    payload: CreditPurchaseCreate,
    request: Request,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CreditPurchaseResponse:
    if not credit_enforcement_enabled(workspace.workspace_id):
        raise ApiError(403, "CREDIT_PILOT_REQUIRED", "当前账号暂未开放积分充值。")
    settings: Settings = request.app.state.settings
    key = _creation_key(settings)
    product = PRODUCTS.get(payload.package_id)
    if product is None:
        raise ApiError(422, "INVALID_CREDIT_PACKAGE", "充值套餐不存在。")
    request_key = require_idempotency_key(idempotency_header)
    statement = select(CreditPurchaseRecord).where(
        CreditPurchaseRecord.workspace_id == workspace.workspace_id,
        CreditPurchaseRecord.created_by_user_id == workspace.principal.user_id,
        CreditPurchaseRecord.idempotency_key == request_key,
    )
    existing = session.scalar(statement)
    if existing is not None:
        if existing.package_id != payload.package_id:
            raise ApiError(
                409, "IDEMPOTENCY_CONFLICT", "这次购买内容已改变，请重新确认。"
            )
        return _response(existing)
    order_id = new_id("pay")
    parameters = {
        "pid": settings.credit_epay_pid,
        "out_trade_no": order_id,
        "name": product.name,
        "money": f"{product.amount_fen // 100}.{product.amount_fen % 100:02d}",
        "notify_url": settings.credit_epay_notify_url,
        "return_url": settings.credit_epay_return_url + "?purchase=" + order_id,
        "param": order_id,
    }
    parameters["sign"] = epay_sign(parameters, key)
    parameters["sign_type"] = "MD5"
    order = CreditPurchaseRecord(
        id=order_id,
        workspace_id=workspace.workspace_id,
        created_by_user_id=workspace.principal.user_id,
        idempotency_key=request_key,
        package_id=product.id,
        package_name=product.name,
        amount_fen=product.amount_fen,
        credits=product.credits,
        product_snapshot=product.snapshot(),
        merchant_pid=settings.credit_epay_pid,
        signing_key_id=settings.credit_epay_active_key_id,
        checkout_url=settings.credit_epay_base_url.rstrip("/")
        + "/submit.php?"
        + urlencode(parameters),
        status="pending",
    )
    session.add(order)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(statement)
        if existing is None:
            raise
        if existing.package_id != payload.package_id:
            raise ApiError(
                409, "IDEMPOTENCY_CONFLICT", "这次购买内容已改变，请重新确认。"
            ) from None
        return _response(existing)
    return _response(order)


class CreditPurchaseList(BaseModel):
    items: list[CreditPurchaseResponse]
    next_cursor: str | None


class CreditMembershipState(BaseModel):
    refund_pending: bool = False
    plan_id: str | None
    plan_name: str | None
    monthly_credits: int
    starts_at: str | None
    ends_at: str | None
    next_plan_name: str | None
    next_plan_starts_at: str | None
    next_grant_at: str | None
    next_expiry_at: str | None
    expiring_credits: int
    member_credits: int
    pack_credits: int


@router.get(
    "/api/v1/workspaces/{workspace_id}/credits/membership",
    response_model=CreditMembershipState,
)
def membership(workspace: WorkspaceDependency, session: SessionDependency) -> dict:
    if credit_enforcement_enabled(workspace.workspace_id):
        refresh(session, workspace.workspace_id)
        session.commit()
    return membership_state(session, workspace.workspace_id)


@router.get(
    "/api/v1/workspaces/{workspace_id}/credits/purchases",
    response_model=CreditPurchaseList,
)
def purchase_list(
    workspace: WorkspaceDependency,
    session: SessionDependency,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    status: Literal["pending", "paid"] | None = None,
) -> CreditPurchaseList:
    statement = select(CreditPurchaseRecord).where(
        CreditPurchaseRecord.workspace_id == workspace.workspace_id
    )
    if status:
        statement = statement.where(CreditPurchaseRecord.status == status)
    if cursor:
        anchor = session.scalar(
            select(CreditPurchaseRecord).where(
                CreditPurchaseRecord.id == cursor,
                CreditPurchaseRecord.workspace_id == workspace.workspace_id,
            )
        )
        if anchor is None:
            raise ApiError(422, "INVALID_ORDER_CURSOR", "订单分页位置无效。")
        statement = statement.where(
            or_(
                CreditPurchaseRecord.created_at < anchor.created_at,
                and_(
                    CreditPurchaseRecord.created_at == anchor.created_at,
                    CreditPurchaseRecord.id < anchor.id,
                ),
            )
        )
    rows = list(
        session.scalars(
            statement.order_by(
                CreditPurchaseRecord.created_at.desc(), CreditPurchaseRecord.id.desc()
            ).limit(limit + 1)
        )
    )
    return CreditPurchaseList(
        items=[_response(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


@router.get(
    "/api/v1/workspaces/{workspace_id}/credits/purchases/{purchase_id}",
    response_model=CreditPurchaseResponse,
)
def purchase_detail(
    purchase_id: str, workspace: WorkspaceDependency, session: SessionDependency
) -> CreditPurchaseResponse:
    order = session.scalar(
        select(CreditPurchaseRecord).where(
            CreditPurchaseRecord.id == purchase_id,
            CreditPurchaseRecord.workspace_id == workspace.workspace_id,
        )
    )
    if order is None:
        raise ApiError(404, "CREDIT_PURCHASE_NOT_FOUND", "充值订单不存在。")
    return _response(order)


def _query_gateway_order(settings: Settings, merchant_pid: str, order_id: str) -> dict:
    # MPAY api.php accepts the active merchant key in a UTF-8 POST body.
    # Keep credentials out of URLs, logs, exception chains and API responses.
    secret = settings.credit_epay_keys.get(settings.credit_epay_active_key_id)
    if secret is None or len(secret.get_secret_value()) < 16:
        raise ApiError(
            503, "PAYMENT_QUERY_UNAVAILABLE", "暂时无法核对到账，请稍后重试。"
        )
    try:
        with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                "https://pay.tengliapi.xyz/api.php",
                data={
                    "act": "order",
                    "pid": merchant_pid,
                    "key": secret.get_secret_value(),
                    "out_trade_no": order_id,
                },
            )
            response.raise_for_status()
            if len(response.content) > 65536:
                raise ValueError("Oversized gateway response")
            data = response.json()
    except (httpx.HTTPError, ValueError):
        raise ApiError(
            502, "PAYMENT_QUERY_UNAVAILABLE", "支付渠道暂时无法查询，请稍后重试。"
        ) from None
    if (
        not isinstance(data, dict)
        or type(data.get("code")) is not int
        or data["code"] != 1
    ):
        raise ApiError(
            502,
            "PAYMENT_QUERY_UNAVAILABLE",
            "支付渠道尚未返回有效订单，请稍后重试或联系帮助核对。",
        )
    required = ["pid", "out_trade_no", "trade_no", "type", "name", "money", "param"]
    if (
        any(not isinstance(data.get(key), str) for key in required)
        or type(data.get("status")) is not int
        or data["status"] not in {0, 1}
        or data["pid"] != merchant_pid
        or data["out_trade_no"] != order_id
    ):
        raise ApiError(
            502, "PAYMENT_ORDER_MISMATCH", "支付渠道订单信息不一致，请联系帮助核对。"
        )
    return data


@router.post(
    "/api/v1/workspaces/{workspace_id}/credits/purchases/{purchase_id}/reconcile",
    response_model=CreditPurchaseResponse,
)
def reconcile_purchase(
    purchase_id: str,
    request: Request,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
) -> CreditPurchaseResponse:
    order = session.scalar(
        select(CreditPurchaseRecord).where(
            CreditPurchaseRecord.id == purchase_id,
            CreditPurchaseRecord.workspace_id == workspace.workspace_id,
        )
    )
    if order is None:
        raise ApiError(404, "CREDIT_PURCHASE_NOT_FOUND", "充值订单不存在。")
    if order.status == "paid":
        return _response(order)
    merchant_pid, order_id = order.merchant_pid, order.id
    # Never hold wallet/order locks while waiting for a remote response.
    session.rollback()
    data = _query_gateway_order(request.app.state.settings, merchant_pid, order_id)
    if data["status"] == 1:
        parameters = {
            key: data[key]
            for key in [
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
        try:
            _settle_verified_purchase(session, parameters)
        except IntegrityError:
            session.rollback()
            raise ApiError(
                409, "PAYMENT_RECEIPT_CONFLICT", "支付流水需要核对。"
            ) from None
        except Exception:
            session.rollback()
            raise
    # Reload after the remote query: a callback may have committed meanwhile.
    current = session.scalar(
        select(CreditPurchaseRecord)
        .where(
            CreditPurchaseRecord.id == order_id,
        )
        .execution_options(populate_existing=True)
    )
    assert current is not None
    return _response(current)


def settle_paid_purchase(
    session: Session, settings: Settings, parameters: dict[str, str]
) -> None:
    """Acknowledge only after the paid order, wallet and ledger commit together."""
    order = session.scalar(
        select(CreditPurchaseRecord)
        .where(CreditPurchaseRecord.id == parameters.get("out_trade_no", ""))
        .with_for_update()
    )
    if order is None:
        raise ApiError(400, "INVALID_PAYMENT_CALLBACK", "支付通知无法确认。")
    secret = settings.credit_epay_keys.get(order.signing_key_id)
    signature = parameters.get("sign", "")
    if (
        secret is None
        or parameters.get("sign_type") != "MD5"
        or re.fullmatch(r"[0-9a-f]{32}", signature) is None
        or not hmac.compare_digest(
            epay_sign(parameters, secret.get_secret_value()), signature
        )
    ):
        raise ApiError(400, "INVALID_PAYMENT_SIGNATURE", "支付通知签名无效。")
    _settle_verified_purchase(session, parameters)


def _settle_verified_purchase(session: Session, parameters: dict[str, str]) -> None:
    """Only verified callbacks or authenticated server queries may call this."""
    order = session.scalar(
        select(CreditPurchaseRecord)
        .where(CreditPurchaseRecord.id == parameters.get("out_trade_no", ""))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise ApiError(400, "INVALID_PAYMENT_CALLBACK", "支付通知无法确认。")
    trade_no = parameters.get("trade_no", "")
    if (
        parameters.get("pid") != order.merchant_pid
        or parameters.get("trade_status") != "TRADE_SUCCESS"
        or parameters.get("name") != order.package_name
        or parameters.get("param") != order.id
        or money_fen(parameters.get("money", "")) != order.amount_fen
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", trade_no)
        or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", parameters.get("type", ""))
    ):
        raise ApiError(400, "PAYMENT_ORDER_MISMATCH", "支付通知与充值订单不一致。")
    if order.status == "paid":
        if order.gateway_trade_no != trade_no or order.ledger_entry_id is None:
            raise ApiError(409, "PAYMENT_ORDER_MISMATCH", "支付订单状态需要核对。")
        session.rollback()
        return
    claimed = session.execute(
        update(CreditPurchaseRecord)
        .where(
            CreditPurchaseRecord.id == order.id,
            CreditPurchaseRecord.status == "pending",
        )
        .values(status="paid", gateway_trade_no=trade_no, paid_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult[Any], claimed).rowcount != 1:
        session.rollback()
        # Reload and validate the committed winner; never ACK a missing ledger.
        _settle_verified_purchase(session, parameters)
        return
    account = refresh(session, order.workspace_id)
    terms = order.product_snapshot
    if terms and terms.get("kind") == "membership":
        # A paid renewal starts after all already purchased periods. Even two
        # different plans paid concurrently cannot overlap or lose paid time.
        now = aware(utc_now())
        last_end = session.scalar(
            select(CreditMembershipRecord.ends_at)
            .where(
                CreditMembershipRecord.workspace_id == order.workspace_id,
                CreditMembershipRecord.ends_at > now,
                CreditMembershipRecord.cancelled_at.is_(None),
            )
            .order_by(CreditMembershipRecord.ends_at.desc())
            .limit(1)
        )
        begins = max(now, aware(last_end)) if last_end else now
        member = CreditMembershipRecord(
            id=new_id("mem"),
            workspace_id=order.workspace_id,
            purchase_id=order.id,
            plan_id=terms["plan_id"],
            plan_name=order.package_name.split(" · ")[0],
            monthly_credits=order.credits,
            months=terms["months"],
            starts_at=begins,
            ends_at=add_months(begins, terms["months"]),
        )
        session.add(member)
        order.product_snapshot = {
            **terms,
            "starts_at": begins.isoformat(),
            "ends_at": aware(member.ends_at).isoformat(),
        }
        session.flush()
        if begins <= now:
            lot = grant(
                session,
                account,
                f"{order.id}:0",
                order.credits,
                add_months(begins, 1),
                f"{member.plan_name} · 第 1 期积分",
            )
            order.ledger_entry_id = lot.ledger_entry_id
        else:
            entry = CreditLedgerEntryRecord(
                workspace_id=order.workspace_id,
                entry_type="renewal",
                delta_balance_credits=0,
                delta_reserved_credits=0,
                balance_after_credits=account.balance_credits,
                reserved_after_credits=account.reserved_credits,
                description=(
                    f"{order.package_name} · {begins.astimezone(UTC).date()} 生效"
                ),
            )
            session.add(entry)
            session.flush()
            order.ledger_entry_id = entry.id
    else:
        # Orders created before this release retain their original non-expiring
        # pack contract, including pending orders paid after the upgrade.
        expiry = (
            add_months(utc_now(), terms["validity_months"])
            if terms and terms.get("validity_months")
            else None
        )
        lot = grant(
            session,
            account,
            order.id,
            order.credits,
            expiry,
            order.package_name,
            kind="purchase",
        )
        order.ledger_entry_id = lot.ledger_entry_id
    session.add(
        AuditEventRecord(
            workspace_id=order.workspace_id,
            actor_user_id=order.created_by_user_id,
            action="credits.purchase_settled",
            resource_type="credit_purchase",
            resource_id=order.id,
            details={
                "amount_fen": order.amount_fen,
                "credits": order.credits,
                "provider": "epay",
            },
        )
    )
    session.commit()


def _callback_transaction(
    session: Session, settings: Settings, parameters: dict[str, str]
) -> None:
    try:
        settle_paid_purchase(session, settings, parameters)
    except IntegrityError:
        session.rollback()
        raise ApiError(409, "PAYMENT_RECEIPT_CONFLICT", "支付流水需要核对。") from None
    except Exception:
        session.rollback()
        raise


@router.get(
    "/api/v1/payments/epay/notify",
    response_class=PlainTextResponse,
    operation_id="epay_notify_get",
)
@router.post(
    "/api/v1/payments/epay/notify",
    response_class=PlainTextResponse,
    operation_id="epay_notify_post",
)
async def epay_notify(
    request: Request, session: SessionDependency
) -> PlainTextResponse:
    raw_query = request.scope.get("query_string", b"")
    parameters = parse_epay_form(raw_query)
    if request.method == "POST":
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/x-www-form-urlencoded"
        ):
            raise ApiError(415, "INVALID_PAYMENT_CALLBACK", "支付通知必须使用表单。")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) + len(raw_query) > 8192:
                raise ApiError(413, "PAYMENT_CALLBACK_TOO_LARGE", "支付通知过长。")
        posted = parse_epay_form(bytes(body))
        if parameters.keys() & posted.keys() or len(parameters) + len(posted) > 128:
            raise ApiError(400, "INVALID_PAYMENT_CALLBACK", "支付通知包含重复字段。")
        parameters.update(posted)
    await run_in_threadpool(
        _callback_transaction, session, request.app.state.settings, parameters
    )
    return PlainTextResponse("success", headers={"Cache-Control": "no-store"})
