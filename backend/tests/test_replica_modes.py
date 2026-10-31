"""Exercise current mode routing, real reservations and historical plan bindings."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import CreditReservationRecord, JobRecord, ReplicaDocumentRecord
from app.replica_fast import image_prompt
from app.replica_modes import MODE_VERSION
from app.replica_refined import VERSION, bundle

from .test_replica import upload
from .test_replica_auto_start import setup
from .test_replica_fast import ROUTE, Gateway, confirm, create, execute, proposal


@pytest.mark.parametrize("requested_speed", ["fast", "standard"])
def test_style_uses_former_fast_exact_skill_and_charges_eight(client, requested_speed):
    gateway = Gateway(proposal(count=2))
    client.app.state.settings.reference_remix_provider_enabled = True
    client.app.state.replica_gateway = gateway
    body = {
        "request_id": str(uuid4()),
        "replica_mode_version": MODE_VERSION,
        "replication_method": "style",
        "replica_speed": requested_speed,
        "product_asset_ids": [upload(client, "red")],
        "references": [
            {"asset_id": upload(client, color)} for color in ("blue", "green")
        ],
        "facts": "用户授权红色商品",
        "auto_start_after_plan": True,
        "credit_budget": 16,
    }
    response = client.post(ROUTE + "/sessions", json=body)
    assert response.status_code == 202, response.text
    doc = client.get(ROUTE + "/documents/" + response.json()["id"]).json()
    assert doc["status"] == "generating", doc
    assert doc["payload"]["replica_speed"] == "fast"
    assert doc["payload"]["replication_method"] == "style"
    assert doc["payload"]["skill_id"] == "aurora-ecommerce-reference-remix-fast"
    assert len(gateway.plans) == 1
    assert '"method": "exact"' in gateway.plans[0].product_information[0]
    job_id = doc["payload"]["job_ids"][0]
    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, job_id)
        assert job.display_name == "一键复刻 · 风格模仿"
        assert job.estimated_credits == 16
        reservation = session.scalar(
            select(CreditReservationRecord).where(
                CreditReservationRecord.job_id == job_id
            )
        )
        assert reservation.reserved_credits == 16
        assert reservation.pricing_snapshot["credits_per_image"] == 8
        plan = session.get(ReplicaDocumentRecord, doc["id"]).payload["_fast_plan"]
        assert "Match this reference screen's composition" in image_prompt(
            plan, plan["units"][0]
        )
        assert "Build a new scene and composition" not in image_prompt(
            plan, plan["units"][0]
        )
    assert execute(client, gateway, job_id) == "completed"
    with client.app.state.session_factory() as session:
        assert session.get(JobRecord, job_id).actual_credits == 16


@pytest.mark.parametrize("requested_speed", ["fast", "standard"])
def test_exact_uses_sister_refined_protocol_and_reserves_fifteen(
    client, monkeypatch, requested_speed
):
    route, body = setup(client, monkeypatch)
    compact = bundle("replica_exact_compact").CompactExactReplicaRun
    seen = []

    async def prepare(self, values, records):
        seen.append((self.skill_id, values["_exact_model_protocol"]))
        return [
            {
                "reference": values["references"][0],
                "analysis": {},
                "prompt": "",
                "unit_id": "M01",
            }
        ]

    async def snapshot(self):
        return {
            "schema": "replica-native-v1",
            "skill_id": self.skill_id,
            "source_hash": self.source_hash,
            "files": {},
        }

    monkeypatch.setattr(compact, "prepare", prepare)
    monkeypatch.setattr(compact, "snapshot", snapshot)
    body.update(
        replica_mode_version=MODE_VERSION,
        replica_speed=requested_speed,
        credit_budget=15,
    )
    response = client.post(route + "/sessions", json=body)
    assert response.status_code == 202, response.text
    doc = client.get(route + "/documents/" + response.json()["id"]).json()
    assert doc["status"] == "generating", doc
    assert seen == [("aurora-ecommerce-reference-remix", VERSION)]
    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, doc["payload"]["job_ids"][0])
        assert job.display_name == "一键复刻 · 一比一复刻"
        assert job.estimated_credits == 15
        reservation = session.scalar(
            select(CreditReservationRecord).where(
                CreditReservationRecord.job_id == job.id
            )
        )
        assert reservation.reserved_credits == 15
        assert reservation.pricing_snapshot["credits_per_image"] == 15


def test_existing_fast_style_plan_keeps_original_skill_and_can_finish(client):
    gateway = Gateway(proposal())
    doc = create(client, gateway, method="style")
    assert doc["payload"]["skill_id"] == "all-category-style-benchmark-still-fast"
    job_id = confirm(client, doc)
    assert execute(client, gateway, job_id) == "completed"


def test_changing_mode_version_invalidates_bound_fast_plan(client):
    gateway = Gateway(proposal())
    doc = create(client, gateway, method="style")
    job_id = confirm(client, doc)
    with client.app.state.session_factory() as session:
        row = session.get(ReplicaDocumentRecord, doc["id"])
        row.payload = {**row.payload, "replica_mode_version": MODE_VERSION}
        session.commit()
    assert execute(client, gateway, job_id) == "failed"
    assert not gateway.images


def test_refined_protocol_matches_sister_and_keeps_legacy_binding():
    import app.models
    from app.replica_exact_compact import protocol_binding

    assert protocol_binding()["content_sha256"] == (
        "3d9a80bc65e6e5a9c552839a238f2b5c4197d87932b17aa1f9e61ee0b20a6ba8"
    )
    assert bundle("replica_exact_compact").protocol_binding() == {
        "version": "exact-compact-v16",
        "content_sha256": (
            "63df401796fde30686b4485af519a2f5ee0f3a3577cfd2225dfc352d2cd2c59c"
        ),
    }
    assert bundle("models") is app.models


def refined_suite(
    client,
    *,
    reject_crop=False,
    unknown_once=False,
    cancel_once=False,
    reject_plan=False,
):
    import json
    from io import BytesIO
    from types import SimpleNamespace

    from PIL import Image

    from app.provider import ProviderOutcome
    from app.task_runner import MockTaskRunner
    from tests.test_replica_compact import SyntheticGateway

    class RefinedSyntheticGateway(SyntheticGateway):
        failed_once = False

        async def plan(self, request):
            envelope = json.loads(request.product_information[0])
            if envelope["stage"] == "crop_integrity":
                self.requests.append(request)
                data = envelope["context"]
                return SimpleNamespace(
                    payload={
                        "column_id": data["column_id"],
                        "screen_count": len(data["screens"]),
                        "boundary_ys": data["boundary_ys"],
                        "decision": "REVISE" if reject_crop else "PASS",
                        "evidence": (
                            "Actual synthetic crops retain all complete source panels."
                        ),
                        "headlines_attached": not reject_crop,
                        "dependent_copy_complete": True,
                        "visual_carriers_complete": True,
                    },
                    error_code=None,
                    normalized_usage={"reported": False},
                    actual_cost_micros=0,
                )
            return await super().plan(request)

        async def edit(self, request):
            value = await super().edit(request)
            if unknown_once and request.group_key == "M002" and not self.failed_once:
                self.failed_once = True
                value.outcome = ProviderOutcome.OUTCOME_UNKNOWN
                value.artifact = None
                value.error_code = "PROVIDER_TRANSPORT_FAILED"
                value.provider_request_id = None
            if cancel_once and request.group_key == "M002" and not self.failed_once:
                self.failed_once = True
                client.app.state.task_runner.coordinator.cancel(request.job_id)
                value.outcome = ProviderOutcome.FAILED
                value.artifact = None
                value.error_code = "PROVIDER_REQUEST_REJECTED"
            return value

    state = client.app.state
    state.settings.reference_remix_provider_enabled = True
    gateway = RefinedSyntheticGateway()
    gateway.reject_always = reject_plan
    state.replica_gateway = gateway
    state.task_runner = MockTaskRunner(
        state.session_factory,
        0,
        storage=state.storage,
        xinghe_gateway=gateway,
        xinghe_concurrency=20,
        reference_remix_provider_enabled=True,
        domestic_revision_settings=state.settings,
    )
    ids = []
    for size in [(64, 96), (256, 640)]:
        image = BytesIO()
        Image.new("RGB", size, "blue").save(image, "PNG")
        uploaded = client.post(
            "/api/v1/workspaces/ws_test/assets",
            headers={"Idempotency-Key": uuid4().hex},
            files={"file": ("fixture.png", image.getvalue(), "image/png")},
        )
        assert uploaded.status_code == 201
        ids.append(uploaded.json()["id"])
    response = client.post(
        ROUTE + "/sessions",
        json={
            "request_id": uuid4().hex,
            "replica_mode_version": MODE_VERSION,
            "replication_method": "exact",
            "product_asset_ids": ids[:1],
            "references": [{"asset_id": ids[1]}],
            "facts": "Supported synthetic product",
            "auto_start_after_plan": True,
        },
    )
    assert response.status_code == 202, response.text
    return (
        client.get(ROUTE + "/documents/" + response.json()["id"]).json(),
        gateway,
        state.task_runner,
    )


def test_new_refined_suite_runs_physical_crop_audit_then_original_native_plan(client):
    import asyncio
    import json

    doc, gateway, runner = refined_suite(client)
    assert doc["status"] == "generating", doc["payload"].get("error")
    assert "crop_integrity" in [
        json.loads(r.product_information[0])["stage"] for r in gateway.requests
    ]
    job_id = doc["payload"]["job_ids"][0]
    with runner.session_factory() as db:
        row = db.get(ReplicaDocumentRecord, doc["id"])
        assert row.payload["native_snapshot"]["model_protocol"]["version"] == VERSION
    assert asyncio.run(runner.run(job_id)) == "completed"
    assert len(gateway.image_requests) == 2
    assert all(
        r.single_dispatch and r.quality == "high" for r in gateway.image_requests
    )
    with runner.session_factory() as db:
        assert db.get(JobRecord, job_id).actual_credits == 30


def test_incomplete_refined_crops_stop_without_prompt_only_fallback(client):
    doc, gateway, _ = refined_suite(client, reject_crop=True)
    assert doc["status"] == "failed", doc
    assert doc["payload"]["error_code"] == "REPLICA_SOURCE_CROP_INCOMPLETE"
    assert not doc["payload"].get("job_ids") and not gateway.image_requests


@pytest.mark.parametrize("best_effort", [False, True])
def test_refined_unknown_retry_preserves_successful_pixels_and_backup_route(
    client, best_effort
):
    import asyncio
    from copy import deepcopy

    doc, gateway, runner = refined_suite(
        client, unknown_once=True, reject_plan=best_effort
    )
    assert doc["status"] == "generating", doc["payload"].get("error")
    parent = doc["payload"]["job_ids"][0]
    assert asyncio.run(runner.run(parent)) == "partial"
    with runner.session_factory() as db:
        row = db.get(ReplicaDocumentRecord, doc["id"])
        child = row.payload["job_ids"][0]
        original = deepcopy(row.payload["native_executions"][parent]["snapshot"])
        summary = client.get("/api/v1/workspaces/ws_test/jobs/" + parent).json()
        assert child != parent, {
            "recovery_error": row.payload.get("recovery_error_code"),
            "items": [(i["status"], i["error_code"]) for i in summary["items"]],
            "error_code": summary.get("error_code"),
        }
    assert asyncio.run(runner.run(child)) == "completed"
    assert [r.group_key for r in gateway.image_requests] == ["M001", "M002", "M002"]
    assert gateway.image_requests[-1].image_route == "image-failover"
    with runner.session_factory() as db:
        assert (
            db.get(ReplicaDocumentRecord, doc["id"]).payload["native_executions"][
                parent
            ]["snapshot"]
            == original
        )
        assert (
            db.get(JobRecord, parent).actual_credits
            == db.get(JobRecord, child).actual_credits
            == 15
        )


@pytest.mark.parametrize("best_effort", [False, True])
def test_refined_cancelled_suite_manually_resumes_only_missing_images(
    client, best_effort
):
    import asyncio

    doc, gateway, runner = refined_suite(
        client, cancel_once=True, reject_plan=best_effort
    )
    parent = doc["payload"]["job_ids"][0]
    assert asyncio.run(runner.run(parent)) == "cancelled"
    response = client.post(
        ROUTE + f"/sessions/{doc['id']}/jobs/{parent}/retry",
        json={"request_id": uuid4().hex},
    )
    assert response.status_code == 202, response.text
    child = response.json()["payload"]["job_ids"][0]
    assert asyncio.run(runner.run(child)) == "completed"
    assert [r.group_key for r in gateway.image_requests] == ["M001", "M002", "M002"]
    with runner.session_factory() as db:
        assert db.get(JobRecord, child).actual_credits == 15


def test_refined_best_effort_requires_three_full_original_plan_rounds(client):
    import asyncio
    import json

    doc, gateway, runner = refined_suite(client, reject_plan=True)
    assert doc["status"] == "generating", doc["payload"].get("error")
    reviews = [
        r
        for r in gateway.requests
        if json.loads(r.product_information[0])["stage"] == "review_plan"
    ]
    assert len(reviews) >= 3
    parent = doc["payload"]["job_ids"][0]
    assert asyncio.run(runner.run(parent)) == "completed"
    assert len(gateway.image_requests) == 2


def test_current_style_split_cannot_spend_beyond_the_displayed_budget(client):
    gateway = Gateway(proposal(screens=2))
    client.app.state.settings.reference_remix_provider_enabled = True
    client.app.state.replica_gateway = gateway
    response = client.post(
        ROUTE + "/sessions",
        json={
            "request_id": str(uuid4()),
            "replica_mode_version": MODE_VERSION,
            "replication_method": "style",
            "product_asset_ids": [upload(client, "red")],
            "references": [{"asset_id": upload(client, "blue")}],
            "facts": "用户授权红色商品",
            "auto_start_after_plan": True,
            "credit_budget": 8,
        },
    )
    assert response.status_code == 202, response.text
    doc = client.get(ROUTE + "/documents/" + response.json()["id"]).json()
    assert doc["status"] == "awaiting_confirmation", doc
    assert doc["payload"]["credit_budget_exceeded"] is True
    assert doc["payload"]["credit_quote"] == {
        "image_count": 2,
        "estimated_credits": 16,
    }
    assert not doc["payload"]["job_ids"] and not gateway.images
    job_id = confirm(client, doc)
    gateway.failure = "F002"
    assert execute(client, gateway, job_id) == "partial"
    with client.app.state.session_factory() as session:
        assert session.get(JobRecord, job_id).actual_credits == 8
    gateway.failure = None
    response = client.post(
        ROUTE + f"/sessions/{doc['id']}/jobs/{job_id}/retry",
        json={"request_id": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    retry_id = response.json()["payload"]["job_ids"][0]
    assert execute(client, gateway, retry_id) == "completed"
    with client.app.state.session_factory() as session:
        assert session.get(JobRecord, retry_id).actual_credits == 8
    assert len(gateway.plans) == 1
    assert [r.group_key for r in gateway.images] == ["F001", "F002", "F002"]
