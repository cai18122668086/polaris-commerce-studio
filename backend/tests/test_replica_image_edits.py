from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (
    AssetRecord,
    AuditEventRecord,
    CreditLedgerEntryRecord,
    JobAssetRecord,
    JobItemRecord,
    JobRecord,
    ReplicaDocumentRecord,
    UserRecord,
    WorkspaceMemberRecord,
    utc_now,
)
from tests.test_api import WORKSPACE_ID, local_edit_payload
from tests.test_local_edit_review import _get, _resolve
from tests.test_masked_repair import (
    OfflineMaskedGateway,
    _dispatch,
    _install_runner,
    _png,
    _upload,
    _valid_inputs,
)


@pytest.fixture
def replica_frame(client):
    source, mask, _ = _valid_inputs(client)
    other = _upload(
        client,
        _png((8, 8), (10, 180, 40, 255)),
        media_kind="image",
        filename="second.png",
    )
    gateway = OfflineMaskedGateway(review_success=True, outcomes=["success"] * 10)
    _install_runner(client, gateway)
    with client.app.state.session_factory() as session:
        document = ReplicaDocumentRecord(
            id="replica_session",
            workspace_id=WORKSPACE_ID,
            created_by="usr_test",
            kind="session",
            fingerprint=uuid4().hex,
            status="completed",
            payload={"job_ids": ["job_replica_parent"]},
        )
        session.add(document)
        job = JobRecord(
            id="job_replica_parent",
            workspace_id=WORKSPACE_ID,
            type="reference_remix",
            status="completed",
            stage="completed",
            progress=100,
            configuration={
                "replica_session_id": document.id,
                "input": {},
                "settings": {},
            },
            expected_item_count=2,
            succeeded_item_count=2,
            failed_item_count=0,
            estimated_credits=16,
            actual_credits=16,
            finished_at=utc_now(),
        )
        session.add(job)
        session.flush()
        for ordinal, asset_id in enumerate([source["id"], other["id"]]):
            item = JobItemRecord(
                id=f"item_replica_{ordinal}",
                item_key=f"replica-{ordinal}",
                workspace_id=WORKSPACE_ID,
                job_id=job.id,
                ordinal=ordinal,
                status="succeeded",
                stage="generated",
                configuration={},
                result_source="generated",
                finished_at=utc_now(),
            )
            session.add(item)
            session.flush()
            session.add(
                JobAssetRecord(
                    workspace_id=WORKSPACE_ID,
                    job_id=job.id,
                    job_item_id=item.id,
                    asset_id=asset_id,
                    direction="output",
                    role="generated_image",
                    ordinal=0,
                    is_deliverable=True,
                    validation={"sha256": session.get(AssetRecord, asset_id).sha256},
                )
            )
        session.commit()
    return {
        "job_id": "job_replica_parent",
        "item_id": "item_replica_0",
        "source": source["id"],
        "other": other["id"],
        "mask": mask["id"],
        "gateway": gateway,
    }


def _create(client, frame, *, source=None, explicit=True, key=None):
    payload = local_edit_payload(source or frame["source"], frame["mask"])
    if explicit:
        payload["input"]["replica_output"] = {
            "job_id": frame["job_id"],
            "job_item_id": frame["item_id"],
        }
    return client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        json=payload,
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def _pending_edit(client, frame, *, source=None):
    response = _create(client, frame, source=source)
    assert response.status_code == 202, response.text
    job = response.json()
    assert _dispatch(client) == 1
    job = _get(client, job["id"])
    assert job["status"] == "awaiting_final_review", job
    return job, next(row for row in job["assets"] if row["role"] == "locked_candidate")


def _history(client, frame):
    response = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{frame['job_id']}/items/{frame['item_id']}/local-edits"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _select(client, frame, current, local_job_id, *, key=None):
    return client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{frame['job_id']}/items/{frame['item_id']}/local-edits/selection",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"expected_current_asset_id": current, "local_edit_job_id": local_job_id},
    )


def test_accept_updates_the_exact_replica_frame_and_keeps_original(
    client, replica_frame
):
    frame = replica_frame
    job, image = _pending_edit(client, frame)
    before = _get(client, frame["job_id"])
    assert {row["asset_id"] for row in before["assets"] if row["is_deliverable"]} == {
        frame["source"],
        frame["other"],
    }
    assert _history(client, frame)["records"][0]["status"] == "awaiting_final_review"
    key = str(uuid4())
    accepted = _resolve(client, job, image, "accept", key=key)
    assert accepted.status_code == 202, accepted.text
    assert _resolve(client, job, image, "accept", key=key).status_code == 202
    parent = _get(client, frame["job_id"])
    outputs = [
        row
        for row in parent["assets"]
        if row["is_deliverable"] and row["direction"] == "output"
    ]
    assert len(outputs) == 2
    assert (
        next(row for row in outputs if row["job_item_id"] == frame["item_id"])[
            "asset_id"
        ]
        == image["asset_id"]
    )
    assert (
        next(row for row in outputs if row["job_item_id"] != frame["item_id"])[
            "asset_id"
        ]
        == frame["other"]
    )
    original = next(
        row for row in parent["assets"] if row["asset_id"] == frame["source"]
    )
    assert original["is_deliverable"] is False
    assert parent["status"] == "completed" and parent["cost"]["actual_credits"] == 16
    saved = _history(client, frame)
    assert saved["current_asset_id"] == image["asset_id"]
    assert saved["original_asset_id"] == frame["source"]
    assert saved["current_local_edit_job_id"] == job["id"]
    assert saved["records"][0]["is_current"]
    with client.app.state.session_factory() as session:
        entries = session.scalars(
            select(CreditLedgerEntryRecord).where(
                CreditLedgerEntryRecord.job_id == job["id"],
                CreditLedgerEntryRecord.entry_type == "settle",
            )
        ).all()
        assert len(entries) == 1 and entries[0].delta_balance_credits == -5
        events = session.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.action == "replica.output_selected"
            )
        ).all()
        assert len(events) == 1 and events[0].details["additional_credits"] == 0
    assert len(frame["gateway"].masked_calls) == 1


def test_history_restores_original_and_modified_without_generation_or_charge(
    client, replica_frame
):
    frame = replica_frame
    job, image = _pending_edit(client, frame)
    assert _resolve(client, job, image, "accept").status_code == 202
    key = str(uuid4())
    restored = _select(client, frame, image["asset_id"], None, key=key)
    assert restored.status_code == 200, restored.text
    assert _select(client, frame, image["asset_id"], None, key=key).status_code == 200
    assert _history(client, frame)["current_asset_id"] == frame["source"]
    assert _select(client, frame, frame["source"], job["id"]).status_code == 200
    assert _history(client, frame)["current_asset_id"] == image["asset_id"]
    stale = _select(client, frame, frame["source"], None)
    assert stale.status_code == 409
    assert _history(client, frame)["current_asset_id"] == image["asset_id"]
    assert len(frame["gateway"].masked_calls) == 1
    with client.app.state.session_factory() as session:
        assert (
            len(
                session.scalars(
                    select(CreditLedgerEntryRecord).where(
                        CreditLedgerEntryRecord.entry_type == "settle"
                    )
                ).all()
            )
            == 1
        )


def test_continued_edit_keeps_both_jobs_and_old_version_selection(
    client, replica_frame
):
    frame = replica_frame
    first, first_image = _pending_edit(client, frame)
    assert _resolve(client, first, first_image, "accept").status_code == 202
    frame["gateway"].raw_alpha = 128
    second, second_image = _pending_edit(client, frame, source=first_image["asset_id"])
    assert _resolve(client, second, second_image, "accept").status_code == 202
    saved = _history(client, frame)
    assert saved["current_asset_id"] == second_image["asset_id"]
    assert {row["job_id"] for row in saved["records"]} == {first["id"], second["id"]}
    assert (
        _select(client, frame, second_image["asset_id"], first["id"]).status_code == 200
    )
    assert _history(client, frame)["current_asset_id"] == first_image["asset_id"]
    assert len(frame["gateway"].masked_calls) == 2


def test_paid_complete_variant_switch_also_refreshes_parent(client, replica_frame):
    frame = replica_frame
    job, locked = _pending_edit(client, frame)
    raw = next(row for row in job["assets"] if row["role"] == "provider_raw")
    assert _resolve(client, job, locked, "accept").status_code == 202
    accepted = _resolve(
        client, job, raw, "accept", variant="original", allow_outside=True
    )
    assert accepted.status_code == 202, accepted.text
    assert _history(client, frame)["current_asset_id"] == raw["asset_id"]
    assert len(frame["gateway"].masked_calls) == 1


def test_binding_cannot_edit_a_different_frame(client, replica_frame):
    frame = replica_frame
    response = _create(client, {**frame, "item_id": "item_replica_1"})
    assert response.status_code == 409, response.text
    assert _history(client, frame)["records"] == []
    assert len(frame["gateway"].masked_calls) == 0


def test_legacy_request_infers_unique_replica_origin_and_replays(client, replica_frame):
    key = str(uuid4())
    first = _create(client, replica_frame, explicit=False, key=key)
    assert first.status_code == 202, first.text
    replay = _create(client, replica_frame, explicit=False, key=key)
    assert replay.status_code == 202 and replay.json()["id"] == first.json()["id"]
    assert (
        first.json()["configuration"]["input"]["replica_output"]["job_id"]
        == replica_frame["job_id"]
    )
    assert len(_history(client, replica_frame)["records"]) == 1


def test_unaccepted_history_cannot_replace_replica(client, replica_frame):
    job, _ = _pending_edit(client, replica_frame)
    response = _select(client, replica_frame, replica_frame["source"], job["id"])
    assert response.status_code == 409
    assert (
        _history(client, replica_frame)["current_asset_id"] == replica_frame["source"]
    )
    assert (
        _select(
            client, replica_frame, replica_frame["source"], "job_foreign"
        ).status_code
        == 404
    )


def test_viewer_can_read_history_but_cannot_change_selection(client, replica_frame):
    with client.app.state.session_factory() as session:
        session.add(
            UserRecord(
                id="usr_viewer", auth_provider="development", auth_subject="usr_viewer"
            )
        )
        session.flush()
        session.add(
            WorkspaceMemberRecord(
                workspace_id=WORKSPACE_ID, user_id="usr_viewer", role="viewer"
            )
        )
        session.commit()
    frame = replica_frame
    path = (f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{frame['job_id']}"
            f"/items/{frame['item_id']}/local-edits")
    headers = {"X-User-Id": "usr_viewer"}
    read = client.get(path, headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["allowed_actions"] == []
    denied = client.post(
        path + "/selection",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_current_asset_id": frame["source"]},
    )
    assert denied.status_code == 403


def test_reused_replica_output_keeps_original_and_previous_edit_history(
    client, replica_frame
):
    frame = replica_frame
    first, image = _pending_edit(client, frame)
    assert _resolve(client, first, image, "accept").status_code == 202
    with client.app.state.session_factory() as session:
        session.add(
            JobRecord(
                id="job_replica_retry",
                workspace_id=WORKSPACE_ID,
                type="reference_remix",
                status="completed",
                stage="completed",
                progress=100,
                configuration={
                    "replica_session_id": "replica_session",
                    "input": {},
                    "settings": {},
                },
                expected_item_count=1,
                succeeded_item_count=1,
                failed_item_count=0,
                finished_at=utc_now(),
                retry_of_job_id=frame["job_id"],
            )
        )
        session.flush()
        session.add(
            JobItemRecord(
                id="item_replica_retry",
                item_key="reused-first",
                workspace_id=WORKSPACE_ID,
                job_id="job_replica_retry",
                ordinal=0,
                status="reused",
                stage="generated",
                configuration={},
                result_source="reused",
                source_job_item_id=frame["item_id"],
                finished_at=utc_now(),
            )
        )
        session.flush()
        prior = session.scalar(
            select(JobAssetRecord).where(
                JobAssetRecord.job_id == frame["job_id"],
                JobAssetRecord.job_item_id == frame["item_id"],
                JobAssetRecord.is_deliverable.is_(True),
            )
        )
        session.add(
            JobAssetRecord(
                workspace_id=WORKSPACE_ID,
                job_id="job_replica_retry",
                job_item_id="item_replica_retry",
                asset_id=prior.asset_id,
                direction="output",
                role=prior.role,
                ordinal=0,
                is_deliverable=True,
                validation=dict(prior.validation),
            )
        )
        session.commit()
    retry_frame = {
        **frame,
        "job_id": "job_replica_retry",
        "item_id": "item_replica_retry",
    }
    frame["gateway"].raw_alpha = 128
    second, second_image = _pending_edit(client, retry_frame, source=image["asset_id"])
    assert _resolve(client, second, second_image, "accept").status_code == 202
    assert len(_history(client, retry_frame)["records"]) == 2
    assert (
        _select(client, retry_frame, second_image["asset_id"], None).status_code == 200
    )
    assert _history(client, retry_frame)["current_asset_id"] == frame["source"]
    assert _history(client, frame)["current_asset_id"] == image["asset_id"]


def test_preexisting_accepted_edit_can_be_synchronized_without_new_generation(
    client, replica_frame
):
    from app.replica_image_edits import apply_accepted_edit

    frame = replica_frame
    job, image = _pending_edit(client, frame)
    assert _resolve(client, job, image, "accept").status_code == 202
    with client.app.state.session_factory() as session:
        selected = session.scalar(
            select(JobAssetRecord).where(
                JobAssetRecord.job_id == frame["job_id"],
                JobAssetRecord.role == "replica_selected_result",
            )
        )
        session.delete(selected)
        original = session.scalar(
            select(JobAssetRecord).where(
                JobAssetRecord.job_id == frame["job_id"],
                JobAssetRecord.asset_id == frame["source"],
            )
        )
        original.is_deliverable = True
        local = session.get(JobRecord, job["id"])
        inputs = dict(local.configuration["input"])
        inputs.pop("replica_output")
        local.configuration = {**local.configuration, "input": inputs}
        session.commit()
    assert _history(client, frame)["current_asset_id"] == frame["source"]
    with client.app.state.session_factory() as session:
        local = session.get(JobRecord, job["id"])
        delivery = session.scalar(
            select(JobAssetRecord).where(
                JobAssetRecord.job_id == job["id"],
                JobAssetRecord.direction == "output",
                JobAssetRecord.is_deliverable.is_(True),
            )
        )
        apply_accepted_edit(session, local, delivery, None)
        session.commit()
    assert _history(client, frame)["current_asset_id"] == image["asset_id"]
    assert len(frame["gateway"].masked_calls) == 1
