"""Main image: fewer hard stops, so more orders deliver all six pages.

Mock upstream only. A page the supplier explicitly rejected is retried inside
the same order; an unconfirmed result is never re-sent automatically; a
near-square result is fitted instead of rejected; a failed or unusable plan
is re-planned once; repairable plan defects are repaired.
"""

import hashlib
import io
from copy import deepcopy
from dataclasses import replace

from PIL import Image
from sqlalchemy import select

from app import aurora_main_image_authored as authored
from app.aurora_main_image_planner import PAGE_ROLES
from app.models import CreditLedgerEntryRecord, CreditReservationRecord, JobPlanRecord
from app.provider import ProviderOutcome

from ._main_image_workflow_helpers import BASE, assert_delivery, detail
from .test_api import dispatch_pending
from .test_aurora_main_image_authored_workflow import AuthoredGateway
from .test_aurora_main_image_missing_pages import LOST, LossyGateway, _credits
from .test_aurora_main_image_native_fast_workflow import create


class RejectingGateway(AuthoredGateway):
    """The supplier explicitly rejects some pages a number of times."""

    def __init__(self, rejections):
        super().__init__()
        self.rejections = dict(rejections)  # page_number -> times to reject
        self.keys = []

    async def edit(self, request):
        self.keys.append((request.page_number, request.idempotency_key))
        result = await super().edit(request)
        if self.rejections.get(request.page_number, 0) > 0:
            self.rejections[request.page_number] -= 1
            return replace(
                result,
                outcome=ProviderOutcome.FAILED,
                artifact=None,
                error_code="IMAGE_CONTENT_REJECTED",
                retryable=False,
            )
        return result


def _ledger(client, job_id):
    with client.app.state.session_factory() as db:
        reservation = db.scalar(
            select(CreditReservationRecord).where(
                CreditReservationRecord.job_id == job_id
            )
        )
        entries = sorted(
            row.entry_type
            for row in db.scalars(
                select(CreditLedgerEntryRecord).where(
                    CreditLedgerEntryRecord.job_id == job_id
                )
            )
        )
    return reservation.status, reservation.settled_credits, entries


def test_rejected_page_is_retried_in_the_same_order_and_billed_once(client, tmp_path):
    gateway = RejectingGateway({3: 1})
    job_id, gateway = create(client, tmp_path, gateway=gateway)
    dispatch_pending(client)
    assert_delivery(client, job_id)
    # Six pages plus one retry of page 3; the retry used a fresh key so the
    # rejected answer is not replayed.
    assert len(gateway.image_calls) == 7
    page3 = [key for page, key in gateway.keys if page == 3]
    assert len(page3) == 2 and page3[0] != page3[1]
    assert page3[1].endswith(":retry-1")
    assert _ledger(client, job_id) == ("settled", 48, ["reserve", "settle"])
    _, _, supplier_requests = _credits(client, [job_id])
    assert supplier_requests == 7


def test_page_rejected_every_time_stops_after_three_tries(client, tmp_path):
    job_id, gateway = create(client, tmp_path, gateway=RejectingGateway({2: 9}))
    dispatch_pending(client)
    current = detail(client, job_id)
    assert current["status"] == "partial"
    assert [p for p, _ in gateway.keys].count(2) == 3
    assert _ledger(client, job_id) == ("settled", 40, ["reserve", "settle"])


def test_unconfirmed_results_are_never_resent_automatically(client, tmp_path):
    job_id, gateway = create(client, tmp_path, gateway=LossyGateway(LOST))
    dispatch_pending(client)
    assert detail(client, job_id)["status"] == "partial"
    assert len(gateway.image_calls) == 6


class OffSquareGateway(AuthoredGateway):
    async def edit(self, request):
        result = await super().edit(request)
        if request.page_number != 1:
            return result
        buffer = io.BytesIO()
        Image.new("RGB", (1024, 1280), (200, 120, 40)).save(buffer, format="PNG")
        payload = buffer.getvalue()
        return replace(
            result,
            artifact=replace(
                result.artifact,
                payload=payload,
                width=1024,
                height=1280,
                sha256=hashlib.sha256(payload).hexdigest(),
                content_type="image/png",
                filename="p1.png",
            ),
        )


def test_near_square_result_is_fitted_not_rejected(client, tmp_path):
    job_id, gateway = create(client, tmp_path, gateway=OffSquareGateway())
    dispatch_pending(client)
    current = assert_delivery(client, job_id)
    first = next(
        a
        for a in current["assets"]
        if a["direction"] == "output" and a["is_deliverable"] and a["ordinal"] == 0
    )
    access = client.post(
        BASE + f"/assets/{first['asset_id']}/access-url",
        json={"disposition": "attachment", "variant": "original"},
    )
    data = client.get(access.json()["url"]).content
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (1024, 1024)
    assert len(gateway.image_calls) == 6


class ReplanGateway(AuthoredGateway):
    """First planning answer is unusable, the second is fine."""

    async def plan(self, request):
        result = await super().plan(request)
        if len(self.planner_calls) == 1:
            broken = deepcopy(result.payload)
            del broken["plan"]["pages"][4]["scene"]
            result = replace(result, payload=broken)
        return result


def test_unusable_first_plan_is_replanned_once(client, tmp_path):
    job_id, gateway = create(client, tmp_path, gateway=ReplanGateway())
    dispatch_pending(client)
    assert_delivery(client, job_id)
    keys = [call.idempotency_key for call in gateway.planner_calls]
    assert len(keys) == 2 and keys[1] == keys[0] + ":retry-1"
    with client.app.state.session_factory() as db:
        payload = db.scalar(
            select(JobPlanRecord.payload).where(JobPlanRecord.job_id == job_id)
        )
    assert len(payload["usage"]["planner"]) == 2


def test_repairable_plan_defects_are_repaired():
    good = authored.fake_strategy("湿纸巾", 3)
    plan = deepcopy(good)
    pages = plan["plan"]["pages"]
    pages[0], pages[1] = pages[1], pages[0]
    pages[2]["reference_sources"] = [4, 2]
    pages[3]["reference_sources"] = [7]
    pages[5]["page_prompt"] = pages[4]["page_prompt"]
    plan["plan"]["product_identity_lock"]["primary_product_source"] = 9
    fixed = authored.validate_strategy(plan, 3)
    assert [p["page_role"] for p in fixed["plan"]["pages"]] == list(PAGE_ROLES)
    assert fixed["plan"]["product_identity_lock"]["primary_product_source"] == 1
    assert fixed["plan"]["pages"][2]["reference_sources"] == [2]
    assert fixed["plan"]["pages"][3]["reference_sources"] == [1]


class OutageGateway(AuthoredGateway):
    """The first planning call hits a provider outage."""

    async def plan(self, request):
        result = await super().plan(request)
        if len(self.planner_calls) == 1:
            result = replace(
                result,
                payload=None,
                error_code="PROVIDER_TRANSPORT_FAILED",
                error_message="Provider transport failed (URLError).",
            )
        return result


def test_planning_outage_waits_then_replans(client, tmp_path, monkeypatch):
    from app import aurora_main_image_native_fast as native_fast

    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(native_fast.asyncio, "sleep", fake_sleep)
    job_id, gateway = create(client, tmp_path, gateway=OutageGateway())
    dispatch_pending(client)
    assert_delivery(client, job_id)
    assert len(gateway.planner_calls) == 2
    # Only the re-plan waits; the fake supplier's own tiny delays are ignored.
    long_waits = [seconds for seconds in waits if seconds >= 1]
    assert long_waits == [native_fast.AUTHORED_REPLAN_DELAY_SECONDS]
