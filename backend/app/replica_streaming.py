"""Bounded parallel image work and durable per-screen publication."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image
from sqlalchemy import func, select

from .models import (
    AssetRecord,
    JobAssetRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobRecord,
    WorkspaceLimitRecord,
)
from .replica_native import ReplicaNativeError, digest
from .storage import ValidatedImage


def serialized_checkpoint[**P, R](
    call: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    @wraps(call)
    async def save(*args: P.args, **kwargs: P.kwargs) -> R:
        run: Any = args[1]
        if not hasattr(run, "_delivery_checkpoint_lock"):
            run._delivery_checkpoint_lock = asyncio.Lock()
        async with run._delivery_checkpoint_lock:
            return await call(*args, **kwargs)

    return save


async def parallel_images(
    provider: Any, indices: list[int], generate: Callable[[int], Awaitable[None]]
) -> None:
    semaphore = asyncio.Semaphore(getattr(provider, "max_concurrency", 1))
    stopped = False

    async def one(index: int) -> None:
        nonlocal stopped
        async with semaphore:
            if stopped:
                return
            try:
                await generate(index)
            except BaseException:
                stopped = True
                raise

    results = await asyncio.gather(*(one(i) for i in indices), return_exceptions=True)
    # Drain dispatched calls before returning a failure, retaining all real
    # outputs and unknown-outcome fences instead of cancelling sibling calls.
    for result in results:
        if isinstance(result, BaseException):
            raise result


async def publish_output(
    provider: Any, run: Any, request: Any, ordinal: int, path: Path
) -> None:
    if (
        getattr(provider, "session_factory", None) is None
        or getattr(provider, "storage", None) is None
    ):
        return
    from .execution import _output_asset_role

    data = path.read_bytes()
    sha = digest(data)
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        content_type = Image.MIME.get(image.format or "PNG", "image/png")
        suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[image.format or "PNG"]
    with provider.session_factory() as session:
        job = session.get(JobRecord, request.job_id)
        if job is None:
            return
        if job.workspace_id != request.workspace_id or job.status in {
            "cancelled",
            "cancelling",
        }:
            raise ReplicaNativeError("任务已停止，生成图片已保留。")
    delivery_key = digest(f"{request.job_id}:{ordinal}:{sha}".encode())
    key = f"{request.workspace_id}/replica/{run.document_id}/{delivery_key}{suffix}"
    stored = await provider.storage.save_validated(
        ValidatedImage(
            payload=data,
            filename=f"replica-{ordinal + 1:03}{suffix}",
            content_type=content_type,
            width=width,
            height=height,
            object_key=key,
            sha256=sha,
        )
    )
    with provider.session_factory() as session:
        job = session.get(JobRecord, request.job_id, with_for_update=True)
        attempt = session.get(JobAttemptRecord, request.attempt_id)
        if (
            job is None
            or job.workspace_id != request.workspace_id
            or job.status
            in {"cancelled", "cancelling", "completed", "failed", "partial"}
            or attempt is None
            or attempt.status != "running"
        ):
            return
        item = session.scalar(
            select(JobItemRecord).where(
                JobItemRecord.job_id == job.id,
                JobItemRecord.ordinal == ordinal,
            )
        )
        if item is None:
            raise ReplicaNativeError("生成图片未绑定当前任务项。")
        existing = session.scalar(
            select(JobAssetRecord).where(
                JobAssetRecord.job_id == job.id,
                JobAssetRecord.job_item_id == item.id,
                JobAssetRecord.direction == "output",
                JobAssetRecord.ordinal == ordinal,
            )
        )
        if existing is not None:
            asset = session.get(AssetRecord, existing.asset_id)
            if asset is None or asset.sha256 != sha:
                raise ReplicaNativeError("已交付图片的字节发生变化。")
            return
        limits = session.get(
            WorkspaceLimitRecord, job.workspace_id, with_for_update=True
        )
        used = session.scalar(
            select(func.coalesce(func.sum(AssetRecord.byte_size), 0)).where(
                AssetRecord.workspace_id == job.workspace_id,
                AssetRecord.lifecycle_status == "ready",
                AssetRecord.deleted_at.is_(None),
            )
        )
        if (
            limits is None
            or int(used or 0) + stored.byte_size > limits.storage_quota_bytes
        ):
            raise ReplicaNativeError("工作区存储空间不足，生成图片已保留。")
        asset_id = "asset_" + uuid4().hex
        session.add(
            AssetRecord(
                id=asset_id,
                workspace_id=job.workspace_id,
                media_kind="image",
                origin_kind="generated",
                lifecycle_status="ready",
                original_filename=stored.filename,
                content_type=content_type,
                byte_size=stored.byte_size,
                width=width,
                height=height,
                sha256=sha,
                storage_provider=stored.storage_provider,
                storage_bucket=stored.storage_bucket,
                object_key=key,
                object_version=stored.object_version,
                etag=stored.etag,
                asset_metadata={"replica_incremental": True},
            )
        )
        session.flush()
        session.add(
            JobAssetRecord(
                workspace_id=job.workspace_id,
                job_id=job.id,
                job_item_id=item.id,
                asset_id=asset_id,
                direction="output",
                role=_output_asset_role(job.type),
                ordinal=ordinal,
                is_deliverable=True,
                validation={"sha256": sha, "review_status": "NOT_REVIEWED"},
            )
        )
        session.commit()
