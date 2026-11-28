"""Free (synthetic) recovery check after a worker dies mid-generation.

Reproduces the state job_0a8e08cb left on 2026-11-26: six pages dispatched in
parallel, the worker killed while four image calls were in flight, two pages
never started here. One page's image had already arrived in the local stage.
A single broker delivery must then resolve every expired page, recover the
staged image without a new call, never re-send an unresolved call, charge the
customer once for delivered pages only, and count every sent request.
"""

import asyncio
import io
from datetime import timedelta

from PIL import Image
from sqlalchemy import select

from app.aurora_main_image_fast_provider import RECEIPTS_KEY, generation_hash
from app.generation_image_stage import GenerationImageStage
from app.models import (
    CreditLedgerEntryRecord,
    CreditReservationRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    utc_now,
)
from app.storage import ValidatedImage

from ._main_image_workflow_helpers import confirm, detail
from .test_api import dispatch_pending
from .test_aurora_main_image_authored_workflow import AuthoredGateway
from .test_aurora_main_image_native_fast_workflow import create

IN_FLIGHT = (0, 1, 2, 5)  # sent before the worker died
STAGED = 1  # this one's image had arrived in the local stage


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1024, 1024), (40, 160, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _simulate_worker_crash(client, job_id, stage_root):
    """Leave the exact rows a killed worker leaves behind."""

    expired = utc_now() - timedelta(minutes=5)
    with client.app.state.session_factory() as db:
        job = db.get(JobRecord, job_id)
        plan = db.scalar(select(JobPlanRecord).where(JobPlanRecord.job_id == job_id))
        items = {
            item.ordinal: item
            for item in db.scalars(
                select(JobItemRecord).where(JobItemRecord.job_id == job_id)
            )
        }
        receipts = {}
        for ordinal in IN_FLIGHT:
            item = items[ordinal]
            item.status = "running"
            item.attempt_count = 1
            attempt = JobAttemptRecord(
                id=f"attempt_crash_{ordinal}",
                workspace_id=job.workspace_id,
                job_id=job.id,
                job_item_id=item.id,
                attempt_no=1,
                status="running",
                lease_token="dead-worker",
                leased_by="dead-worker",
                lease_expires_at=expired,
                provider="aurora",
                operation=job.type,
                provider_idempotency_key=f"{job.id}:{item.id}:1",
            )
            db.add(attempt)
            receipts[str(ordinal)] = {
                "state": "invoked",
                "job_id": job.id,
                "attempt_id": attempt.id,
                "plan_hash": generation_hash(plan.payload),
                "page_index": ordinal,
                "started_at": expired.isoformat(),
            }
        job.configuration = {**job.configuration, RECEIPTS_KEY: receipts}
        db.commit()
        workspace_id = job.workspace_id
    stage = GenerationImageStage(stage_root, "main-image")
    payload = _png()
    stage.save(
        stage.path(workspace_id, job_id, f"attempt_crash_{STAGED}"),
        ValidatedImage(
            payload=payload,
            filename="g.png",
            content_type="image/png",
            object_key="unused",
            sha256="unused",
            width=1024,
            height=1024,
        ),
        10_000_000,
    )


def test_one_delivery_resolves_every_expired_page_and_bills_once(client, tmp_path):
    gateway = AuthoredGateway()
    job_id, gateway = create(client, tmp_path, auto=False, gateway=gateway)
    dispatch_pending(client)
    assert detail(client, job_id)["status"] == "awaiting_confirmation"
    _simulate_worker_crash(client, job_id, tmp_path / "native-fast-main")
    confirm(client, job_id)
    calls_before = len(gateway.image_calls)

    # Exactly one broker delivery after the crash (no manual queue repair).
    asyncio.run(client.app.state.task_runner.run(job_id))

    current = detail(client, job_id)
    statuses = {
        item["ordinal"]: (item["status"], item["error_code"])
        for item in current["items"]
    }
    # Every expired page is resolved in this one delivery.
    assert current["status"] in {"partial", "completed"}, statuses
    # Staged result recovered without a new call; unstarted pages generated.
    assert statuses[STAGED][0] == "succeeded"
    assert statuses[3][0] == statuses[4][0] == "succeeded"
    # Unresolved in-flight calls are never re-sent.
    for ordinal in set(IN_FLIGHT) - {STAGED}:
        assert statuses[ordinal] == ("failed", "PROVIDER_OUTCOME_UNKNOWN")
    new_calls = [call.page_number - 1 for call in gateway.image_calls[calls_before:]]
    assert sorted(new_calls) == [3, 4]

    # Customer: one reservation, one settlement, delivered pages only (3 × 8).
    with client.app.state.session_factory() as db:
        reservation = db.scalar(
            select(CreditReservationRecord).where(
                CreditReservationRecord.job_id == job_id
            )
        )
        assert reservation.status == "settled" and reservation.settled_credits == 24
        entries = [
            row.entry_type
            for row in db.scalars(
                select(CreditLedgerEntryRecord).where(
                    CreditLedgerEntryRecord.job_id == job_id
                )
            )
        ]
        assert sorted(entries) == ["reserve", "settle"]
    assert current["cost"]["actual_credits"] == 24
    # Requests: 1 planning + 4 sent before the crash + 2 new image calls.
    assert current["api_request_count"] == 7
    # Supplier cost of the four interrupted calls is unconfirmed, not hidden.
    assert current["cost"]["usage_completeness"] != "complete"
