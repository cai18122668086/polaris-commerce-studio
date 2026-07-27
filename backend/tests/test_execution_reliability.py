import asyncio
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.domain import (
    AttemptStatus,
    JobItemStatus,
    JobStatus,
    OutboxStatus,
)
from app.execution import ExecutionCoordinator
from app.models import (
    JobAttemptRecord,
    JobItemRecord,
    JobRecord,
    OutboxEventRecord,
    UsageEventRecord,
    utc_now,
)
from app.outbox import publish_pending_events
from app.provider import FakeProvider, ProviderOutcome, ProviderResult

WORKSPACE_ID = "ws_test"


def _image_payload(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 32), color).save(output, format="PNG")
    return output.getvalue()


def _create_job(client: TestClient) -> str:
    asset_ids: list[str] = []
    for index, media_kind in enumerate(["image", "mask"]):
        response = client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
            headers={"Idempotency-Key": str(uuid4())},
            data={"origin_kind": "upload", "media_kind": media_kind},
            files={
                "file": (
                    f"input-{index}.png",
                    _image_payload((20 + index, 40, 60)),
                    "image/png",
                )
            },
        )
        assert response.status_code == 201
        asset_ids.append(response.json()["id"])
    created = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "type": "local_edit",
            "intent": "submit",
            "input": {
                "source_asset_id": asset_ids[0],
                "selection_mask_asset_id": asset_ids[1],
            },
            "configuration": {
                "instruction": "reliability test",
                "quality": "balanced",
                "output_format": "png",
            },
        },
    )
    assert created.status_code == 202
    return str(created.json()["id"])


def _coordinator(
    client: TestClient,
    provider: FakeProvider,
    worker_id: str,
) -> ExecutionCoordinator:
    return ExecutionCoordinator(
        client.app.state.session_factory,
        provider,
        worker_id=worker_id,
        lease_seconds=2,
        heartbeat_seconds=0.2,
    )


def _counts(client: TestClient, job_id: str) -> tuple[int, int]:
    with client.app.state.session_factory() as session:
        attempts = session.scalar(
            select(func.count())
            .select_from(JobAttemptRecord)
            .where(JobAttemptRecord.job_id == job_id)
        )
        usage = session.scalar(
            select(func.count())
            .select_from(UsageEventRecord)
            .where(UsageEventRecord.job_id == job_id)
        )
    return int(attempts or 0), int(usage or 0)


def test_ten_concurrent_deliveries_execute_provider_once(
    client: TestClient,
) -> None:
    job_id = _create_job(client)
    providers = [FakeProvider(delay_seconds=0.05) for _ in range(10)]
    coordinators = [
        _coordinator(client, provider, f"worker-{index}")
        for index, provider in enumerate(providers)
    ]

    async def deliver() -> list[JobStatus | None]:
        return await asyncio.gather(
            *(coordinator.run(job_id) for coordinator in coordinators)
        )

    asyncio.run(deliver())
    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED.value
    assert sum(provider.call_count for provider in providers) == 1
    assert _counts(client, job_id) == (1, 1)


def test_expired_claim_is_released_to_one_new_worker_without_new_attempt(
    client: TestClient,
) -> None:
    job_id = _create_job(client)
    old_provider = FakeProvider()
    new_provider = FakeProvider()
    old = _coordinator(client, old_provider, "old-worker")
    new = _coordinator(client, new_provider, "new-worker")
    assert old.prepare(job_id) == JobStatus.PROCESSING
    old_lease = old.claim_next_item(job_id)
    assert old_lease is not None

    with client.app.state.session_factory() as session:
        attempt = session.get(JobAttemptRecord, old_lease.attempt_id)
        assert attempt is not None
        attempt.lease_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()

    new_lease = new.claim_next_item(job_id)
    assert new_lease is not None
    assert new_lease.attempt_id == old_lease.attempt_id
    assert new_lease.lease_token != old_lease.lease_token
    assert old.mark_provider_started(old_lease) is False
    assert asyncio.run(new.execute_lease(new_lease)) is True
    assert new.finalize_job(job_id) == JobStatus.COMPLETED
    assert old_provider.call_count == 0
    assert new_provider.call_count == 1
    assert _counts(client, job_id) == (1, 1)


def test_expired_running_attempt_becomes_unknown_and_stale_finish_is_fenced(
    client: TestClient,
) -> None:
    job_id = _create_job(client)
    old = _coordinator(client, FakeProvider(), "old-worker")
    recovery = _coordinator(client, FakeProvider(), "recovery-worker")
    assert old.prepare(job_id) == JobStatus.PROCESSING
    lease = old.claim_next_item(job_id)
    assert lease is not None
    assert old.mark_provider_started(lease) is True

    with client.app.state.session_factory() as session:
        attempt = session.get(JobAttemptRecord, lease.attempt_id)
        assert attempt is not None
        attempt.lease_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()

    assert recovery.claim_next_item(job_id) is None
    assert (
        old.finish_attempt(
            lease,
            ProviderResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_request_id="stale-result",
            ),
        )
        is False
    )
    assert recovery.finalize_job(job_id) == JobStatus.FAILED
    with client.app.state.session_factory() as session:
        attempt = session.get(JobAttemptRecord, lease.attempt_id)
        item = session.get(JobItemRecord, lease.item_id)
        job = session.get(JobRecord, job_id)
        assert attempt is not None and item is not None and job is not None
        assert attempt.status == AttemptStatus.OUTCOME_UNKNOWN.value
        assert item.error_code == "PROVIDER_OUTCOME_UNKNOWN"
        assert job.actual_cost_micros is None
    assert _counts(client, job_id) == (1, 0)


@pytest.mark.parametrize(
    "item_status",
    [
        JobItemStatus.PENDING.value,
        JobItemStatus.QUEUED.value,
        JobItemStatus.RUNNING.value,
    ],
)
def test_nonterminal_item_prevents_job_terminalization(
    client: TestClient,
    item_status: str,
) -> None:
    job_id = _create_job(client)
    coordinator = _coordinator(client, FakeProvider(), "worker")
    assert coordinator.prepare(job_id) == JobStatus.PROCESSING
    with client.app.state.session_factory() as session:
        item = session.scalar(
            select(JobItemRecord).where(JobItemRecord.job_id == job_id)
        )
        assert item is not None
        item.status = item_status
        session.commit()
    assert coordinator.finalize_job(job_id) == JobStatus.PROCESSING


def test_cancel_and_finish_have_serializable_results(client: TestClient) -> None:
    cancelled_job_id = _create_job(client)
    cancelled = _coordinator(client, FakeProvider(), "cancel-first")
    assert cancelled.prepare(cancelled_job_id) == JobStatus.PROCESSING
    cancelled_lease = cancelled.claim_next_item(cancelled_job_id)
    assert cancelled_lease is not None
    assert cancelled.mark_provider_started(cancelled_lease)
    assert cancelled.cancel(cancelled_job_id) == JobStatus.CANCELLED
    assert not cancelled.finish_attempt(
        cancelled_lease,
        ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_request_id="too-late",
        ),
    )

    finished_job_id = _create_job(client)
    finished = _coordinator(client, FakeProvider(), "finish-first")
    assert finished.prepare(finished_job_id) == JobStatus.PROCESSING
    finished_lease = finished.claim_next_item(finished_job_id)
    assert finished_lease is not None
    assert asyncio.run(finished.execute_lease(finished_lease))
    assert finished.finalize_job(finished_job_id) == JobStatus.COMPLETED
    assert finished.cancel(finished_job_id) == JobStatus.COMPLETED


def test_published_outbox_delivery_is_recovered_from_postgres(
    client: TestClient,
) -> None:
    job_id = _create_job(client)
    with client.app.state.session_factory() as session:
        event = session.scalar(
            select(OutboxEventRecord).where(
                OutboxEventRecord.aggregate_id == job_id
            )
        )
        assert event is not None
        event.status = OutboxStatus.PUBLISHED.value
        event.published_at = utc_now() - timedelta(seconds=31)
        session.commit()

    published = publish_pending_events(
        client.app.state.settings,
        client.app.state.session_factory,
        client.app.state.task_runner,
    )
    assert published == 1
    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, job_id)
        event = session.scalar(
            select(OutboxEventRecord).where(
                OutboxEventRecord.aggregate_id == job_id
            )
        )
        assert job is not None and event is not None
        assert job.status == JobStatus.COMPLETED.value
        assert event.status == OutboxStatus.PUBLISHED.value
    assert _counts(client, job_id) == (1, 1)
