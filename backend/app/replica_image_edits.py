"""Durable user-selected replica outputs, retaining original images and edit jobs."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import ApiError
from .models import (
    AssetRecord,
    AuditEventRecord,
    JobAssetRecord,
    JobItemRecord,
    JobRecord,
    ReplicaDocumentRecord,
)

SELECTED_ROLE = "replica_selected_result"
_JOBS = "replica_edit_job_ids"
_ORIGINAL = "replica_original_asset_id"
_ORIGINAL_RELATION = "replica_original_relation_id"
_ORIGINAL_VALIDATION = "replica_original_validation"
_CURRENT = "replica_current_edit_job_id"
_SNAPSHOTS = "replica_edit_snapshots"


@dataclass
class Frame:
    job: JobRecord
    item: JobItemRecord
    original: AssetRecord
    original_relation: JobAssetRecord | None
    selected: JobAssetRecord | None
    outputs: list[JobAssetRecord]

    @property
    def current_asset_id(self) -> str:
        return (
            self.selected.asset_id
            if self.selected and self.selected.is_deliverable
            else self.original.id
        )


def frame(
    session: Session,
    workspace_id: str,
    job_id: str,
    item_id: str,
    *,
    lock: bool = False,
) -> Frame:
    from .services import get_workspace_job

    job = get_workspace_job(session, workspace_id, job_id, for_update=lock)
    document_id = job.configuration.get("replica_session_id")
    document = (
        session.get(ReplicaDocumentRecord, document_id)
        if isinstance(document_id, str)
        else None
    )
    if (
        job.type != "reference_remix"
        or document is None
        or document.workspace_id != workspace_id
        or document.kind != "session"
    ):
        raise ApiError(404, "REPLICA_OUTPUT_NOT_FOUND", "未找到这张复刻图片。")
    query = select(JobItemRecord).where(
        JobItemRecord.id == item_id,
        JobItemRecord.job_id == job_id,
        JobItemRecord.workspace_id == workspace_id,
    )
    item = session.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise ApiError(404, "REPLICA_OUTPUT_NOT_FOUND", "未找到这张复刻图片。")
    outputs = list(
        session.scalars(
            select(JobAssetRecord)
            .where(
                JobAssetRecord.workspace_id == workspace_id,
                JobAssetRecord.job_id == job_id,
                JobAssetRecord.job_item_id == item_id,
                JobAssetRecord.direction == "output",
            )
            .order_by(JobAssetRecord.ordinal, JobAssetRecord.id)
        )
    )
    selected = next((row for row in outputs if row.role == SELECTED_ROLE), None)
    original_relation = next(
        (
            row
            for row in outputs
            if row.id
            == (selected.validation.get(_ORIGINAL_RELATION) if selected else None)
        ),
        None,
    )
    if selected is None:
        originals = [row for row in outputs if row.is_deliverable]
        if len(originals) != 1:
            raise ApiError(409, "REPLICA_OUTPUT_NOT_READY", "这张图片尚未生成完成。")
        original_relation = originals[0]
    original_id = (
        selected.validation.get(_ORIGINAL)
        if selected
        else original_relation.asset_id
        if original_relation
        else None
    )
    original = (
        session.get(AssetRecord, original_id) if isinstance(original_id, str) else None
    )
    if original is None or original.workspace_id != workspace_id:
        raise ApiError(409, "REPLICA_ORIGINAL_MISSING", "原版图片暂不可用。")
    return Frame(job, item, original, original_relation, selected, outputs)


def _ensure_selected(session: Session, target: Frame) -> JobAssetRecord:
    if target.selected is None:
        if target.original_relation is None:
            raise ApiError(409, "REPLICA_ORIGINAL_MISSING", "原版记录暂不可用。")
        target.selected = JobAssetRecord(
            workspace_id=target.job.workspace_id,
            job_id=target.job.id,
            job_item_id=target.item.id,
            asset_id=target.original.id,
            direction="output",
            role=SELECTED_ROLE,
            ordinal=0,
            is_deliverable=False,
            validation={
                _ORIGINAL: target.original.id,
                _ORIGINAL_RELATION: target.original_relation.id,
                _ORIGINAL_VALIDATION: dict(target.original_relation.validation),
                _JOBS: [],
                _CURRENT: None,
            },
        )
        session.add(target.selected)
        session.flush()
    return target.selected


def _infer_binding(session: Session, job: JobRecord) -> dict[str, str] | None:
    source_id = (job.configuration.get("input") or {}).get("source_asset_id")
    matches = session.execute(
        select(JobAssetRecord.job_id, JobAssetRecord.job_item_id)
        .join(
            JobRecord,
            JobRecord.id == JobAssetRecord.job_id,
        )
        .where(
            JobAssetRecord.workspace_id == job.workspace_id,
            JobAssetRecord.asset_id == source_id,
            JobAssetRecord.direction == "output",
            JobAssetRecord.job_item_id.is_not(None),
            JobRecord.type == "reference_remix",
        )
    ).all()
    candidates: set[tuple[str, str]] = set()
    for parent_id, item_id in matches:
        if not isinstance(item_id, str):
            continue
        parent = session.get(JobRecord, parent_id)
        if parent and parent.configuration.get("replica_session_id"):
            candidates.add((parent_id, item_id))
    if len(candidates) != 1:
        return None
    parent_id, item_id = candidates.pop()
    return {"job_id": parent_id, "job_item_id": item_id}


def register_edit(
    session: Session, job: JobRecord, *, infer: bool = True
) -> Frame | None:
    inputs = dict(job.configuration.get("input") or {})
    binding = inputs.get("replica_output") or (
        _infer_binding(session, job) if infer else None
    )
    if not binding:
        inputs.pop("replica_output", None)
        job.configuration = {**job.configuration, "input": inputs}
        return None
    target = frame(
        session, job.workspace_id, binding["job_id"], binding["job_item_id"], lock=True
    )
    source_id = inputs.get("source_asset_id")
    selected = _ensure_selected(session, target)
    registered = list(selected.validation.get(_JOBS) or [])
    if job.id not in registered and source_id != target.current_asset_id:
        raise ApiError(
            409, "REPLICA_SOURCE_CHANGED", "复刻图片已有更新，请从当前图片继续修改。"
        )
    if job.id not in registered:
        registered.append(job.id)
    selected.validation = {**selected.validation, _JOBS: registered}
    inputs["replica_output"] = dict(binding)
    job.configuration = {
        **job.configuration,
        "input": inputs,
        "_local_edit_compare_versions": True,
    }
    return target


def _apply(
    session: Session,
    target: Frame,
    asset: AssetRecord,
    delivery: JobAssetRecord | None,
    local_job_id: str | None,
    actor_id: str | None,
    validation_override: dict | None = None,
) -> None:
    from .local_edit_billing import require_image_access

    if (
        asset.workspace_id != target.job.workspace_id
        or asset.lifecycle_status != "ready"
        or asset.deleted_at is not None
    ):
        raise ApiError(409, "REPLICA_EDIT_ASSET_UNAVAILABLE", "这版图片暂不可用。")
    require_image_access(session, asset)
    selected = _ensure_selected(session, target)
    previous = target.current_asset_id
    for row in target.outputs:
        row.is_deliverable = False
    metadata = {
        key: value
        for key, value in selected.validation.items()
        if key.startswith("replica_")
    }
    validation = (
        validation_override
        if validation_override is not None
        else (
            delivery.validation if delivery else metadata.get(_ORIGINAL_VALIDATION, {})
        )
    )
    if local_job_id is not None:
        snapshots = dict(metadata.get(_SNAPSHOTS) or {})
        snapshots[local_job_id] = {"asset_id": asset.id, "validation": dict(validation)}
        metadata[_SNAPSHOTS] = snapshots
    selected.asset_id = asset.id
    selected.is_deliverable = True
    selected.validation = {
        **validation,
        **metadata,
        "sha256": asset.sha256,
        _CURRENT: local_job_id,
        "user_selected": True,
    }
    target.job.state_version += 1
    session.add(
        AuditEventRecord(
            workspace_id=target.job.workspace_id,
            actor_user_id=actor_id,
            action="replica.output_selected",
            resource_type="job_item",
            resource_id=target.item.id,
            request_id=local_job_id or target.job.id,
            details={
                "replica_job_id": target.job.id,
                "original_asset_id": target.original.id,
                "previous_asset_id": previous,
                "asset_id": asset.id,
                "local_edit_job_id": local_job_id,
                "new_generation_requested": False,
                "additional_credits": 0,
            },
        )
    )


def apply_accepted_edit(
    session: Session,
    job: JobRecord,
    delivery: JobAssetRecord,
    actor_id: str | None,
    replica_output: dict[str, str] | None = None,
) -> None:
    if delivery.validation.get("user_accepted") is not True:
        raise ApiError(409, "REPLICA_EDIT_NOT_ACCEPTED", "请先确认采用这次修改。")
    original_binding = (job.configuration.get("input") or {}).get("replica_output")
    binding = replica_output or original_binding
    if not binding:
        binding = _infer_binding(session, job)
        if not binding:
            return
    target = frame(
        session, job.workspace_id, binding["job_id"], binding["job_item_id"], lock=True
    )
    if (
        replica_output
        and replica_output != original_binding
        and (
            target.selected is None
            or job.id not in (target.selected.validation.get(_JOBS) or [])
        )
    ):
        raise ApiError(404, "REPLICA_EDIT_NOT_FOUND", "这次修改不属于当前图片。")
    selected = _ensure_selected(session, target)
    ids = list(selected.validation.get(_JOBS) or [])
    if job.id not in ids:
        ids.append(job.id)
        selected.validation = {**selected.validation, _JOBS: ids}
    asset = session.get(AssetRecord, delivery.asset_id)
    if asset is None:
        raise ApiError(409, "REPLICA_EDIT_ASSET_UNAVAILABLE", "这版图片暂不可用。")
    _apply(session, target, asset, delivery, job.id, actor_id)


def history(session: Session, target: Frame) -> dict:
    from .services import job_history_is_available

    ids = list(target.selected.validation.get(_JOBS) or []) if target.selected else []
    current_job_id = (
        target.selected.validation.get(_CURRENT)
        if target.selected and target.selected.is_deliverable
        else None
    )
    jobs = (
        list(
            session.scalars(
                select(JobRecord)
                .where(
                    JobRecord.workspace_id == target.job.workspace_id,
                    JobRecord.id.in_(ids),
                    JobRecord.type == "local_edit",
                    job_history_is_available(),
                )
                .order_by(JobRecord.created_at.desc(), JobRecord.id.desc())
            )
        )
        if ids
        else []
    )
    related: dict[str, list[JobAssetRecord]] = {job.id: [] for job in jobs}
    if related:
        for relation in session.scalars(
            select(JobAssetRecord).where(
                JobAssetRecord.workspace_id == target.job.workspace_id,
                JobAssetRecord.job_id.in_(list(related)),
            )
        ):
            related[relation.job_id].append(relation)
    records = []
    for job in jobs:
        relations = related[job.id]
        result = next(
            (
                row
                for row in relations
                if row.direction == "output" and row.is_deliverable
            ),
            None,
        )
        if result is None and (job.actual_credits or 0) > 0:
            result = next(
                (row for row in relations if row.role == "locked_candidate"), None
            )
        snapshot = (
            (target.selected.validation.get(_SNAPSHOTS) or {}).get(job.id)
            if target.selected
            else None
        )
        result_asset_id = (
            snapshot.get("asset_id")
            if snapshot
            else result.asset_id
            if result
            else None
        )
        records.append(
            {
                "job_id": job.id,
                "source_asset_id": job.configuration["input"]["source_asset_id"],
                "result_asset_id": result_asset_id,
                "status": job.status,
                "instruction": (job.configuration.get("settings") or {}).get(
                    "instruction", ""
                ),
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "is_current": current_job_id == job.id
                and result_asset_id == target.current_asset_id,
            }
        )
    return {
        "job_id": target.job.id,
        "job_item_id": target.item.id,
        "original_asset_id": target.original.id,
        "current_asset_id": target.current_asset_id,
        "current_local_edit_job_id": current_job_id,
        "records": records,
    }


def select_history(
    session: Session,
    target: Frame,
    local_job_id: str | None,
    expected_asset_id: str,
    actor_id: str,
) -> None:
    if target.current_asset_id != expected_asset_id:
        raise ApiError(
            409,
            "REPLICA_SELECTION_CHANGED",
            "当前图片已有更新，请刷新修改记录后再选择。",
        )
    if local_job_id is None:
        _apply(session, target, target.original, None, None, actor_id)
        return
    selected = target.selected
    if selected is None or local_job_id not in (selected.validation.get(_JOBS) or []):
        raise ApiError(404, "REPLICA_EDIT_NOT_FOUND", "这次修改不属于当前图片。")
    from .services import job_history_is_available

    job = session.scalar(
        select(JobRecord).where(
            JobRecord.id == local_job_id,
            JobRecord.workspace_id == target.job.workspace_id,
            job_history_is_available(),
        )
    )
    if (
        job is None
        or job.workspace_id != target.job.workspace_id
        or job.type != "local_edit"
        or job.status != "completed"
    ):
        raise ApiError(409, "REPLICA_EDIT_NOT_ACCEPTED", "请先打开这次修改并选择采用。")
    snapshot = (selected.validation.get(_SNAPSHOTS) or {}).get(local_job_id)
    if snapshot:
        asset = session.get(AssetRecord, snapshot["asset_id"])
        if asset is None:
            raise ApiError(409, "REPLICA_EDIT_ASSET_UNAVAILABLE", "这版图片暂不可用。")
        _apply(session, target, asset, None, job.id, actor_id, snapshot["validation"])
        return
    delivery = session.scalar(
        select(JobAssetRecord).where(
            JobAssetRecord.workspace_id == job.workspace_id,
            JobAssetRecord.job_id == job.id,
            JobAssetRecord.direction == "output",
            JobAssetRecord.is_deliverable.is_(True),
        )
    )
    asset = session.get(AssetRecord, delivery.asset_id) if delivery else None
    if asset is None:
        raise ApiError(409, "REPLICA_EDIT_ASSET_UNAVAILABLE", "这版图片暂不可用。")
    _apply(session, target, asset, delivery, job.id, actor_id)
