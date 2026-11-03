import asyncio
import hashlib
from dataclasses import replace
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from app.domain import JobStatus
from app.masked_repair import MaskedRepairError
from app.masked_review_contract import validate_review
from app.models import (
    AssetRecord,
    AuditEventRecord,
    CreditLedgerEntryRecord,
    CreditReservationRecord,
    JobAssetRecord,
    JobRecord,
)
from app.services import release_credits, transition_job
from tests.test_api import WORKSPACE_ID
from tests.test_masked_repair import (
    OfflineMaskedGateway,
    _create_job,
    _dispatch,
    _install_runner,
    _valid_inputs,
)


def _pending(client, *, verdict=False):
    gateway = OfflineMaskedGateway(review_success=verdict)
    _install_runner(client, gateway)
    source, mask, _ = _valid_inputs(client)
    _, job = _create_job(client, source["id"], mask["id"])
    assert _dispatch(client) == 1
    body = _get(client, job["id"])
    assert body["status"] == "awaiting_final_review", body
    assert body["failed_item_count"] == 0
    locked = next(a for a in body["assets"] if a["role"] == "locked_candidate")
    return gateway, body, locked


def _get(client, job_id):
    return client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}").json()


def _resolve(
    client, job, image, action, *, key=None, variant="locked", allow_outside=False
):
    return client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/local-edit/review",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={
            "action": action,
            "expected_candidate_sha256": image["validation"]["sha256"],
            "candidate_variant": variant,
            "allow_outside_selection_changes": allow_outside,
        },
    )


def test_selection_does_not_charge_again_after_generation(client):
    gateway, job, image = _pending(client)
    with client.app.state.session_factory() as session:
        hold = session.scalar(
            select(CreditReservationRecord).where(
                CreditReservationRecord.job_id == job["id"]
            )
        )
        assert hold.status == "settled"
        reserved = hold.reserved_credits
    key = str(uuid4())
    response = _resolve(client, job, image, "accept", key=key)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "completed"
    delivered = next(a for a in response.json()["assets"] if a["is_deliverable"])
    assert delivered["asset_id"] == image["asset_id"]
    assert _resolve(client, job, image, "accept", key=key).status_code == 202
    assert _resolve(client, job, image, "accept").status_code == 409
    with client.app.state.session_factory() as session:
        hold = session.scalar(
            select(CreditReservationRecord).where(
                CreditReservationRecord.job_id == job["id"]
            )
        )
        assert hold.status == "settled"
        assert hold.settled_credits == reserved
        entries = session.scalars(
            select(CreditLedgerEntryRecord).where(
                CreditLedgerEntryRecord.job_id == job["id"],
                CreditLedgerEntryRecord.entry_type == "settle",
            )
        ).all()
        assert len(entries) == 1
    assert len(gateway.masked_calls) == len(gateway.review_calls) == 1


def test_original_adoption_preserves_exact_bytes_and_charges_no_more(client):
    gateway, job, locked = _pending(client)
    raw = next(a for a in job["assets"] if a["role"] == "provider_raw")
    response = _resolve(
        client, job, raw, "accept", variant="original", allow_outside=True
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "completed"
    delivered = next(a for a in body["assets"] if a["is_deliverable"])
    assert delivered["asset_id"] == raw["asset_id"]
    validation = delivered["validation"]
    assert validation["sha256"] == raw["validation"]["sha256"]
    assert validation["candidate_variant"] == "original"
    assert validation["outside_selection_changes_authorized"] is True
    assert validation["strict_lock_success"] is False
    assert validation["outside_changed_pixels"] > 0
    assert validation["outside_change_measurement_basis"] == "provider_input_canvas"
    assert "reviewed_artifact_sha256" not in validation
    assert any(a["asset_id"] == locked["asset_id"] for a in body["assets"])
    access = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets/{raw['asset_id']}/access-url",
        json={"disposition": "attachment", "variant": "original"},
    )
    assert access.status_code == 200, access.text
    downloaded = client.get(access.json()["url"]).content
    assert hashlib.sha256(downloaded).hexdigest() == raw["validation"]["sha256"]
    with Image.open(BytesIO(downloaded)) as image:
        # Full generation uses the provider's canvas, not a second resize/composite.
        assert image.size == (
            gateway.masked_calls[0].width,
            gateway.masked_calls[0].height,
        )
        assert image.size != (8, 8)
    assert body["cost"]["actual_credits"] == 5
    assert len(gateway.masked_calls) == len(gateway.review_calls) == 1
    with client.app.state.session_factory() as session:
        entries = session.scalars(
            select(CreditLedgerEntryRecord).where(
                CreditLedgerEntryRecord.job_id == job["id"],
                CreditLedgerEntryRecord.entry_type == "settle",
            )
        ).all()
        assert len(entries) == 1
        assert entries[0].delta_balance_credits == -5
        audit = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.resource_id == job["id"],
                AuditEventRecord.action == "masked_repair.user_accept",
            )
        )
        assert audit.actor_user_id == "usr_test"
        assert audit.details["candidate_variant"] == "original"
        assert audit.details["outside_selection_changes_authorized"] is True
        assert (
            audit.details["outside_changed_pixels"]
            == validation["outside_changed_pixels"]
        )


def test_original_requires_explicit_full_image_choice(client):
    gateway, job, _ = _pending(client)
    raw = next(a for a in job["assets"] if a["role"] == "provider_raw")
    denied = _resolve(client, job, raw, "accept", variant="original")
    assert denied.status_code == 422, denied.text
    assert _get(client, job["id"])["status"] == "awaiting_final_review"
    assert len(gateway.masked_calls) == 1


def test_legacy_adoption_request_replays_with_explicit_default_variant(client):
    _, job, locked = _pending(client)
    key = str(uuid4())
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/local-edit/review",
        headers={"Idempotency-Key": key},
        json={
            "action": "accept",
            "expected_candidate_sha256": locked["validation"]["sha256"],
        },
    )
    assert response.status_code == 202
    assert _resolve(client, job, locked, "accept", key=key).status_code == 202


def test_original_choice_cannot_use_locked_hash_or_bypass_payment(client):
    _, job, locked = _pending(client)
    denied = _resolve(
        client, job, locked, "accept", variant="original", allow_outside=True
    )
    assert denied.status_code == 409
    raw = next(a for a in job["assets"] if a["role"] == "provider_raw")
    with client.app.state.session_factory() as session:
        debit = session.scalar(
            select(CreditLedgerEntryRecord).where(
                CreditLedgerEntryRecord.job_id == job["id"],
                CreditLedgerEntryRecord.entry_type == "settle",
            )
        )
        debit.delta_balance_credits = 0
        session.commit()
    denied = _resolve(
        client, job, raw, "accept", variant="original", allow_outside=True
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "LOCAL_EDIT_IMAGE_NOT_SETTLED"


def test_original_adoption_rejects_changed_bytes_or_input_binding(client):
    gateway, job, _ = _pending(client)
    raw = next(a for a in job["assets"] if a["role"] == "provider_raw")
    with client.app.state.session_factory() as session:
        asset = session.get(AssetRecord, raw["asset_id"])
        key = asset.object_key
    original_read = client.app.state.storage.read_bytes

    async def changed(object_key):
        return (
            b"corrupted original"
            if object_key == key
            else await original_read(object_key)
        )

    client.app.state.storage.read_bytes = changed
    denied = _resolve(
        client, job, raw, "accept", variant="original", allow_outside=True
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "LOCAL_EDIT_CANDIDATE_CHANGED"
    client.app.state.storage.read_bytes = original_read
    with client.app.state.session_factory() as session:
        asset = session.get(AssetRecord, raw["asset_id"])
        asset.asset_metadata = {**asset.asset_metadata, "mask_sha256": "0" * 64}
        session.commit()
    denied = _resolve(
        client, job, raw, "accept", variant="original", allow_outside=True
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "LOCAL_EDIT_INPUT_BINDING_INVALID"
    assert len(gateway.masked_calls) == 1


def test_switching_adopted_variant_keeps_both_candidates_and_single_bill(client):
    gateway, job, locked = _pending(client)
    raw = next(a for a in job["assets"] if a["role"] == "provider_raw")
    assert _resolve(client, job, locked, "accept").status_code == 202
    completed = _get(client, job["id"])
    assert "accept_local_edit" in completed["allowed_actions"]
    key = str(uuid4())
    original = _resolve(
        client, job, raw, "accept", key=key, variant="original", allow_outside=True
    )
    assert original.status_code == 202, original.text
    assert (
        _resolve(
            client, job, raw, "accept", key=key, variant="original", allow_outside=True
        ).status_code
        == 202
    )
    restored = _resolve(client, job, locked, "accept")
    assert restored.status_code == 202, restored.text
    body = restored.json()
    delivered = [a for a in body["assets"] if a["is_deliverable"]]
    assert len(delivered) == 1 and delivered[0]["asset_id"] == locked["asset_id"]
    assert delivered[0]["validation"]["strict_lock_success"] is True
    assert {a["role"] for a in body["assets"]} >= {"provider_raw", "locked_candidate"}
    assert body["cost"]["actual_credits"] == 5
    with client.app.state.session_factory() as session:
        entries = session.scalars(
            select(CreditLedgerEntryRecord).where(
                CreditLedgerEntryRecord.job_id == job["id"],
                CreditLedgerEntryRecord.entry_type == "settle",
            )
        ).all()
        assert len(entries) == 1
    assert len(gateway.masked_calls) == len(gateway.review_calls) == 1


def test_previous_generation_original_can_be_adopted_without_another_generation(client):
    gateway, first, _ = _pending(client)
    raw = next(a for a in first["assets"] if a["role"] == "provider_raw")
    gateway.outcomes = ["success"]
    gateway.raw_alpha = 128
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{first['id']}/retry",
        headers={"Idempotency-Key": str(uuid4())},
        json={"scope": "failed"},
    )
    assert response.status_code == 201
    second = response.json()
    assert _dispatch(client) == 1
    adopted = _resolve(
        client, second, raw, "accept", variant="original", allow_outside=True
    )
    assert adopted.status_code == 202, adopted.text
    delivered = next(a for a in adopted.json()["assets"] if a["is_deliverable"])
    assert delivered["asset_id"] == raw["asset_id"]
    assert len(gateway.masked_calls) == 2
    with client.app.state.session_factory() as session:
        entries = session.scalars(
            select(CreditLedgerEntryRecord).where(
                CreditLedgerEntryRecord.job_id.in_([first["id"], second["id"]]),
                CreditLedgerEntryRecord.entry_type == "settle",
            )
        ).all()
        assert len(entries) == 2
        assert sum(e.delta_balance_credits for e in entries) == -10


def test_paid_full_image_is_accessible_before_selection(client):
    _, job, image = _pending(client)
    assert job["cost"]["actual_credits"] == job["cost"]["estimated_credits"] > 0
    access = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets/{image['asset_id']}/access-url",
        json={"disposition": "inline", "variant": "original"},
    )
    assert access.status_code == 200, access.text
    assert client.get(access.json()["url"]).status_code == 200
    assert _get(client, job["id"])["status"] == "awaiting_final_review"
    # A paid legacy raw remains accessible using its actual ledger receipt.
    raw = next(a for a in job["assets"] if a["role"] == "provider_raw")
    with client.app.state.session_factory() as session:
        record = session.get(AssetRecord, raw["asset_id"])
        record.asset_metadata = {
            k: v
            for k, v in record.asset_metadata.items()
            if k not in {"billing_policy", "billing_paid_job_id"}
        }
        session.commit()
    assert (
        client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/assets/{raw['asset_id']}/access-url",
            json={"disposition": "inline", "variant": "original"},
        ).status_code
        == 200
    )


def test_unpaid_raw_cannot_leak_via_original_thumbnail_or_signed_content(
    client, monkeypatch
):
    from datetime import UTC, datetime

    from app import masked_repair
    from app.routes_v1 import _content_signature

    original_composite = masked_repair._strict_composite

    def failed_composite(*args, **kwargs):
        raise MaskedRepairError(
            "LOCAL_EDIT_PIXEL_LOCK_FAILED", "Controlled pixel-lock failure."
        )

    monkeypatch.setattr(masked_repair, "_strict_composite", failed_composite)
    gateway = OfflineMaskedGateway()
    _install_runner(client, gateway)
    source, mask, _ = _valid_inputs(client)
    _, job = _create_job(client, source["id"], mask["id"])
    _dispatch(client)
    body = _get(client, job["id"])
    assert body["status"] == "failed"
    assert body["cost"]["actual_credits"] == 0
    raw = next(a for a in body["assets"] if a["role"] == "provider_raw")
    # The same protection applies to old unbilled raw without the new policy tag.
    with client.app.state.session_factory() as session:
        record = session.get(AssetRecord, raw["asset_id"])
        record.asset_metadata = {
            k: v
            for k, v in record.asset_metadata.items()
            if k not in {"billing_policy", "billing_paid_job_id"}
        }
        session.commit()
    for variant in ("original", "thumbnail"):
        access = client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/assets/{raw['asset_id']}/access-url",
            json={"disposition": "inline", "variant": variant},
        )
        assert access.status_code == 409
        assert access.json()["error"]["code"] == "LOCAL_EDIT_IMAGE_NOT_SETTLED"
        expires = int(datetime.now(UTC).timestamp()) + 600
        signature = _content_signature(
            client.app.state.settings.access_url_secret,
            WORKSPACE_ID,
            raw["asset_id"],
            expires,
            "inline",
            variant,
        )
        content = client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/assets/{raw['asset_id']}/content",
            params={
                "expires": expires,
                "signature": signature,
                "disposition": "inline",
                "variant": variant,
            },
        )
        assert content.status_code == 409
    # Recovering the saved generation bills once, then unlocks the same raw.
    monkeypatch.setattr(masked_repair, "_strict_composite", original_composite)
    recovered = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/retry",
        headers={"Idempotency-Key": str(uuid4())},
        json={"scope": "failed"},
    )
    assert recovered.status_code == 201
    _dispatch(client)
    assert len(gateway.masked_calls) == 1
    assert _get(client, recovered.json()["id"])["cost"]["actual_credits"] > 0
    unlocked = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets/{raw['asset_id']}/access-url",
        json={"disposition": "inline", "variant": "original"},
    )
    assert unlocked.status_code == 200


def test_recheck_reuses_exact_image_and_conflicting_verdict_stays_pending(client):
    gateway, job, image = _pending(client)
    gateway.review_success = True
    key = str(uuid4())
    assert _resolve(client, job, image, "review", key=key).status_code == 202
    assert _resolve(client, job, image, "review", key=key).status_code == 202
    assert _dispatch(client) == 1
    reviewed = _get(client, job["id"])
    assert reviewed["status"] == "awaiting_final_review"
    assert reviewed["error_code"] == "LOCAL_EDIT_VISUAL_REVIEW_NEEDS_REVIEW"
    assert (
        gateway.review_calls[0].candidate_png == gateway.review_calls[1].candidate_png
    )
    assert len(gateway.masked_calls) == 1
    assert _resolve(client, reviewed, image, "review").status_code == 409


def test_unavailable_review_recovery_delivers_same_image_without_new_generation(
    client, monkeypatch
):
    gateway, job, image = _pending(client, verdict=None)

    def unexpected_composite(*args, **kwargs):
        raise AssertionError("Recheck must read the saved bytes without recompositing.")

    monkeypatch.setattr("app.masked_repair._strict_composite", unexpected_composite)
    gateway.review_success = True
    assert _resolve(client, job, image, "review").status_code == 202
    assert _dispatch(client) == 1
    reviewed = _get(client, job["id"])
    assert reviewed["status"] == "completed", reviewed
    assert len(gateway.masked_calls) == 1
    assert len(gateway.review_calls) == 2
    assert (
        gateway.review_calls[0].candidate_png == gateway.review_calls[1].candidate_png
    )


def test_paid_failure_recovery_reuses_raw_without_duplicate_charge(client):
    gateway, job, _ = _pending(client, verdict=None)
    with client.app.state.session_factory() as session:
        record = session.get(JobRecord, job["id"])
        record.failed_item_count = 1
        transition_job(record, JobStatus.FAILED, stage="failed", progress=100)
        release_credits(session, record)
        relation = session.scalar(
            select(JobAssetRecord).where(
                JobAssetRecord.job_id == job["id"],
                JobAssetRecord.role == "locked_candidate",
            )
        )
        session.delete(relation)
        session.commit()
    gateway.review_success = True
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/retry",
        headers={"Idempotency-Key": str(uuid4())},
        json={"scope": "failed"},
    )
    assert response.status_code == 201
    assert _dispatch(client) == 1
    recovered = _get(client, response.json()["id"])
    assert recovered["status"] == "completed"
    assert recovered["cost"]["actual_credits"] == 0
    assert recovered["configuration"]["_local_edit_generation_already_paid"] is True
    assert len(gateway.masked_calls) == 1


def test_regeneration_preserves_previous_version_for_selection(client):
    gateway, original, image = _pending(client)
    gateway.outcomes = ["success"]
    gateway.review_success = True
    gateway.raw_alpha = 128
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{original['id']}/retry",
        headers={"Idempotency-Key": str(uuid4())},
        json={"scope": "failed"},
    )
    assert response.status_code == 201, response.text
    retried = response.json()
    dispatched = _dispatch(client)
    assert dispatched == 1, _get(client, retried["id"])
    retried = _get(client, retried["id"])
    assert retried["status"] == "awaiting_final_review", retried
    assert len(gateway.masked_calls) == 2
    assert _get(client, original["id"])["assets"]
    adopted = _resolve(client, retried, image, "accept")
    assert adopted.status_code == 202, adopted.text
    assert adopted.json()["status"] == "completed"
    assert (
        next(a for a in adopted.json()["assets"] if a["is_deliverable"])["asset_id"]
        == image["asset_id"]
    )
    with client.app.state.session_factory() as session:
        holds = session.scalars(
            select(CreditReservationRecord).where(
                CreditReservationRecord.job_id.in_([original["id"], retried["id"]])
            )
        ).all()
        assert sorted(h.status for h in holds) == ["settled", "settled"]
        assert (
            sum(h.settled_credits for h in holds)
            == 2 * retried["cost"]["estimated_credits"]
        )


def test_candidate_hash_and_stored_bytes_are_checked_before_adoption(client):
    _, job, image = _pending(client)
    forged = {**image, "validation": {"sha256": "0" * 64}}
    assert _resolve(client, job, forged, "accept").status_code == 409
    with client.app.state.session_factory() as session:
        asset = session.get(AssetRecord, image["asset_id"])
        # The storage adapter is untrusted at the promotion boundary.
        key = asset.object_key
    storage = client.app.state.storage
    old = storage.read_bytes

    async def changed(object_key):
        return b"changed" if object_key == key else await old(object_key)

    storage.read_bytes = changed
    assert _resolve(client, job, image, "accept").status_code == 409
    assert _get(client, job["id"])["status"] == "awaiting_final_review"


def test_declining_selection_does_not_refund_completed_generation(client):
    _, job, image = _pending(client)
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/cancel",
        headers={"Idempotency-Key": str(uuid4())},
        json={"reason": "放弃这次修改"},
    )
    assert response.status_code == 202
    _dispatch(client)
    assert _get(client, job["id"])["status"] == "cancelled"
    with client.app.state.session_factory() as session:
        hold = session.scalar(
            select(CreditReservationRecord).where(
                CreditReservationRecord.job_id == job["id"]
            )
        )
        assert hold.status == "settled"
        assert hold.settled_credits == hold.reserved_credits > 0
        assert session.get(AssetRecord, image["asset_id"]) is not None


def test_good_raw_survives_rejected_final_composite(client):
    class GoodRawBadComposite(OfflineMaskedGateway):
        async def review_masked(self, request):
            result = await super().review_masked(request)
            return replace(result, raw_visual_success=True, review_state="reject")

    gateway = GoodRawBadComposite(review_success=False)
    _install_runner(client, gateway)
    source, mask, _ = _valid_inputs(client)
    _, job = _create_job(client, source["id"], mask["id"])
    _dispatch(client)
    body = _get(client, job["id"])
    assert body["status"] == "awaiting_final_review"
    raw = next(a for a in body["assets"] if a["role"] == "provider_raw")
    final = next(a for a in body["assets"] if a["role"] == "locked_candidate")
    assert raw["validation"]["raw_visual_success"] is True
    assert final["validation"]["review_state"] == "reject"
    assert final["validation"]["strict_lock_success"] is True
    assert not any(a["is_deliverable"] for a in body["assets"])


def test_user_adoption_never_overrides_pixel_lock_even_with_valid_hash(client):
    _, job, image = _pending(client)
    storage = client.app.state.storage
    original_read = storage.read_bytes
    with client.app.state.session_factory() as session:
        asset = session.get(AssetRecord, image["asset_id"])
        key = asset.object_key
        payload = asyncio.run(original_read(key))
        with Image.open(BytesIO(payload)) as img:
            changed = img.convert("RGBA")
            changed.putpixel((0, 0), (255, 0, 0, 255))
            stream = BytesIO()
            changed.save(stream, format="PNG")
        payload = stream.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        asset.sha256 = digest
        session.commit()

    async def leak(object_key):
        return payload if object_key == key else await original_read(object_key)

    storage.read_bytes = leak
    forged = {**image, "validation": {"sha256": digest}}
    response = _resolve(client, job, forged, "accept")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOCAL_EDIT_PIXEL_LOCK_FAILED"


@pytest.mark.parametrize(
    "overrides",
    [
        {"visual_success": False},
        {
            "visual_success": False,
            "boundary_continuity": False,
            "summary": "May cause seams later.",
        },
        {"reason_codes": ["TARGET_TEXT_UNCHANGED"]},
        {"instruction_satisfied": None},
    ],
)
def test_unsupported_or_conflicting_review_is_uncertain(overrides):
    payload = {
        "visual_success": True,
        "instruction_satisfied": True,
        "identity_inside_selection_preserved": True,
        "boundary_continuity": True,
        "artifacts_absent": True,
        "reason_codes": [],
        "summary": "Requested edit is present.",
    }
    review = validate_review({**payload, **overrides})
    assert review["review_state"] == "needs_review"
    assert review["visual_success"] is None
