from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import CreditLedgerEntryRecord, JobAssetRecord, JobRecord, utc_now
from tests.test_api import WORKSPACE_ID
from tests.test_local_edit_review import _get, _pending, _resolve
from tests.test_masked_repair import _dispatch


def _retry(client, job, body, key=None):
    return client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/retry",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"scope": "failed", **body},
    )


def test_edited_regeneration_keeps_canvas_history_and_older_paid_original(client):
    gateway, first, _ = _pending(client)
    first_instruction = first["configuration"]["settings"]["instruction"]
    raw = next(a for a in first["assets"] if a["role"] == "provider_raw")
    instruction = "将选区中的文字改为清爽保湿，保持字体和位置。"
    body = {"local_edit_instruction": f"  {instruction}  "}
    key = str(uuid4())
    created = _retry(client, first, body, key)
    assert created.status_code == 201, created.text
    second = created.json()
    assert second["configuration"]["input"] == first["configuration"]["input"]
    assert second["configuration"]["settings"]["instruction"] == instruction
    assert second["retry_of_job_id"] == first["id"]
    assert "_local_edit_retry_guidance" not in second["configuration"]
    assert (
        _get(client, first["id"])["configuration"]["settings"]["instruction"]
        == first_instruction
    )
    assert _retry(client, first, body, key).json()["id"] == second["id"]
    assert (
        _retry(client, first, {"local_edit_instruction": "换一个要求"}, key).status_code
        == 409
    )
    assert len(gateway.masked_calls) == 1
    gateway.outcomes = ["success"]
    gateway.raw_alpha = 128
    assert _dispatch(client) == 1
    assert len(gateway.masked_calls) == 2
    assert instruction in gateway.masked_calls[-1].prompt
    adopted = _resolve(
        client, second, raw, "accept", variant="original", allow_outside=True
    )
    assert adopted.status_code == 202, adopted.text
    assert (
        next(a for a in adopted.json()["assets"] if a["is_deliverable"])["asset_id"]
        == raw["asset_id"]
    )
    with client.app.state.session_factory() as session:
        entries = session.scalars(
            select(CreditLedgerEntryRecord).where(
                CreditLedgerEntryRecord.job_id.in_([first["id"], second["id"]]),
                CreditLedgerEntryRecord.entry_type == "settle",
            )
        ).all()
        assert len(entries) == 2
        assert sum(row.delta_balance_credits for row in entries) == -10


@pytest.mark.parametrize("instruction", ["", "  \n\t", "字" * 4001])
def test_invalid_instruction_does_not_cancel_or_generate(client, instruction):
    gateway, first, _ = _pending(client)
    response = _retry(client, first, {"local_edit_instruction": instruction})
    assert response.status_code == 422
    assert _get(client, first["id"])["status"] == "awaiting_final_review"
    assert len(gateway.masked_calls) == 1


def test_legacy_retry_and_explicit_null_replay_the_same_request(client):
    _, first, _ = _pending(client)
    key = str(uuid4())
    created = _retry(client, first, {}, key)
    assert created.status_code == 201
    replay = _retry(client, first, {"local_edit_instruction": None}, key)
    assert replay.status_code == 201
    assert replay.json()["id"] == created.json()["id"]


def test_instruction_override_is_only_available_to_local_edits(client):
    _, first, _ = _pending(client)
    with client.app.state.session_factory() as session:
        session.get(JobRecord, first["id"]).type = "detail_pack"
        session.commit()
    assert (
        _retry(client, first, {"local_edit_instruction": "修改文字"}).status_code == 422
    )


def test_new_instruction_cannot_bypass_original_image_recovery(client):
    gateway, first, _ = _pending(client)
    with client.app.state.session_factory() as session:
        locked = session.scalar(
            select(JobAssetRecord).where(
                JobAssetRecord.job_id == first["id"],
                JobAssetRecord.role == "locked_candidate",
            )
        )
        session.delete(locked)
        job = session.get(JobRecord, first["id"])
        job.status = "failed"
        job.finished_at = utc_now()
        session.commit()
    response = _retry(client, first, {"local_edit_instruction": "修改文字"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOCAL_EDIT_RECOVERY_REQUIRED"
    assert len(gateway.masked_calls) == 1


@pytest.mark.parametrize("changed_field", ["input", "settings"])
def test_old_version_selection_still_requires_the_same_canvas_and_mode(
    client, changed_field
):
    gateway, first, image = _pending(client)
    second = _retry(client, first, {"local_edit_instruction": "把文字改为海宇"}).json()
    gateway.outcomes = ["success"]
    gateway.raw_alpha = 128
    assert _dispatch(client) == 1
    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, second["id"])
        changed = dict(job.configuration[changed_field])
        changed[
            "quality" if changed_field == "settings" else "selection_mask_asset_id"
        ] = "final" if changed_field == "settings" else "asset_other_mask"
        job.configuration = {**job.configuration, changed_field: changed}
        session.commit()
    assert _resolve(client, second, image, "accept").status_code == 409
