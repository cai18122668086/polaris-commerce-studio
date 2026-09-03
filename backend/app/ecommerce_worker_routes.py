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
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .database import get_session
from .domain import MembershipRole, MembershipStatus, WorkspaceStatus
from .errors import ApiError
from .models import (
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
