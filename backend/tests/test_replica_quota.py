"""Native replica reservations must not poison subsequent workspace submits."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (
    AuditEventRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobRecord,
    UsageEventRecord,
    utc_now,
)
from app.provider_quota_ledger import ProviderQuotaLedgerError, reconcile_and_total
from app.replica_quota import native_replica_budget
from app.routes_v1 import _reserve_real_provider_job_if_enabled


def native_configuration(method="exact"):
    return {
        "replica_session_id": "rep_" + "a" * 32,
        "settings": {
            "reference_skill": (
                "aurora-ecommerce-reference-remix"
                if method == "exact"
                else "all-category-style-benchmark-still"
            ),
            "replication_method": method,
            "replica_plan_hash": "b" * 64,
            "image_count": 5,
        },
    }


@pytest.mark.parametrize(
    "method,budget", [("exact", (13_050_000, 65, 45)), ("style", (10_050_000, 53, 33))]
)
def test_native_submit_reserves_bounded_images_audits_and_contract_retries(
    client, method, budget
):
    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.reference_remix_provider_enabled = True
    settings.tengli_daily_budget_usd = 0
    settings.tengli_monthly_budget_usd = 0
    settings.tengli_daily_request_limit = 0
    with client.app.state.session_factory() as session:
        job = JobRecord(
            id="job_" + uuid4().hex,
            workspace_id="ws_test",
            type="reference_remix",
            configuration=native_configuration(method),
            expected_item_count=5,
            estimated_cost_max_micros=450_000,
        )
        session.add(job)
        session.flush()
        _reserve_real_provider_job_if_enabled(
            session, SimpleNamespace(app=client.app), job, "usr_test"
        )
        session.flush()
        event = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.resource_id == job.id,
                AuditEventRecord.action == "provider.beta_job_reserved",
            )
        )
        assert (
            event.details["estimated_cost_micros"],
            event.details["provider_request_count"],
            event.details["group_count"],
        ) == budget


def seed_legacy_replica(
    session, *, requests=13, charge=2_290_002, native=True, estimated=False
):
    now = utc_now()
    job = JobRecord(
        id="job_" + uuid4().hex,
        workspace_id="ws_test",
        type="reference_remix",
        status="completed",
        stage="completed",
        expected_item_count=5,
        succeeded_item_count=5,
        failed_item_count=0,
        finished_at=now,
        configuration=native_configuration() if native else {"settings": {}},
    )
    session.add(job)
    session.flush()
    item = JobItemRecord(
        id="item_" + uuid4().hex,
        workspace_id="ws_test",
        job_id=job.id,
        item_key="native",
        ordinal=0,
        status="succeeded",
    )
    session.add(item)
    session.flush()
    attempt = JobAttemptRecord(
        id="attempt_" + uuid4().hex,
        workspace_id="ws_test",
        job_id=job.id,
        job_item_id=item.id,
        attempt_no=1,
        status="succeeded",
        lease_token="test",
        leased_by="test",
        lease_expires_at=now,
        provider="tengli",
        operation="reference_remix",
        provider_idempotency_key=job.id,
    )
    session.add(attempt)
    session.flush()
    session.add(
        UsageEventRecord(
            workspace_id="ws_test",
            job_id=job.id,
            job_item_id=item.id,
            attempt_id=attempt.id,
            provider="tengli",
            model="gpt-image-2",
            operation="reference_remix",
            usage_reported=False,
            raw_usage={"network_requests": requests},
            pricing_version="test",
            currency="USD",
            estimated_cost_micros=(
                (charge + requests - 1) // requests if estimated else 0
            ),
            actual_cost_micros=None if estimated else charge,
        )
    )
    reservation = AuditEventRecord(
        workspace_id="ws_test",
        action="provider.beta_job_reserved",
        resource_type="job",
        resource_id=job.id,
        request_id=job.id,
        details={
            "ledger_version": 2,
            "job_type": "reference_remix",
            "estimated_cost_micros": 1_400_000,
            "provider_request_count": 12,
            "image_budget_micros": 450_000,
            "planner_reserve_micros": 250_000,
            "group_count": 1,
        },
    )
    session.add(reservation)
    session.commit()
    return job, reservation


def test_legacy_native_settlement_reconciles_once_and_allows_next_reservation(client):
    now = utc_now()
    with client.app.state.session_factory() as session:
        job, reservation = seed_legacy_replica(session, estimated=True)
        original = dict(reservation.details)
        for _ in range(2):
            assert reconcile_and_total(
                session,
                workspace_id="ws_test",
                day_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
                month_start=now.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                ),
            ) == (2_290_002, 2_290_002, 13)
            session.flush()
        events = session.scalars(
            select(AuditEventRecord)
            .where(
                AuditEventRecord.resource_id == job.id,
            )
            .order_by(AuditEventRecord.id)
        ).all()
        assert len(events) == 4
        assert reservation.details == original
        settled = next(e for e in events if e.action == "provider.beta_job_settled")
        released = next(e for e in events if e.action == "provider.beta_job_released")
        assert (
            settled.details["legacy_native_replica_reserve_correction_micros"]
            == 890_002
        )
        assert settled.details["legacy_native_replica_request_correction"] == 1
        assert released.details["released_request_count"] == 0
        assert released.details["released_cost_micros"] == 0
        settings = client.app.state.settings
        settings.task_runner = "tengli"
        settings.reference_remix_provider_enabled = True
        settings.tengli_daily_budget_usd = 0
        settings.tengli_monthly_budget_usd = 0
        settings.tengli_daily_request_limit = 0
        new_job = JobRecord(
            id="job_" + uuid4().hex,
            workspace_id="ws_test",
            type="reference_remix",
            configuration=native_configuration(),
            expected_item_count=5,
            estimated_cost_max_micros=450_000,
        )
        session.add(new_job)
        session.flush()
        _reserve_real_provider_job_if_enabled(
            session, SimpleNamespace(app=client.app), new_job, "usr_test"
        )
        session.flush()
        assert (
            session.scalar(
                select(AuditEventRecord.id).where(
                    AuditEventRecord.resource_id == new_job.id,
                    AuditEventRecord.action == "provider.beta_job_reserved",
                )
            )
            is not None
        )


@pytest.mark.parametrize(
    "requests,charge,native",
    [(66, 2_290_002, True), (13, 13_050_001, True), (13, 2_290_002, False)],
)
def test_real_overruns_and_unrelated_remix_still_fail_closed(
    client, requests, charge, native
):
    now = utc_now()
    with client.app.state.session_factory() as session:
        seed_legacy_replica(session, requests=requests, charge=charge, native=native)
        with pytest.raises(ProviderQuotaLedgerError, match="exceed"):
            reconcile_and_total(
                session,
                workspace_id="ws_test",
                day_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
                month_start=now.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                ),
            )


def test_native_budget_requires_server_binding_and_matching_count():
    configuration = native_configuration()
    assert native_replica_budget(configuration, 4, 450_000, 250_000) is None
    configuration.pop("replica_session_id")
    assert native_replica_budget(configuration, 5, 450_000, 250_000) is None
