"""Minimal secure protocol for outbound local ecommerce browser workers.

The control plane only sees worker metadata and structured heartbeats.  Tokens
are short-lived, one-time or session-scoped, and bound to a user/workspace/device
triple.  Request models deliberately reject unknown fields so cookies,
localStorage, browser profiles, and CDP endpoints cannot enter this protocol.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .database import get_session
from .domain import (
    CRAWL_TASK_TERMINAL_STATUSES,
    CrawlTaskStatus,
    MembershipRole,
    MembershipStatus,
    WorkspaceStatus,
)
from .ecommerce_crawl_tasks import (
    _acquire_profile_lease,
    _heartbeat_profile_lease,
    _persist_product_snapshot,
    _profile_lease_is_owned,
    _ProfileLeaseLost,
    _release_profile_lease,
    _set_status,
)
from .errors import ApiError
from .models import (
    CrawlAttemptRecord,
    CrawlProfileLeaseRecord,
    CrawlTaskRecord,
    EcommerceAccountRecord,
    EcommerceWorkerEnrollmentRecord,
    EcommerceWorkerRecord,
    UserRecord,
    WorkspaceMemberRecord,
    WorkspaceRecord,
    utc_now,
)

router = APIRouter(prefix="/api/ecommerce/workers", tags=["ecommerce-workers"])
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(get_principal)]

_ALLOWED_PROTOCOL = {"worker.v1"}
_MAX_CAPABILITIES = 32
_RETRYABLE_WORKER_ERRORS = {
    "WORKER_TIMEOUT",
    "WORKER_BROWSER_CRASH",
    "WORKER_UNAVAILABLE",
}
_FORBIDDEN_RESULT_KEYS = {
    "cookie",
    "cookies",
    "localstorage",
    "profile",
    "profilepath",
    "cdp",
    "debuggingport",
    "password",
    "token",
    "captcha",
    "qrcode",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkerEnrollmentRequest(_StrictModel):
    workspace_id: str = Field(min_length=1, max_length=40)
    device_id: str = Field(min_length=1, max_length=128)


class WorkerRegisterRequest(_StrictModel):
    enrollment_token: str = Field(min_length=24, max_length=256)
    device_id: str = Field(min_length=1, max_length=128)
    protocol_version: str = Field(min_length=1, max_length=32)
    agent_version: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=_MAX_CAPABILITIES)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip().casefold()
            if not item or len(item) > 64 or any(ch.isspace() for ch in item):
                raise ValueError("capabilities must be short non-whitespace names")
            if item not in normalized:
                normalized.append(item)
        return normalized


class WorkerHeartbeatRequest(_StrictModel):
    protocol_version: str = Field(min_length=1, max_length=32)
    agent_version: str = Field(min_length=1, max_length=64)
    capabilities: list[str] | None = Field(default=None, max_length=_MAX_CAPABILITIES)
    ready: bool = True

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return WorkerRegisterRequest.validate_capabilities(values)


class WorkerTaskClaimRequest(_StrictModel):
    platforms: list[str] | None = Field(default=None, max_length=8)

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip().casefold() for value in values]
        if any(
            not value or len(value) > 24 or any(ch.isspace() for ch in value)
            for value in normalized
        ):
            raise ValueError("platforms must be short non-whitespace names")
        return list(dict.fromkeys(normalized))


class WorkerTaskLeaseRequest(_StrictModel):
    fencing_token: int = Field(ge=1)


class WorkerTaskCompletionRequest(WorkerTaskLeaseRequest):
    outcome: str = Field(pattern="^(cancelled|failed|timed_out)$")
    error_code: str | None = Field(default=None, max_length=64)
    error_message_safe: str | None = Field(default=None, max_length=500)


class WorkerProductResult(_StrictModel):
    platform: str = Field(min_length=1, max_length=24)
    num_iid: str | int | None = Field(default=None, alias="numIid")
    tmall: bool | None = None
    title: str | None = Field(default=None, max_length=500)
    price: str | None = Field(default=None, max_length=128)
    shop_name: str | None = Field(default=None, alias="shopName", max_length=300)
    sales: str | None = Field(default=None, max_length=128)
    image_urls: list[str] = Field(
        default_factory=list, alias="imageUrls", max_length=100
    )
    desc_image_urls: list[str] = Field(
        default_factory=list, alias="descImageUrls", max_length=200
    )
    sku_image_urls: list[str] = Field(
        default_factory=list, alias="skuImageUrls", max_length=100
    )
    sku_prop_groups: list[dict[str, Any]] = Field(
        default_factory=list, alias="skuPropGroups", max_length=100
    )
    skus: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    props_text: str = Field(default="", alias="propsText", max_length=20_000)
    services: list[str] = Field(default_factory=list, max_length=100)
    platform_data: dict[str, Any] = Field(
        default_factory=dict, alias="platformData", max_length=100
    )
    image_diagnostics: dict[str, int] = Field(
        default_factory=dict, alias="imageDiagnostics", max_length=100
    )
    access_state: str | None = Field(default=None, alias="accessState", max_length=40)
    source_url: str | None = Field(default=None, alias="sourceUrl", max_length=2048)
    warnings: list[str] = Field(default_factory=list, max_length=100)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def reject_sensitive_nested_keys(self) -> WorkerProductResult:
        def walk(value: object) -> None:
            if isinstance(value, Mapping):
                for key, item in value.items():
                    normalized = str(key).replace("_", "").casefold()
                    if normalized in _FORBIDDEN_RESULT_KEYS:
                        raise ValueError("result contains a forbidden sensitive field")
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(self.model_dump(by_alias=True))
        return self


class WorkerResultUploadRequest(WorkerTaskLeaseRequest):
    result: WorkerProductResult


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _ensure_workspace_write(
    session: Session, principal: Principal, workspace_id: str
) -> None:
    workspace = session.get(WorkspaceRecord, workspace_id)
    membership = session.scalar(
        select(WorkspaceMemberRecord).where(
            WorkspaceMemberRecord.workspace_id == workspace_id,
            WorkspaceMemberRecord.user_id == principal.user_id,
            WorkspaceMemberRecord.status == MembershipStatus.ACTIVE.value,
        )
    )
    if (
        workspace is None
        or workspace.status != WorkspaceStatus.ACTIVE.value
        or membership is None
    ):
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "WORKSPACE_NOT_FOUND", "未找到指定工作区。"
        )
    if membership.role == MembershipRole.VIEWER.value:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "WORKSPACE_ACCESS_DENIED",
            "当前成员角色没有本机代理写入权限。",
        )


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    ).isoformat()


def _worker_state(worker: EcommerceWorkerRecord, timeout_seconds: int) -> str:
    if worker.status != "online" or worker.last_seen_at is None:
        return "offline"
    last_seen = _as_utc(worker.last_seen_at)
    return (
        "online"
        if utc_now() - last_seen <= timedelta(seconds=timeout_seconds)
        else "offline"
    )


def _worker_response(
    worker: EcommerceWorkerRecord, timeout_seconds: int
) -> dict[str, Any]:
    state = _worker_state(worker, timeout_seconds)
    return {
        "id": worker.id,
        "workspace_id": worker.workspace_id,
        "device_id": worker.device_id,
        "protocol_version": worker.protocol_version,
        "agent_version": worker.agent_version,
        "capabilities": list(worker.capabilities or []),
        "status": state,
        "error_code": "WORKER_OFFLINE" if state == "offline" else None,
        "last_seen_at": _iso(worker.last_seen_at),
        "registered_at": _iso(worker.created_at),
        "session_token_expires_at": _iso(worker.session_token_expires_at),
    }


def _worker_task_response(
    task: CrawlTaskRecord, lease: CrawlProfileLeaseRecord
) -> dict[str, Any]:
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "platform": task.platform,
        "source_url": task.source_url,
        "canonical_url": task.canonical_url,
        "account_id": task.account_id,
        "profile_id": task.profile_id,
        "request_payload": dict(task.request_payload or {}),
        "status": task.status,
        "stage": task.stage,
        "attempt_count": task.attempt_count,
        "max_attempts": task.max_attempts,
        "lease": {
            "fencing_token": lease.fencing_token,
            "acquired_at": _iso(lease.acquired_at),
            "heartbeat_at": _iso(lease.heartbeat_at),
            "expires_at": _iso(lease.expires_at),
        },
    }


@router.post("/enrollments", status_code=status.HTTP_201_CREATED)
def create_worker_enrollment(
    payload: WorkerEnrollmentRequest,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
) -> dict[str, Any]:
    """Mint a one-time token for a user-authorized local device."""

    _ensure_workspace_write(session, principal, payload.workspace_id)
    now = utc_now()
    raw_token = secrets.token_urlsafe(32)
    record = EcommerceWorkerEnrollmentRecord(
        id=_new_id("wen"),
        user_id=principal.user_id,
        workspace_id=payload.workspace_id,
        device_id=payload.device_id.strip(),
        token_hash=_hash_token(raw_token),
        expires_at=now
        + timedelta(
            seconds=request.app.state.settings.ecommerce_worker_enrollment_ttl_seconds
        ),
    )
    session.add(record)
    session.commit()
    return {
        "success": True,
        "data": {
            "enrollment_token": raw_token,
            "expires_at": _iso(record.expires_at),
            "workspace_id": record.workspace_id,
            "device_id": record.device_id,
        },
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_worker(
    payload: WorkerRegisterRequest,
    request: Request,
    session: SessionDependency,
) -> dict[str, Any]:
    if payload.protocol_version not in _ALLOWED_PROTOCOL:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "WORKER_PROTOCOL_UNSUPPORTED",
            "本机代理协议版本不受支持。",
        )
    now = utc_now()
    enrollment = session.scalar(
        select(EcommerceWorkerEnrollmentRecord)
        .where(
            EcommerceWorkerEnrollmentRecord.token_hash
            == _hash_token(payload.enrollment_token)
        )
        .with_for_update()
    )
    if (
        enrollment is None
        or enrollment.consumed_at is not None
        or _as_utc(enrollment.expires_at) <= now
        or enrollment.device_id != payload.device_id.strip()
    ):
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "WORKER_ENROLLMENT_INVALID",
            "本机代理注册令牌无效或已过期。",
        )

    worker = session.scalar(
        select(EcommerceWorkerRecord).where(
            EcommerceWorkerRecord.user_id == enrollment.user_id,
            EcommerceWorkerRecord.workspace_id == enrollment.workspace_id,
            EcommerceWorkerRecord.device_id == enrollment.device_id,
        )
    )
    if worker is None:
        worker = EcommerceWorkerRecord(
            id=_new_id("wrk"),
            user_id=enrollment.user_id,
            workspace_id=enrollment.workspace_id,
            device_id=enrollment.device_id,
            protocol_version=payload.protocol_version,
            agent_version=payload.agent_version,
            capabilities=payload.capabilities,
        )
        session.add(worker)
    else:
        worker.protocol_version = payload.protocol_version
        worker.agent_version = payload.agent_version
        worker.capabilities = payload.capabilities

    session_token = secrets.token_urlsafe(32)
    worker.session_token_hash = _hash_token(session_token)
    worker.session_token_expires_at = now + timedelta(
        seconds=request.app.state.settings.ecommerce_worker_token_ttl_seconds
    )
    worker.last_seen_at = now
    worker.status = "online"
    enrollment.consumed_at = now
    session.commit()
    return {
        "success": True,
        "data": {
            "worker": _worker_response(
                worker,
                request.app.state.settings.ecommerce_worker_heartbeat_timeout_seconds,
            ),
            "session_token": session_token,
        },
    }


def _authorized_worker(
    session: Session, worker_id: str, authorization: str | None
) -> EcommerceWorkerRecord:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "WORKER_AUTH_REQUIRED",
            "本机代理心跳需要 Bearer 令牌。",
        )
    worker = session.get(EcommerceWorkerRecord, worker_id)
    if worker is None or not hmac.compare_digest(
        worker.session_token_hash or "", _hash_token(token)
    ):
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, "WORKER_AUTH_INVALID", "本机代理令牌无效。"
        )
    user = session.get(UserRecord, worker.user_id)
    membership = session.scalar(
        select(WorkspaceMemberRecord).where(
            WorkspaceMemberRecord.workspace_id == worker.workspace_id,
            WorkspaceMemberRecord.user_id == worker.user_id,
            WorkspaceMemberRecord.status == MembershipStatus.ACTIVE.value,
        )
    )
    workspace = session.get(WorkspaceRecord, worker.workspace_id)
    if (
        user is None
        or user.status != "active"
        or workspace is None
        or workspace.status != WorkspaceStatus.ACTIVE.value
        or membership is None
    ):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "WORKER_SCOPE_REVOKED",
            "本机代理所属用户或工作区权限已撤销。",
        )
    if (
        worker.session_token_expires_at is None
        or _as_utc(worker.session_token_expires_at) <= utc_now()
    ):
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "WORKER_TOKEN_EXPIRED",
            "本机代理令牌已过期，请重新注册。",
        )
    return worker


@router.post("/{worker_id}/heartbeat")
def worker_heartbeat(
    worker_id: str,
    payload: WorkerHeartbeatRequest,
    request: Request,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    worker = _authorized_worker(session, worker_id, authorization)
    if payload.protocol_version not in _ALLOWED_PROTOCOL:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "WORKER_PROTOCOL_UNSUPPORTED",
            "本机代理协议版本不受支持。",
        )
    worker.protocol_version = payload.protocol_version
    worker.agent_version = payload.agent_version
    if payload.capabilities is not None:
        worker.capabilities = payload.capabilities
    worker.last_seen_at = utc_now()
    worker.status = "online" if payload.ready else "offline"
    session.commit()
    return {
        "success": True,
        "data": _worker_response(
            worker,
            request.app.state.settings.ecommerce_worker_heartbeat_timeout_seconds,
        ),
    }


@router.get("")
def list_workers(
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    workspace_id: str = Query(min_length=1, max_length=40),
) -> dict[str, Any]:
    _ensure_workspace_write(session, principal, workspace_id)
    workers = session.scalars(
        select(EcommerceWorkerRecord)
        .where(
            EcommerceWorkerRecord.user_id == principal.user_id,
            EcommerceWorkerRecord.workspace_id == workspace_id,
        )
        .order_by(EcommerceWorkerRecord.created_at, EcommerceWorkerRecord.id)
    ).all()
    timeout = request.app.state.settings.ecommerce_worker_heartbeat_timeout_seconds
    return {
        "success": True,
        "data": [_worker_response(worker, timeout) for worker in workers],
    }


def _require_worker_online(request: Request, worker: EcommerceWorkerRecord) -> None:
    timeout = request.app.state.settings.ecommerce_worker_heartbeat_timeout_seconds
    if _worker_state(worker, timeout) != "online":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "WORKER_OFFLINE",
            "本机代理已离线，不能领取或续期任务。",
        )


def _lease_for_worker_task(
    session: Session,
    worker: EcommerceWorkerRecord,
    task_id: str,
    fencing_token: int,
) -> CrawlProfileLeaseRecord:
    lease = session.scalar(
        select(CrawlProfileLeaseRecord).where(
            CrawlProfileLeaseRecord.task_id == task_id,
            CrawlProfileLeaseRecord.owner_id == worker.id,
            CrawlProfileLeaseRecord.fencing_token == fencing_token,
        )
    )
    if lease is None or not _as_utc(lease.expires_at) > utc_now():
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "TASK_LEASE_LOST",
            "任务租约已失效，请停止本次执行。",
        )
    return lease


@router.post("/{worker_id}/tasks/claim")
def claim_worker_task(
    worker_id: str,
    payload: WorkerTaskClaimRequest,
    request: Request,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    worker = _authorized_worker(session, worker_id, authorization)
    _require_worker_online(request, worker)
    query = (
        select(CrawlTaskRecord)
        .where(
            CrawlTaskRecord.workspace_id == worker.workspace_id,
            CrawlTaskRecord.status == CrawlTaskStatus.QUEUED.value,
        )
        .order_by(
            CrawlTaskRecord.queued_at, CrawlTaskRecord.created_at, CrawlTaskRecord.id
        )
        .limit(20)
    )
    if payload.platforms:
        query = query.where(CrawlTaskRecord.platform.in_(payload.platforms))
    tasks = session.scalars(query).all()
    capabilities = set(worker.capabilities or [])
    allowed_platforms = {
        value.rsplit(".", 1)[-1]
        for value in capabilities
        if value.startswith("browser.")
    }
    for task in tasks:
        if task.platform not in allowed_platforms:
            continue
        if task.cancel_requested_at is not None:
            _set_status(
                session,
                task,
                CrawlTaskStatus.CANCELLED,
                stage="cancelled",
                progress=100,
                message="任务在领取前被取消。",
                event_type="cancelled",
            )
            continue
        if task.account_id:
            account = session.get(EcommerceAccountRecord, task.account_id)
            if (
                account is None
                or account.workspace_id != worker.workspace_id
                or account.status != "active"
            ):
                continue
        profile_id = task.profile_id or f"domestic-{task.platform}"
        fencing_token = _acquire_profile_lease(
            request.app.state.session_factory,
            profile_id=profile_id,
            platform=task.platform,
            task_id=task.id,
            owner_id=worker.id,
            ttl_seconds=request.app.state.settings.ecommerce_worker_task_lease_ttl_seconds,
        )
        if fencing_token is None:
            continue
        current = session.get(CrawlTaskRecord, task.id)
        if (
            current is None
            or current.status != CrawlTaskStatus.QUEUED.value
            or current.cancel_requested_at is not None
        ):
            _release_profile_lease(
                request.app.state.session_factory,
                profile_id=profile_id,
                task_id=task.id,
                owner_id=worker.id,
                fencing_token=fencing_token,
            )
            continue
        _set_status(
            session,
            current,
            CrawlTaskStatus.RUNNING,
            stage="fetching",
            progress=5,
            message="本机代理已领取任务。",
            event_type="worker_claimed",
        )
        current.attempt_count += 1
        attempt = CrawlAttemptRecord(
            id=_new_id("cat"),
            task_id=current.id,
            attempt_no=current.attempt_count,
            status="running",
            worker_id=worker.id,
            started_at=utc_now(),
        )
        session.add(attempt)
        session.commit()
        lease = session.scalar(
            select(CrawlProfileLeaseRecord).where(
                CrawlProfileLeaseRecord.task_id == current.id,
                CrawlProfileLeaseRecord.owner_id == worker.id,
                CrawlProfileLeaseRecord.fencing_token == fencing_token,
            )
        )
        if lease is None:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "TASK_LEASE_LOST",
                "任务租约已失效，请停止本次执行。",
            )
        return {"success": True, "data": _worker_task_response(current, lease)}
    session.commit()
    return {"success": True, "data": None}


@router.post("/{worker_id}/tasks/{task_id}/lease")
def renew_worker_task_lease(
    worker_id: str,
    task_id: str,
    payload: WorkerTaskLeaseRequest,
    request: Request,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    worker = _authorized_worker(session, worker_id, authorization)
    _require_worker_online(request, worker)
    task = session.get(CrawlTaskRecord, task_id)
    if task is None or task.workspace_id != worker.workspace_id:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "CRAWL_TASK_NOT_FOUND", "未找到指定抓取任务。"
        )
    lease = _lease_for_worker_task(session, worker, task_id, payload.fencing_token)
    ok = _heartbeat_profile_lease(
        request.app.state.session_factory,
        profile_id=lease.profile_id,
        task_id=task_id,
        owner_id=worker.id,
        fencing_token=payload.fencing_token,
        ttl_seconds=request.app.state.settings.ecommerce_worker_task_lease_ttl_seconds,
    )
    if not ok:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "TASK_LEASE_LOST",
            "任务租约已失效，请停止本次执行。",
        )
    refreshed = session.scalar(
        select(CrawlProfileLeaseRecord).where(
            CrawlProfileLeaseRecord.task_id == task_id,
            CrawlProfileLeaseRecord.owner_id == worker.id,
            CrawlProfileLeaseRecord.fencing_token == payload.fencing_token,
        )
    )
    assert refreshed is not None
    return {"success": True, "data": _worker_task_response(task, refreshed)}


@router.get("/{worker_id}/tasks/{task_id}/control")
def worker_task_control(
    worker_id: str,
    task_id: str,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    worker = _authorized_worker(session, worker_id, authorization)
    task = session.get(CrawlTaskRecord, task_id)
    if task is None or task.workspace_id != worker.workspace_id:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "CRAWL_TASK_NOT_FOUND", "未找到指定抓取任务。"
        )
    lease = session.scalar(
        select(CrawlProfileLeaseRecord).where(
            CrawlProfileLeaseRecord.task_id == task_id,
            CrawlProfileLeaseRecord.owner_id == worker.id,
        )
    )
    if lease is None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "TASK_LEASE_REQUIRED",
            "本机代理未持有该任务租约。",
        )
    return {
        "success": True,
        "data": {
            "task_id": task.id,
            "status": task.status,
            "cancel_requested": task.cancel_requested_at is not None
            or task.status == CrawlTaskStatus.CANCELLING.value,
        },
    }


@router.post("/{worker_id}/tasks/{task_id}/complete")
def complete_worker_task(
    worker_id: str,
    task_id: str,
    payload: WorkerTaskCompletionRequest,
    request: Request,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    worker = _authorized_worker(session, worker_id, authorization)
    task = session.get(CrawlTaskRecord, task_id)
    if task is None or task.workspace_id != worker.workspace_id:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "CRAWL_TASK_NOT_FOUND", "未找到指定抓取任务。"
        )
    lease = _lease_for_worker_task(session, worker, task_id, payload.fencing_token)
    if task.status in {item.value for item in CRAWL_TASK_TERMINAL_STATUSES}:
        raise ApiError(
            status.HTTP_409_CONFLICT, "TASK_ALREADY_TERMINAL", "任务已经结束。"
        )
    attempt = session.scalar(
        select(CrawlAttemptRecord).where(
            CrawlAttemptRecord.task_id == task_id,
            CrawlAttemptRecord.attempt_no == task.attempt_count,
        )
    )
    now = utc_now()
    if attempt is not None:
        attempt.finished_at = now
        attempt.status = "cancelled" if payload.outcome == "cancelled" else "failed"
        attempt.error_code = payload.error_code or (
            "WORKER_TIMEOUT" if payload.outcome == "timed_out" else None
        )
        attempt.error_message_safe = payload.error_message_safe
    if (
        payload.outcome == "cancelled"
        or task.cancel_requested_at is not None
        or task.status == CrawlTaskStatus.CANCELLING.value
    ):
        task.error_code = "TASK_CANCELLED"
        task.error_message_safe = "任务已取消。"
        _set_status(
            session,
            task,
            CrawlTaskStatus.CANCELLED,
            stage="cancelled",
            progress=100,
            message="任务已取消。",
            event_type="worker_cancelled",
        )
    else:
        task.error_code = (
            payload.error_code
            if payload.error_code in _RETRYABLE_WORKER_ERRORS
            else (
                "WORKER_TIMEOUT" if payload.outcome == "timed_out" else "WORKER_FAILED"
            )
        )
        task.error_message_safe = payload.error_message_safe or "本机代理执行失败。"
        retryable = (
            task.attempt_count < task.max_attempts
            and task.error_code in _RETRYABLE_WORKER_ERRORS
        )
        _set_status(
            session,
            task,
            CrawlTaskStatus.FAILED,
            stage="failed",
            progress=100,
            message=task.error_message_safe,
            event_type="worker_failed",
        )
        if retryable:
            _set_status(
                session,
                task,
                CrawlTaskStatus.RETRY_SCHEDULED,
                stage="retry_scheduled",
                progress=0,
                message="本机代理执行失败，任务已安排重试。",
                event_type="retry_scheduled",
            )
            _set_status(
                session,
                task,
                CrawlTaskStatus.QUEUED,
                stage="queued",
                progress=0,
                message="任务已重新进入队列。",
            )
        else:
            task.progress = 100
    session.commit()
    _release_profile_lease(
        request.app.state.session_factory,
        profile_id=lease.profile_id,
        task_id=task_id,
        owner_id=worker.id,
        fencing_token=payload.fencing_token,
    )
    return {"success": True, "data": {"task_id": task.id, "status": task.status}}


@router.post("/{worker_id}/tasks/{task_id}/result")
async def upload_worker_task_result(
    worker_id: str,
    task_id: str,
    payload: WorkerResultUploadRequest,
    request: Request,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Persist one structured product result while the worker lease is held."""

    worker = _authorized_worker(session, worker_id, authorization)
    task = session.get(CrawlTaskRecord, task_id)
    if task is None or task.workspace_id != worker.workspace_id:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "CRAWL_TASK_NOT_FOUND",
            "未找到指定抓取任务。",
        )
    lease = _lease_for_worker_task(session, worker, task_id, payload.fencing_token)
    if task.status != CrawlTaskStatus.RUNNING.value:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "TASK_NOT_RUNNING",
            "当前任务不在执行状态，不能提交结果。",
        )
    result_data = payload.result.model_dump(by_alias=True, exclude_none=True)
    if str(result_data.get("platform") or "").casefold() != task.platform.casefold():
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "RESULT_PLATFORM_MISMATCH",
            "商品结果平台与任务不一致。",
        )
    if result_data.get("accessState") in {
        "login_required",
        "risk_controlled",
        "captcha_required",
    }:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "RESULT_NOT_PRODUCT",
            "本机代理回传的是登录、风控或验证码状态，不是商品结果。",
        )
    if not result_data.get("title") and not result_data.get("numIid"):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "RESULT_INCOMPLETE",
            "商品结果至少需要标题或商品编号。",
        )

    def lease_guard() -> bool:
        return _profile_lease_is_owned(
            request.app.state.session_factory,
            profile_id=lease.profile_id,
            task_id=task_id,
            owner_id=worker.id,
            fencing_token=payload.fencing_token,
        )
    try:
        snapshot_id, enriched = await _persist_product_snapshot(
            request.app,
            task_id,
            result_data,
            lease_guard=lease_guard,
        )
    except _ProfileLeaseLost as exc:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "TASK_LEASE_LOST",
            "任务租约已失效，请停止本次执行。",
        ) from exc
    except Exception as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "RESULT_PERSIST_FAILED",
            "商品结果暂时无法保存，请稍后重试。",
        ) from exc

    with request.app.state.session_factory() as commit_session:
        stored_task = commit_session.get(CrawlTaskRecord, task_id)
        if stored_task is None:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                "CRAWL_TASK_NOT_FOUND",
                "未找到指定抓取任务。",
            )
        if not lease_guard():
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "TASK_LEASE_LOST",
                "任务租约已失效，请停止本次执行。",
            )
        stored_task.result_payload = enriched
        stored_task.result_snapshot_id = snapshot_id
        stored_task.error_code = None
        stored_task.error_message_safe = None
        _set_status(
            commit_session,
            stored_task,
            CrawlTaskStatus.SUCCEEDED,
            stage="completed",
            progress=100,
            message="商品抓取完成。",
            event_type="worker_completed",
        )
        commit_session.commit()
    _release_profile_lease(
        request.app.state.session_factory,
        profile_id=lease.profile_id,
        task_id=task_id,
        owner_id=worker.id,
        fencing_token=payload.fencing_token,
    )
    return {
        "success": True,
        "data": {
            "task_id": task_id,
            "status": CrawlTaskStatus.SUCCEEDED.value,
            "snapshot_id": snapshot_id,
        },
    }
