"""Plan-stage human authorization for native automatic delivery only."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .plans import DetailPlanError, canonical_hash

AUTO_MODE = "AUTO_FINALIZE_AUTHORIZED"
MANUAL_MODE = "USER_FINAL_REVIEW"
AUTH_VERSION = "domestic-detail-auto-delivery-authorization-v1"
AUTO_AUTHORIZATION_TEXT = (
    "我已审阅当前完整方案，明确授权按此方案生成后自动交付，"
    "接受保留的材料残差，并知悉生成后不再等待人工最终确认。"
)
AUTO_DISCLOSURE = (
    "自动打包不新增模型或图片调用；正常生成与一次自动修复仍按已确认方案计费。"
    "自动交付不表示画面无残差，也不表示已完成整页审核。"
)


def authorization_quote(
    *,
    job_id: str,
    workspace_id: str,
    actor_id: str,
    plan_id: str,
    revision: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    from .generation import runtime_source_hash

    native = payload["native_approval"]
    if native.get("source_job_id") != job_id:
        raise DetailPlanError(
            "Automatic delivery requires the exact original approval owner"
        )
    value = {
        "version": AUTH_VERSION,
        "job_id": job_id,
        "workspace_id": workspace_id,
        "actor_user_id": actor_id,
        "plan_id": plan_id,
        "plan_revision": revision,
        "native_approval_document_sha256": native["document_sha256"],
        "approval_document_sha256": payload["aurora_v4_3"]["approval_document_sha256"],
        "contract_binding_sha256": payload["aurora_v4_3"]["contract_binding"]["sha256"],
        "source_input_sha256": payload["source_input_sha256"],
        "runtime_source_sha256": runtime_source_hash(),
        "delivery_mode": AUTO_MODE,
        "authorization_text": AUTO_AUTHORIZATION_TEXT,
        "completion_disclosure": AUTO_DISCLOSURE,
        "delivery_extra_model_requests": 0,
        "delivery_extra_image_requests": 0,
    }
    return {**value, "sha256": canonical_hash(value)}


def confirm_authorization(
    *,
    mode: str | None,
    text: str | None,
    fingerprint: str | None,
    job_id: str,
    workspace_id: str,
    actor_id: str,
    plan_id: str,
    revision: int,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    if mode in {None, MANUAL_MODE}:
        if text is not None or fingerprint is not None:
            raise DetailPlanError(
                "Automatic consent cannot be attached to ordinary manual delivery"
            )
        return None
    if mode != AUTO_MODE or text != AUTO_AUTHORIZATION_TEXT:
        raise DetailPlanError(
            "Explicit current automatic-delivery authorization is required"
        )
    quote = authorization_quote(
        job_id=job_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        plan_id=plan_id,
        revision=revision,
        payload=payload,
    )
    if fingerprint != quote["sha256"]:
        raise DetailPlanError(
            "The automatic-delivery source, user or approval fingerprint changed"
        )
    return quote


def receipt_authorization(
    payload: Mapping[str, Any],
    *,
    job_id: str | None = None,
    workspace_id: str | None = None,
    plan_id: str | None = None,
    revision: int | None = None,
) -> dict[str, Any] | None:
    receipt = payload.get("aurora_v4_3", {}).get("approval_receipt") or {}
    authorization = receipt.get("automatic_delivery_authorization")
    if authorization is None:
        return None
    if not isinstance(authorization, dict):
        raise DetailPlanError("Original automatic-delivery authorization is invalid")
    try:
        expected = authorization_quote(
            job_id=payload["native_approval"]["source_job_id"],
            workspace_id=authorization["workspace_id"],
            actor_id=receipt["actor_user_id"],
            plan_id=authorization["plan_id"],
            revision=receipt["plan_revision"],
            payload=payload,
        )
        if (
            canonical_hash(authorization) != canonical_hash(expected)
            or job_id is not None
            and authorization["job_id"] != job_id
            or workspace_id is not None
            and authorization["workspace_id"] != workspace_id
            or plan_id is not None
            and authorization["plan_id"] != plan_id
            or revision is not None
            and authorization["plan_revision"] != revision
        ):
            raise DetailPlanError(
                "The original automatic-delivery authority changed; "
                "a copied child needs new explicit approval"
            )
    except (KeyError, TypeError) as exc:
        raise DetailPlanError(
            "The complete original automatic-delivery authority is missing"
        ) from exc
    return authorization


def native_authorization_text(payload: Mapping[str, Any]) -> str:
    text = str(payload["aurora_v4_3"]["approval_receipt"]["approval_text"])
    authorization = receipt_authorization(payload)
    return text + "\n" + authorization["authorization_text"] if authorization else text


def native_delivery_mode(payload: Mapping[str, Any]) -> str:
    return AUTO_MODE if receipt_authorization(payload) is not None else MANUAL_MODE
