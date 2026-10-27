"""Epay V1 checkout and atomic credit fulfillment for the workspace pilot."""

import hashlib
import hmac
import re
from typing import Annotated, Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .auth import SessionDependency, WorkspaceDependency, WorkspaceWriteDependency
from .config import Settings
from .errors import ApiError
from .models import (
    AuditEventRecord,
    CreditLedgerEntryRecord,
    CreditPurchaseRecord,
    WorkspaceCreditAccountRecord,
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


def _response(order: CreditPurchaseRecord) -> CreditPurchaseResponse:
    return CreditPurchaseResponse(
        id=order.id,
        package_name=order.package_name,
        amount_fen=order.amount_fen,
        credits=order.credits,
        status=order.status,
        checkout_url=order.checkout_url if order.status == "pending" else None,
    )


@router.get(
    "/api/v1/workspaces/{workspace_id}/credits/packages",
    response_model=CreditPackageCatalog,
)
def packages(request: Request, workspace: WorkspaceDependency) -> CreditPackageCatalog:
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
            CreditPackage(
                id=PACKAGE_ID,
                name=PACKAGE_NAME,
                amount_fen=AMOUNT_FEN,
                credits=PACKAGE_CREDITS,
            )
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
    if payload.package_id != PACKAGE_ID:
        raise ApiError(422, "INVALID_CREDIT_PACKAGE", "充值套餐不存在。")
    request_key = require_idempotency_key(idempotency_header)
    statement = select(CreditPurchaseRecord).where(
        CreditPurchaseRecord.workspace_id == workspace.workspace_id,
        CreditPurchaseRecord.created_by_user_id == workspace.principal.user_id,
        CreditPurchaseRecord.idempotency_key == request_key,
    )
    existing = session.scalar(statement)
    if existing is not None:
        return _response(existing)
    order_id = new_id("pay")
    parameters = {
        "pid": settings.credit_epay_pid,
        "out_trade_no": order_id,
        "name": PACKAGE_NAME,
        "money": "99.00",
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
        package_id=PACKAGE_ID,
        package_name=PACKAGE_NAME,
        amount_fen=AMOUNT_FEN,
        credits=PACKAGE_CREDITS,
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
        return _response(existing)
    return _response(order)


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
        settle_paid_purchase(session, settings, parameters)
        return
    account = session.get(
        WorkspaceCreditAccountRecord, order.workspace_id, with_for_update=True
    )
    if account is None:
        raise ApiError(409, "CREDIT_ACCOUNT_NOT_CONFIGURED", "积分账户尚未配置。")
    session.execute(
        update(WorkspaceCreditAccountRecord)
        .where(WorkspaceCreditAccountRecord.workspace_id == order.workspace_id)
        .values(
            balance_credits=WorkspaceCreditAccountRecord.balance_credits
            + order.credits,
            version=WorkspaceCreditAccountRecord.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    session.refresh(account)
    entry = CreditLedgerEntryRecord(
        workspace_id=order.workspace_id,
        entry_type="purchase",
        delta_balance_credits=order.credits,
        delta_reserved_credits=0,
        balance_after_credits=account.balance_credits,
        reserved_after_credits=account.reserved_credits,
    )
    session.add(entry)
    session.flush()
    order.ledger_entry_id = entry.id
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
