"""Streamed results survive failure; continuation pays only for missing images."""

import asyncio
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from app.models import JobAssetRecord, UsageEventRecord, WorkspaceCreditAccountRecord
from app.provider import ProviderOutcome
from app.replica_exact_compact import CompactExactReplicaRun
from app.task_runner import MockTaskRunner
from app.xinghe_agent import ImageCallResult
from tests.test_api import dispatch_pending
from tests.test_replica_compact import SyntheticGateway


@pytest.mark.parametrize("best_effort", [False, True])
@pytest.mark.parametrize("stop", ["failed", "failed_first", "cancelled", "unknown"])
def test_partial_delivery_retries_missing_images_without_rebilling(
    client, tmp_path, monkeypatch, best_effort, stop
):
    client.app.state.settings.reference_remix_provider_enabled = True
    client.app.state.settings.replica_exact_compact_workspaces = ("ws_test",)
    gateway = SyntheticGateway()
    gateway.reject_always = best_effort
    original_edit = gateway.edit
    calls = []
    stopped_once = False
    failed_key = "M001" if stop == "failed_first" else "M002"
    delivered_ordinal = 1 if stop == "failed_first" else 0

    async def edit(request):
        nonlocal stopped_once
        calls.append(request.group_key)
        if request.group_key == failed_key and not stopped_once:
            stopped_once = True
            for _ in range(500):
                with client.app.state.session_factory() as db:
                    delivered = db.scalar(
                        select(JobAssetRecord).where(
                            JobAssetRecord.job_id == request.job_id,
                            JobAssetRecord.ordinal == delivered_ordinal,
                            JobAssetRecord.direction == "output",
                        )
                    )
                    if delivered is not None:
                        break
                await asyncio.sleep(0.01)
            assert delivered is not None
            if stop == "cancelled":
                client.app.state.task_runner.coordinator.cancel(request.job_id)
            return ImageCallResult(
                outcome=ProviderOutcome.OUTCOME_UNKNOWN
                if stop == "unknown"
                else ProviderOutcome.FAILED,
                error_code="PROVIDER_TIMEOUT"
                if stop == "unknown"
                else "PROVIDER_REQUEST_REJECTED",
                error_message="Synthetic stop",
                retryable=False,
                raw_usage={"network_requests": 1},
                provider_request_id="synthetic-stop",
                normalized_usage={},
                api_latency_seconds=0.01,
                actual_cost_micros=0,
            )
        return await original_edit(request)

    gateway.edit = edit
    client.app.state.replica_gateway = gateway
    client.app.state.task_runner = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        reference_remix_provider_enabled=True,
        aurora_work_root=tmp_path / "worker",
    )
    original_init = CompactExactReplicaRun.__init__

    def isolated_init(self, *args, **kwargs):
        kwargs.setdefault("root", tmp_path / "native")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(CompactExactReplicaRun, "__init__", isolated_init)
    ids = []
    for size in [(64, 96), (256, 640)]:
        image = BytesIO()
        Image.new("RGB", size, "blue").save(image, "PNG")
        response = client.post(
            "/api/v1/workspaces/ws_test/assets",
            headers={"Idempotency-Key": uuid4().hex},
            files={"file": ("synthetic.png", image.getvalue(), "image/png")},
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])
    with client.app.state.session_factory() as db:
        original_balance = db.get(
            WorkspaceCreditAccountRecord, "ws_test"
        ).balance_credits
    route = "/api/v1/workspaces/ws_test/replica"
    response = client.post(
        route + "/sessions",
        json={
            "request_id": uuid4().hex,
            "replication_method": "exact",
            "product_asset_ids": ids[:1],
            "references": [{"asset_id": ids[1]}],
            "facts": "Supported synthetic product",
            "auto_start_after_plan": True,
        },
    )
    assert response.status_code == 202, response.text
    did = response.json()["id"]
    doc = client.get(route + "/documents/" + did).json()
    jid = doc["payload"]["job_ids"][0]
    dispatch_pending(client)
    parent = client.get("/api/v1/workspaces/ws_test/jobs/" + jid).json()
    assert parent["status"] == ("cancelled" if stop == "cancelled" else "partial"), (
        parent
    )
    assert parent["cost"]["actual_credits"] == 15
    first_asset = next(
        a["asset_id"] for a in parent["assets"] if a["direction"] == "output"
    )
    assert calls == ["M001", "M002"]
    response = client.post(
        route + f"/sessions/{did}/jobs/{jid}/retry", json={"request_id": uuid4().hex}
    )
    assert response.status_code == 202, response.text
    child_id = response.json()["payload"]["job_ids"][0]
    child = client.get("/api/v1/workspaces/ws_test/jobs/" + child_id).json()
    assert child["cost"]["estimated_credits"] == 15
    assert child["items"][delivered_ordinal]["status"] == "reused"
    dispatch_pending(client)
    child = client.get("/api/v1/workspaces/ws_test/jobs/" + child_id).json()
    with client.app.state.session_factory() as db:
        native_errors = [
            u.raw_usage.get("metrics", {}).get("native_error")
            for u in db.scalars(
                select(UsageEventRecord).where(UsageEventRecord.job_id == child_id)
            )
        ]
    assert child["status"] == ("partial" if stop == "unknown" else "completed"), {
        "error": child.get("error_message"),
        "calls": calls,
        "native_errors": native_errors,
        "items": [
            (i["ordinal"], i["status"], i["error_code"], i["error_message"])
            for i in child["items"]
        ],
    }
    assert child["cost"]["actual_credits"] == (0 if stop == "unknown" else 15)
    assert (
        next(
            a["asset_id"]
            for a in child["assets"]
            if a["direction"] == "output" and a["ordinal"] == delivered_ordinal
        )
        == first_asset
    )
    assert calls == (
        ["M001", "M002"] if stop == "unknown" else ["M001", "M002", failed_key]
    )
    with client.app.state.session_factory() as db:
        account = db.get(WorkspaceCreditAccountRecord, "ws_test")
        assert account.balance_credits == original_balance - (
            15 if stop == "unknown" else 30
        )
        assert account.reserved_credits == 0
