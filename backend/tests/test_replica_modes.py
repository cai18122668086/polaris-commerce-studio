"""Exercise current mode routing, real reservations and historical plan bindings."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import CreditReservationRecord, JobRecord, ReplicaDocumentRecord
from app.replica_exact_compact import VERSION, CompactExactReplicaRun
from app.replica_fast import image_prompt
from app.replica_modes import MODE_VERSION

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
def test_exact_restores_previous_native_protocol_and_reserves_fifteen(
    client, monkeypatch, requested_speed
):
    route, body = setup(client, monkeypatch)
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

    monkeypatch.setattr(CompactExactReplicaRun, "prepare", prepare)
    monkeypatch.setattr(CompactExactReplicaRun, "snapshot", snapshot)
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
