"""One application-level retry, retaining original uncertain calls and good pixels."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from fastapi import BackgroundTasks, Request
from sqlalchemy import select

from .errors import ApiError
from .models import JobItemRecord, JobRecord, ReplicaDocumentRecord, UserRecord, utc_now
from .replica_exact_contracts import canonical_hash

VERSION = "replica-failure-recovery-v1"
TERMINAL = {"partial", "failed", "cancelled"}
UNKNOWN = {"PROVIDER_OUTCOME_UNKNOWN", "IMAGE_RESULT_DOWNLOAD_UNCONFIRMED"}
TRANSIENT = UNKNOWN | {
    "PROVIDER_TRANSPORT_FAILED",
    "IMAGE_RATE_LIMITED",
    "IMAGE_REQUEST_FAILED",
    "FAST_REPLICA_IMAGE_FAILED",
    "FAST_REPLICA_CANVAS_INVALID",
    "IMAGE_RESPONSE_SIZE_INVALID",
    "REPLICA_CANVAS_MISMATCH",
}
logger = logging.getLogger(__name__)


def request_authority(request: Request, source: JobRecord) -> dict[str, Any] | None:
    authority = getattr(request.state, "replica_retry_authority", None)
    if not isinstance(authority, dict):
        return None
    if (
        authority.get("version") != VERSION
        or authority.get("source_job_id") != source.id
        or authority.get("document_id")
        != source.configuration.get("replica_session_id")
        or authority.get("workspace_id") != source.workspace_id
    ):
        raise ApiError(
            409, "REPLICA_RETRY_SCOPE_INVALID", "重试任务与原复刻记录不一致。"
        )
    return authority


def bind_retry(
    session: Any, source: JobRecord, child: JobRecord, authority: dict[str, Any]
) -> None:
    """Bind session, child, charge and outbox in the original retry transaction."""
    row = session.get(
        ReplicaDocumentRecord, authority["document_id"], with_for_update=True
    )
    if row is None or row.workspace_id != source.workspace_id:
        raise ApiError(
            409, "REPLICA_RETRY_SCOPE_INVALID", "未找到当前工作区的复刻记录。"
        )
    values = dict(row.payload)
    if (source.configuration.get("settings") or {}).get(
        "replica_plan_hash"
    ) != values.get("plan_hash"):
        raise ApiError(
            409, "REPLICA_RETRY_SCOPE_INVALID", "原方案已变化，请刷新复刻记录。"
        )
    jobs = list(values.get("job_ids", []))
    events = list(values.get("retry_events", []))
    root = source.root_job_id or source.id
    if source.id not in jobs:
        raise ApiError(
            409, "REPLICA_RETRY_SUPERSEDED", "原任务已有后续重试，请刷新结果。"
        )
    if authority["kind"] == "automatic" and any(
        e.get("kind") == "automatic" and e.get("root_job_id") == root for e in events
    ):
        raise ApiError(
            409,
            "REPLICA_AUTOMATIC_RETRY_USED",
            "本套图片已自动补试一次，可手动重试未完成图片。",
        )
    grant = {
        **authority,
        "root_job_id": root,
        "plan_hash": values.get("plan_hash"),
        "issued_at": utc_now().isoformat(),
        "image_route": "primary"
        if (source.configuration.get("_replica_retry") or {}).get("image_route")
        == "image-failover"
        else "image-failover",
    }
    child.configuration = {**child.configuration, "_replica_retry": grant}
    jobs[jobs.index(source.id)] = child.id
    row.status = "generating"
    row.payload = {
        **{
            k: v
            for k, v in values.items()
            if k
            not in {
                "execution_progress",
                "error",
                "error_code",
                "recovery_error",
                "recovery_error_code",
            }
        },
        "job_ids": jobs,
        "retry_events": [
            *events,
            {
                "from": source.id,
                "to": child.id,
                "request_id": authority["request_id"],
                "kind": authority["kind"],
                "root_job_id": root,
            },
        ],
        "recovery": {
            "kind": authority["kind"],
            "source_job_id": source.id,
            "job_id": child.id,
        },
    }
    row.updated_at = utc_now()


def allows_unconfirmed_retry(job: JobRecord, prior_job_id: str | None) -> bool:
    grant = job.configuration.get("_replica_retry") or {}
    return bool(
        grant.get("version") == VERSION
        and grant.get("kind") in {"manual", "automatic"}
        and prior_job_id
        and prior_job_id == job.retry_of_job_id == grant.get("source_job_id")
        and grant.get("workspace_id") == job.workspace_id
        and grant.get("document_id") == job.configuration.get("replica_session_id")
        and grant.get("plan_hash")
        == (job.configuration.get("settings") or {}).get("replica_plan_hash")
    )


def derived_retry_snapshot(
    snapshot: dict[str, Any], parent_id: str, grant: dict[str, Any]
) -> dict[str, Any]:
    """Create child lineage; no original snapshot or protocol byte is rewritten."""
    from .replica_native import digest
    from .replica_retry import _document

    ledger = (
        _document(snapshot, "invocations.json")
        if "invocations.json" in snapshot["files"]
        else {}
    )
    uncertain = {
        token for token, value in ledger.items() if value.get("state") == "invoked"
    }
    if not uncertain:
        return snapshot
    derived = deepcopy(snapshot)

    def put(name: str, value: Any) -> None:
        text = json.dumps(value, ensure_ascii=False, indent=2)
        derived["files"][name] = {"text": text, "sha256": digest(text.encode())}

    put("recovery-source-invocations.json", ledger)
    for token in uncertain:
        ledger[token] = {
            **ledger[token],
            "state": "superseded_unknown",
            "recovery_source_job_id": parent_id,
            "recovery_authority": grant,
        }
    put("invocations.json", ledger)
    for state_file in ("direct-session.json", "completion-session.json"):
        if state_file not in snapshot["files"]:
            continue
        state = _document(snapshot, state_file)
        for record in state.get("modules", []):
            old = record.get("request") or {}
            if old.get("token") in uncertain and record.get("status") != "GENERATED":
                record.setdefault("previous_requests", []).append(record.pop("request"))
                record["status"] = "PENDING"
        put(state_file, state)
    derived["recovery_lineage"] = {
        "source_job_id": parent_id,
        "source_snapshot_sha256": canonical_hash(snapshot),
        "authority": grant,
    }
    put("recovery-authority.json", derived["recovery_lineage"])
    return derived


async def retry_once(
    runner: Any, settings: Any, storage: Any, job_id: str
) -> str | None:
    from .auth import (
        _principal_from_user,
        require_workspace,
        require_workspace_processing_write,
    )
    from .replica import ImageRetryRequest, retry_image

    background = BackgroundTasks()
    document_id = None
    try:
        with runner.session_factory() as session:
            source = session.get(JobRecord, job_id)
            if source is None or source.status not in {"partial", "failed"}:
                return None
            document_id = source.configuration.get("replica_session_id")
            row = (
                session.get(ReplicaDocumentRecord, document_id) if document_id else None
            )
            if row is None or row.workspace_id != source.workspace_id:
                return None
            values = dict(row.payload)
            if (
                values.get("auto_start_after_plan") is not True
                or values.get("replica_mode_version") != "replica-modes-v2"
            ):
                return None
            root = source.root_job_id or source.id
            if any(
                e.get("kind") == "automatic" and e.get("root_job_id") == root
                for e in values.get("retry_events", [])
            ):
                return None
            if job_id not in values.get("job_ids", []):
                return None
            items = session.scalars(
                select(JobItemRecord).where(JobItemRecord.job_id == job_id)
            ).all()
            missing = [i for i in items if i.status not in {"succeeded", "reused"}]
            if not missing or any(
                i.status in {"running", "pending", "queued", "retry_wait"}
                for i in missing
            ):
                return None
            if not any(i.error_code in TRANSIENT for i in missing):
                return None
            submission = values.get("_automatic_submission") or {}
            user = session.get(UserRecord, submission.get("actor_user_id"))
            if user is None or user.status != "active":
                return None
            principal = _principal_from_user(
                user, email_verified=submission.get("email_verified") is True
            )
            app = SimpleNamespace(
                state=SimpleNamespace(
                    settings=settings,
                    session_factory=runner.session_factory,
                    task_runner=runner,
                    storage=storage,
                )
            )
            request = Request(
                {
                    "type": "http",
                    "app": app,
                    "method": "POST",
                    "path": (
                        f"/api/v1/workspaces/{row.workspace_id}/replica/"
                        f"sessions/{document_id}/jobs/{job_id}/retry"
                    ),
                    "headers": [],
                    "query_string": b"",
                    "scheme": "https",
                    "server": ("internal", 443),
                }
            )
            workspace = require_workspace_processing_write(
                request,
                session,
                require_workspace(source.workspace_id, principal, session),
            )
            request.state.replica_retry_kind = "automatic"
            result = retry_image(
                document_id,
                job_id,
                ImageRetryRequest(request_id="automatic-retry-" + job_id),
                request,
                background,
                workspace,
                session,
            )
            child_id = next(
                (
                    e["to"]
                    for e in result["payload"]["retry_events"]
                    if e["from"] == job_id
                ),
                None,
            )
        await background()
        return child_id
    except Exception as error:
        logger.warning(
            "Replica automatic retry deferred: job=%s code=%s",
            job_id,
            getattr(error, "code", type(error).__name__),
        )
        if document_id:
            with runner.session_factory() as session:
                row = session.get(
                    ReplicaDocumentRecord, document_id, with_for_update=True
                )
                if row is not None and job_id in row.payload.get("job_ids", []):
                    row.payload = {
                        **row.payload,
                        "recovery_error_code": getattr(
                            error, "code", "REPLICA_RECOVERY_UNAVAILABLE"
                        ),
                        "recovery_error": (
                            "自动补试暂未提交成功，可手动重试未完成的图片。"
                        ),
                    }
                    session.commit()
        return None
