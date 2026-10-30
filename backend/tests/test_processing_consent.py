from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.main import create_app
from app.models import ProcessingConsentRecord
from app.processing_consent import NOTICE, NOTICE_HASH, POLICY_VERSION
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)

CHOICE = {
    "policyVersion": POLICY_VERSION,
    "hongKongProcessing": True,
    "aiTraining": True,
}
PATH = "/api/v1/me/processing-consent"


def upload(client, workspace):
    image = BytesIO()
    Image.new("RGB", (64, 64), "white").save(image, "PNG")
    return client.post(
        f"/api/v1/workspaces/{workspace}/assets",
        headers={"Idempotency-Key": "synthetic-upload"},
        data={"origin_kind": "upload", "media_kind": "image"},
        files={"file": ("synthetic.png", image.getvalue(), "image/png")},
    )


def test_old_session_needs_explicit_choices_and_revoke_keeps_read_access(tmp_path):
    backend = FakeExternalAuthBackend(identity=verified_identity())
    with TestClient(create_app(external_settings(tmp_path), backend)) as client:
        user_id = client.get("/api/v1/me").json()["id"]
        workspace = client.get("/api/v1/workspaces").json()[0]["id"]
        assert client.get(PATH).json()["accepted"] is False
        assert upload(client, workspace).status_code == 403
        assert (
            client.post(
                f"/api/v1/workspaces/{workspace}/jobs/job_missing/cancel",
                json={},
                headers={"Idempotency-Key": "synthetic-cancel"},
            ).status_code
            == 404
        )  # Cancellation reaches the handler without new consent.
        for partial in (
            {},
            {**CHOICE, "aiTraining": False},
            {**CHOICE, "hongKongProcessing": False},
        ):
            assert client.post(PATH, json=partial).status_code in {400, 422}
        assert (
            client.post(PATH, json={**CHOICE, "aiTraining": "true"}).status_code == 422
        )
        assert (
            client.post(PATH, json={**CHOICE, "policyVersion": "old"}).status_code
            == 409
        )
        for _ in range(2):
            assert client.post(PATH, json=CHOICE).json()["accepted"] is True
        with client.app.state.session_factory() as session:
            records = session.scalars(select(ProcessingConsentRecord)).all()
            assert len(records) == 1
            assert records[0].user_id == user_id
            assert records[0].notice == NOTICE
            assert records[0].notice_sha256 == NOTICE_HASH
            assert records[0].choices == CHOICE
        created = upload(client, workspace)
        assert created.status_code == 201, created.text
        assert client.delete(PATH).json()["accepted"] is False
        assert upload(client, workspace).status_code == 403
        assert client.get(f"/api/v1/workspaces/{workspace}/assets").status_code == 200
        assert client.get(f"/api/v1/workspaces/{workspace}/jobs").status_code == 200
        # Existing originals remain downloadable after withdrawal.
        asset = created.json()["id"]
        download = client.post(
            f"/api/v1/workspaces/{workspace}/assets/{asset}/access-url",
            json={"disposition": "attachment", "variant": "original"},
        )
        assert download.status_code == 200
        assert client.get(download.json()["url"]).status_code == 200
        assert client.post(PATH, json=CHOICE).json()["accepted"] is True
        with client.app.state.session_factory() as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(ProcessingConsentRecord)
                )
                == 2
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ProcessingConsentRecord)
                    .where(ProcessingConsentRecord.withdrawn_at.is_not(None))
                )
                == 1
            )


def test_consent_is_scoped_to_authenticated_identity(tmp_path):
    backend = FakeExternalAuthBackend()
    with TestClient(create_app(external_settings(tmp_path), backend)) as client:
        assert client.post(PATH, json=CHOICE).status_code == 401
        backend.identity = verified_identity()
        assert client.post(PATH, json=CHOICE).status_code == 200
        backend.identity = verified_identity(
            primary_user_id="another-subject", email="other@example.com"
        )
        assert client.get(PATH).json()["accepted"] is False


def test_withdrawn_consent_does_not_block_support_or_payment_handlers(tmp_path):
    backend = FakeExternalAuthBackend(identity=verified_identity())
    with TestClient(create_app(external_settings(tmp_path), backend)) as client:
        workspace = client.get("/api/v1/workspaces").json()[0]["id"]
        prefix = f"/api/v1/workspaces/{workspace}"
        assert client.get(PATH).json()["accepted"] is False
        help_request = client.post(
            prefix + "/support-cases",
            headers={"Idempotency-Key": "consent-support-test"},
            json={"issue": "撤回后仍需要查看和核对已有任务"},
        )
        assert help_request.status_code == 201, help_request.text
        purchase = client.post(
            prefix + "/credits/purchases",
            headers={"Idempotency-Key": "consent-purchase-test"},
            json={"package_id": "pack_small"},
        )
        assert (
            purchase.json().get("error", {}).get("code")
            != "PROCESSING_CONSENT_REQUIRED"
        )
        reconcile = client.post(prefix + "/credits/purchases/pay_missing/reconcile")
        assert reconcile.status_code == 404
        assert (
            client.get(
                prefix + "/jobs/job_missing/plan/automatic-delivery-authorization"
            ).status_code
            == 404
        )


def test_new_ai_jobs_and_replica_inputs_need_current_consent(tmp_path):
    from uuid import uuid4

    backend = FakeExternalAuthBackend(identity=verified_identity())
    with TestClient(create_app(external_settings(tmp_path), backend)) as client:
        workspace = client.get("/api/v1/workspaces").json()[0]["id"]
        assert client.post(PATH, json=CHOICE).status_code == 200
        asset = upload(client, workspace).json()["id"]
        assert client.delete(PATH).status_code == 200
        job = client.post(
            f"/api/v1/workspaces/{workspace}/jobs",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "type": "creative_image",
                "input": {"product_asset_ids": [asset]},
                "configuration": {"image_count": 1, "instruction": "保持商品真实外观"},
            },
        )
        assert job.status_code == 403, job.text
        assert job.json()["error"]["code"] == "PROCESSING_CONSENT_REQUIRED"
        replica = client.post(
            f"/api/v1/workspaces/{workspace}/replica/sessions",
            json={
                "request_id": str(uuid4()),
                "product_asset_ids": [asset],
                "references": [{"kind": "asset", "asset_id": asset}],
                "replication_method": "exact",
                "replica_speed": "fast",
            },
        )
        assert replica.status_code == 403, replica.text
        assert replica.json()["error"]["code"] == "PROCESSING_CONSENT_REQUIRED"
