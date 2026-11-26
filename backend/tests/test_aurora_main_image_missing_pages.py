"""Redo only missing main-image pages after explicit confirmation (mock upstream)."""

import asyncio
import io
from dataclasses import replace

from PIL import Image
from sqlalchemy import func, select

from app.aurora_main_image_fast_provider import RECEIPTS_KEY
from app.generation_image_stage import GenerationImageStage
from app.models import (
    CreditLedgerEntryRecord,
    CreditReservationRecord,
    JobRecord,
    UsageEventRecord,
)
from app.provider import ProviderOutcome
from app.provider_quota_ledger import usage_request_count
from app.storage import ValidatedImage

from ._main_image_workflow_helpers import BASE, detail
from .test_api import dispatch_pending, idem
from .test_aurora_main_image_authored_workflow import AuthoredGateway
from .test_aurora_main_image_native_fast_workflow import create

LOST = {0, 1, 2, 5}


class LossyGateway(AuthoredGateway):
    """First round: the upstream never returns these pages' images."""

    def __init__(self, lost):
        super().__init__()
        self.lost = set(lost)

    async def edit(self, request):
        result = await super().edit(request)
        if request.page_number - 1 in self.lost:
            self.lost.discard(request.page_number - 1)
            return replace(
                result,
                outcome=ProviderOutcome.OUTCOME_UNKNOWN,
                artifact=None,
                error_code="PROVIDER_OUTCOME_UNKNOWN",
            )
        return result


def _first_round(client, tmp_path):
    job_id, gateway = create(client, tmp_path, gateway=LossyGateway(LOST))
    # The reconciliation endpoint and the worker share one Aurora work root
    # in deployment (settings.aurora_work_root); align the test fixture.
    client.app.state.settings.aurora_work_root = tmp_path / "native-fast-main"
    dispatch_pending(client)
    current = detail(client, job_id)
    assert current["status"] == "partial"
    return job_id, gateway


def _missing(client, job_id):
    response = client.get(BASE + f"/jobs/{job_id}/main-image/missing-pages")
    assert response.status_code == 200, response.text
    return response.json()


def _redo(client, job_id, pages, key=None):
    return client.post(
        BASE + f"/jobs/{job_id}/retry",
        headers={"Idempotency-Key": key} if key else idem(),
        json={"scope": "failed", "confirm_missing_pages": pages},
    )


def _credits(client, job_ids):
    with client.app.state.session_factory() as db:
        reservations = {
            row.job_id: (row.status, row.settled_credits)
            for row in db.scalars(
                select(CreditReservationRecord).where(
                    CreditReservationRecord.job_id.in_(job_ids)
                )
            )
        }
        ledger = {
            job: sorted(
                row.entry_type
                for row in db.scalars(
                    select(CreditLedgerEntryRecord).where(
                        CreditLedgerEntryRecord.job_id == job
                    )
                )
            )
            for job in job_ids
        }
        image_events = [
            row
            for row in db.scalars(
                select(UsageEventRecord).where(UsageEventRecord.job_id.in_(job_ids))
            )
        ]
        supplier_requests = sum(usage_request_count(row) for row in image_events)
    return reservations, ledger, supplier_requests


def _deliverables(client, job_id):
    return {
        asset["ordinal"]
        for asset in detail(client, job_id)["assets"]
        if asset["direction"] == "output" and asset["is_deliverable"]
    }


def test_lost_pages_are_redone_after_confirmation_and_each_page_billed_once(
    client, tmp_path
):
    job_id, gateway = _first_round(client, tmp_path)
    state = _missing(client, job_id)
    assert [page["page_index"] for page in state["missing_pages"]] == sorted(LOST)
    assert state["delivered_pages"] == [3, 4]
    assert state["credits_per_page"] == 8 and state["max_credits"] == 32
    assert "只对成功交付的页扣费" in state["charge_rule"]

    # Without explicit confirmation an unknown result is never re-sent.
    blocked = client.post(
        BASE + f"/jobs/{job_id}/retry", headers=idem(), json={"scope": "failed"}
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "PROVIDER_OUTCOME_UNKNOWN"

    calls_before = len(gateway.image_calls)
    response = _redo(client, job_id, sorted(LOST))
    assert response.status_code == 201, response.text
    redo_id = response.json()["id"]
    dispatch_pending(client)
    redo = detail(client, redo_id)
    assert redo["status"] == "completed"
    assert _deliverables(client, redo_id) == set(range(6))
    # Only the missing pages were generated again; delivered pages were not.
    new_pages = sorted(c.page_number - 1 for c in gateway.image_calls[calls_before:])
    assert new_pages == sorted(LOST)

    reservations, ledger, supplier_requests = _credits(client, [job_id, redo_id])
    # Customer: 2 pages on the original + 4 on the redo = 6 pages × 8, once.
    assert reservations[job_id] == ("settled", 16)
    assert reservations[redo_id] == ("settled", 32)
    assert ledger[job_id] == ledger[redo_id] == ["reserve", "settle"]
    # Supplier: 6 first-round image calls + 4 redo calls (+ 1 planning call,
    # counted separately on the plan) — independent of customer credits.
    assert supplier_requests == 10


def test_late_receipt_after_redo_neither_delivers_nor_bills_again(client, tmp_path):
    job_id, _ = _first_round(client, tmp_path)
    redo_id = _redo(client, job_id, sorted(LOST)).json()["id"]
    dispatch_pending(client)
    before = _credits(client, [job_id, redo_id])
    delivered_before = (_deliverables(client, job_id), _deliverables(client, redo_id))

    # The original call for page 1 reports back after the redo finished.
    with client.app.state.session_factory() as db:
        job = db.get(JobRecord, job_id)
        receipts = dict(job.configuration[RECEIPTS_KEY])
        receipts["0"] = {
            **receipts["0"],
            "state": "returned",
            "object_key": "late/object.png",
            "sha256": "0" * 64,
        }
        job.configuration = {**job.configuration, RECEIPTS_KEY: receipts}
        db.commit()
    for target in (job_id, redo_id):
        asyncio.run(client.app.state.task_runner.run(target))

    assert (_deliverables(client, job_id), _deliverables(client, redo_id)) == (
        delivered_before
    )
    assert _credits(client, [job_id, redo_id]) == before


def test_result_that_arrived_before_redo_is_recovered_without_a_new_call(
    client, tmp_path
):
    job_id, gateway = _first_round(client, tmp_path)
    with client.app.state.session_factory() as db:
        job = db.get(JobRecord, job_id)
        receipt = job.configuration[RECEIPTS_KEY]["1"]
        workspace_id = job.workspace_id
    buffer = io.BytesIO()
    Image.new("RGB", (1024, 1024), (20, 140, 80)).save(buffer, format="PNG")
    stage = GenerationImageStage(tmp_path / "native-fast-main", "main-image")
    stage.save(
        stage.path(workspace_id, receipt["job_id"], receipt["attempt_id"]),
        ValidatedImage(
            payload=buffer.getvalue(),
            filename="g.png",
            content_type="image/png",
            width=1024,
            height=1024,
            object_key="unused",
            sha256="unused",
        ),
        10_000_000,
    )
    pages = {p["page_index"]: p for p in _missing(client, job_id)["missing_pages"]}
    assert pages[1]["recover_from_local_result"] is True

    calls_before = len(gateway.image_calls)
    redo_id = _redo(client, job_id, sorted(LOST)).json()["id"]
    dispatch_pending(client)
    assert detail(client, redo_id)["status"] == "completed"
    new_pages = sorted(c.page_number - 1 for c in gateway.image_calls[calls_before:])
    assert new_pages == [0, 2, 5]
    reservations, _, _ = _credits(client, [job_id, redo_id])
    assert reservations[redo_id] == ("settled", 32)


def test_double_click_concurrent_and_stale_confirmations_create_one_redo(
    client, tmp_path
):
    job_id, gateway = _first_round(client, tmp_path)
    key = "redo-key-1"
    first = _redo(client, job_id, sorted(LOST), key=key)
    assert first.status_code == 201
    # Same click replayed: the same redo job, nothing new.
    replay = _redo(client, job_id, sorted(LOST), key=key)
    assert replay.status_code in {200, 201}
    assert replay.json()["id"] == first.json()["id"]
    # A second click (new key) or a second tab: rejected while a redo exists.
    second = _redo(client, job_id, sorted(LOST))
    assert second.status_code == 409
    assert second.json()["error"]["code"] in {
        "MISSING_PAGES_REDO_EXISTS",
        "JOB_NOT_RETRYABLE",
    }
    with client.app.state.session_factory() as db:
        children = db.scalar(
            select(func.count())
            .select_from(JobRecord)
            .where(JobRecord.retry_of_job_id == job_id)
        )
    assert children == 1
    dispatch_pending(client)
    assert detail(client, first.json()["id"])["status"] == "completed"
    reservations, _, _ = _credits(client, [job_id, first.json()["id"]])
    assert sum(credits for _, credits in reservations.values()) == 48


def test_stale_confirmation_is_rejected(client, tmp_path):
    job_id, _ = _first_round(client, tmp_path)
    stale = _redo(client, job_id, [0, 1])
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "MISSING_PAGES_CHANGED"
    with client.app.state.session_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.retry_of_job_id == job_id)
            )
            == 0
        )
