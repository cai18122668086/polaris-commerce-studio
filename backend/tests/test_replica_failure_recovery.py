"""Real retry routes with synthetic paid-call boundaries and customer accounting."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

from sqlalchemy import select

from app.models import JobRecord, ReplicaDocumentRecord, WorkspaceCreditAccountRecord
from app.provider import ProviderOutcome
from app.replica_failure_recovery import retry_once
from app.task_runner import MockTaskRunner

from .test_replica import upload
from .test_replica_fast import ROUTE, Gateway, proposal


def setup(client, *, always=False, automatic=True):
    state = client.app.state
    state.settings.reference_remix_provider_enabled = True
    gateway = Gateway(proposal(count=2))
    state.replica_gateway = gateway
    original = gateway.edit
    seen = []

    async def edit(request):
        seen.append((request.group_key, request.image_route))
        value = await original(request)
        if request.group_key == "F001" and (
            always or sum(k == "F001" for k, _ in seen) == 1
        ):
            return replace(
                value,
                outcome=ProviderOutcome.OUTCOME_UNKNOWN,
                artifact=None,
                error_code="PROVIDER_TRANSPORT_FAILED",
                provider_request_id=None,
            )
        return value

    gateway.edit = edit
    runner = MockTaskRunner(
        state.session_factory,
        0,
        storage=state.storage,
        xinghe_gateway=gateway,
        xinghe_concurrency=20,
        reference_remix_provider_enabled=True,
        domestic_revision_settings=state.settings,
        aurora_work_root=state.settings.aurora_work_root,
    )
    state.task_runner = runner
    response = client.post(
        ROUTE + "/sessions",
        json={
            "request_id": uuid4().hex,
            "replica_mode_version": "replica-modes-v2",
            "replication_method": "style",
            "product_asset_ids": [upload(client, "red")],
            "references": [{"asset_id": upload(client, c)} for c in ["blue", "green"]],
            "auto_start_after_plan": True,
        },
    )
    assert response.status_code == 202, response.text
    doc = client.get(ROUTE + "/documents/" + response.json()["id"]).json()
    if not automatic:
        runner.recovery_settings = None
    return doc, runner, gateway, seen


def test_automatic_retry_uses_backup_once_and_reuses_successful_image_and_charge(
    client,
):
    doc, runner, gateway, seen = setup(client)
    parent = doc["payload"]["job_ids"][0]
    assert asyncio.run(runner.run(parent)) == "partial"
    updated = client.get(ROUTE + "/documents/" + doc["id"]).json()
    child = updated["payload"]["job_ids"][0]
    assert child != parent
    assert updated["payload"]["retry_events"][0]["kind"] == "automatic"
    before = client.get("/api/v1/workspaces/ws_test/jobs/" + parent).json()
    asset = next(a["asset_id"] for a in before["assets"] if a["direction"] == "output")
    with runner.session_factory() as db:
        assert db.get(JobRecord, child).estimated_credits == 8
        old_receipt = deepcopy(
            db.get(ReplicaDocumentRecord, doc["id"]).payload["_fast_invocations"][
                "F001"
            ]
        )
    assert asyncio.run(runner.run(child)) == "completed"
    after = client.get("/api/v1/workspaces/ws_test/jobs/" + child).json()
    assert any(a["asset_id"] == asset for a in after["assets"])
    assert len(gateway.plans) == 1
    assert seen.count(("F001", None)) == seen.count(("F001", "image-failover")) == 1
    assert sum(k == "F002" for k, _ in seen) == 1
    assert after["cost"]["actual_credits"] == 8
    assert before["cost"]["actual_credits"] == 8
    with runner.session_factory() as db:
        history = db.get(ReplicaDocumentRecord, doc["id"]).payload[
            "_fast_invocation_history"
        ]
        assert history["F001"] == [old_receipt]
        assert db.get(JobRecord, parent).status == "partial"
    assert (
        "_fast_invocation_history"
        not in client.get(ROUTE + "/documents/" + doc["id"]).json()["payload"]
    )


def test_retry_failure_stops_after_one_automatic_attempt_and_manual_retry_remains(
    client,
):
    doc, runner, _, seen = setup(client, always=True)
    parent = doc["payload"]["job_ids"][0]
    asyncio.run(runner.run(parent))
    child = client.get(ROUTE + "/documents/" + doc["id"]).json()["payload"]["job_ids"][
        0
    ]
    asyncio.run(runner.run(child))
    assert client.get(ROUTE + "/documents/" + doc["id"]).json()["payload"][
        "job_ids"
    ] == [child]
    assert (
        asyncio.run(
            retry_once(
                runner, client.app.state.settings, client.app.state.storage, parent
            )
        )
        is None
    )
    assert len(seen) == 3
    response = client.post(
        ROUTE + f"/sessions/{doc['id']}/jobs/{child}/retry",
        json={"request_id": uuid4().hex},
    )
    assert response.status_code == 202, response.text
    latest = response.json()["payload"]["job_ids"][0]
    replay = client.post(
        ROUTE + f"/sessions/{doc['id']}/jobs/{child}/retry",
        json={"request_id": uuid4().hex},
    )
    assert replay.json()["payload"]["job_ids"] == [latest]
    with runner.session_factory() as db:
        assert (
            db.get(JobRecord, latest).configuration["_replica_retry"]["image_route"]
            == "primary"
        )


def test_unconfirmed_generic_retry_stays_fenced_but_replica_retry_is_explicit(client):
    doc, runner, _, _ = setup(client, automatic=False)
    parent = doc["payload"]["job_ids"][0]
    asyncio.run(runner.run(parent))
    blocked = client.post(
        "/api/v1/workspaces/ws_test/jobs/" + parent + "/retry",
        json={"scope": "missing"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "REPLICA_OUTCOME_RECONCILIATION_REQUIRED"
    response = client.post(
        ROUTE + f"/sessions/{doc['id']}/jobs/{parent}/retry",
        json={"request_id": uuid4().hex},
    )
    assert response.status_code == 202
    child = response.json()["payload"]["job_ids"][0]
    assert asyncio.run(runner.run(child)) == "completed"


def test_retry_reservation_failure_preserves_parent_session_and_no_partial_child(
    client,
):
    doc, runner, _, _ = setup(client, automatic=False)
    parent = doc["payload"]["job_ids"][0]
    asyncio.run(runner.run(parent))
    with runner.session_factory() as db:
        account = db.get(WorkspaceCreditAccountRecord, "ws_test")
        account.balance_credits = 0
        db.commit()
    response = client.post(
        ROUTE + f"/sessions/{doc['id']}/jobs/{parent}/retry",
        json={"request_id": uuid4().hex},
    )
    assert response.status_code == 402, response.text
    updated = client.get(ROUTE + "/documents/" + doc["id"]).json()
    assert updated["payload"]["job_ids"] == [parent]
    assert not updated["payload"].get("retry_events")
    with runner.session_factory() as db:
        assert (
            db.scalars(
                select(JobRecord).where(JobRecord.retry_of_job_id == parent)
            ).all()
            == []
        )
