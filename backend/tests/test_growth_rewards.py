from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app import growth_rewards, services, welcome_credits
from app.credit_memberships import aware
from app.main import create_app
from app.models import (
    AssetRecord,
    CreditGrantRecord,
    JobAssetRecord,
    JobItemRecord,
    JobRecord,
    NewcomerOfferRecord,
    PromotionCampaignRecord,
    utc_now,
)
from tests.test_admin_commerce import prepare, resolve
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_credit_payments import NOTIFY, SECRET, paid_fields


@pytest.fixture
def site(tmp_path):
    backend = FakeExternalAuthBackend()
    settings = external_settings(tmp_path)
    settings.credit_payments_enabled = True
    settings.credit_epay_pid = "1001"
    settings.credit_epay_active_key_id = "v1"
    settings.credit_epay_keys = {"v1": SecretStr(SECRET)}
    settings.announcement_admin_emails = ["operator@example.test"]
    with TestClient(create_app(settings, backend)) as client:
        with client.app.state.session_factory() as session:
            for campaign in (
                growth_rewards.CHECKIN,
                growth_rewards.REFERRAL,
                welcome_credits.WELCOME,
                welcome_credits.NEWCOMER,
            ):
                session.add(
                    PromotionCampaignRecord(
                        id=campaign,
                        enabled=True,
                        starts_at=utc_now() - timedelta(days=1),
                    )
                )
            session.commit()
        yield client, backend


def login(site, subject, *, invite="", age=0, email=None):
    client, backend = site
    backend.identity = replace(
        verified_identity(
            primary_user_id=subject, email=email or subject + "@example.test"
        ),
        joined_at=utc_now() - timedelta(days=age),
    )
    headers = {"X-Signup-Invitation": subject + ":" + invite} if invite else {}
    result = client.get("/api/v1/workspaces", headers=headers)
    assert result.status_code == 200, result.text
    return "/api/v1/workspaces/" + result.json()[0]["id"]


def balance(client, base):
    result = client.get(base + "/credits")
    assert result.status_code == 200, result.text
    return result.json()["balance_credits"]


def buy(client, base, product):
    return client.post(
        base + "/credits/purchases",
        headers={"Idempotency-Key": str(uuid4())},
        json={"package_id": product},
    )


def produce_images(client, base, count):
    workspace_id = base.rsplit("/", 1)[1]
    with client.app.state.session_factory() as session:
        now = utc_now()
        job = JobRecord(
            id="job_" + uuid4().hex,
            workspace_id=workspace_id,
            type="product_image",
            status="queued",
            stage="queued",
            expected_item_count=count,
            configuration={"settings": {}},
        )
        session.add(job)
        session.flush()
        items = [
            JobItemRecord(
                id="item_" + uuid4().hex,
                workspace_id=workspace_id,
                job_id=job.id,
                item_key=f"image-{ordinal}",
                ordinal=ordinal,
                status="pending",
                stage="queued",
            )
            for ordinal in range(count)
        ]
        session.add_all(items)
        services.reserve_image_credits(session, workspace_id, job)
        for item in items:
            item.status = "succeeded"
            item.stage = "completed"
            item.finished_at = now
            asset_id = "asset_" + uuid4().hex
            session.add(
                AssetRecord(
                    id=asset_id,
                    workspace_id=workspace_id,
                    origin_kind="generated",
                    lifecycle_status="ready",
                    original_filename="output.png",
                    content_type="image/png",
                    byte_size=10,
                    width=96,
                    height=96,
                    sha256="a" * 64,
                    storage_provider="local",
                    storage_bucket="test",
                    object_key=asset_id + ".png",
                )
            )
            session.flush()
            session.add(
                JobAssetRecord(
                    workspace_id=workspace_id,
                    job_id=job.id,
                    job_item_id=item.id,
                    asset_id=asset_id,
                    direction="output",
                    role="generated_image",
                    ordinal=item.ordinal,
                    is_deliverable=True,
                )
            )
        job.status = "completed"
        job.finished_at = now
        job.succeeded_item_count = count
        session.flush()
        services.settle_credits(session, job, count * 5)
        session.commit()
        return asset_id


def test_registration_awards_once_per_verified_email_and_existing_accounts_are_excluded(
    site,
):
    client, _ = site
    assert balance(client, login(site, "old", age=3)) == 0
    base = login(site, "new")
    assert balance(client, base) == 50
    assert balance(client, login(site, "new")) == 50
    assert balance(client, login(site, "same-email", email="NEW@example.test")) == 0


def test_checkin_and_customer_support_grants_are_idempotent(site):
    client, _ = site
    base = login(site, "new")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: client.post(base + "/rewards/check-in"), range(2))
        )
    assert all(result.status_code == 200 for result in results)
    assert sorted(result.json()["credited_credits"] for result in results) == [0, 10]
    assert client.get(base + "/rewards").json()["checkin_validity_hours"] == 24
    body = {"issue": "申请客服赠分", "welcome_bonus": True}
    case_url = base + "/support-cases"
    first, retry = [
        client.post(case_url, headers={"Idempotency-Key": str(uuid4())}, json=body)
        for _ in range(2)
    ]
    assert first.status_code == 201 and retry.json()["id"] == first.json()["id"]
    assert balance(client, base) == 60
    staff_url = "/api/v1/admin/commerce/cases/" + first.json()["id"]
    decision = {
        "status": "resolved",
        "resolution": "已核实添加客服，50 积分已到账。",
        "grant_welcome_bonus": True,
    }
    assert client.patch(staff_url, json=decision).status_code == 403
    login(site, "operator", age=3)
    assert client.patch(staff_url, json=decision).status_code == 200
    assert client.patch(staff_url, json=decision).status_code == 200
    assert balance(client, login(site, "new")) == 110


def test_newcomer_catalog_payment_referral_and_refund(site):
    client, _ = site
    inviter_base = login(site, "inviter", age=3)
    code = client.get(inviter_base + "/invitations").json()["invite_code"]
    buyer_base = login(site, "buyer", invite=code)
    asset_id = produce_images(client, buyer_base, 10)
    view = buyer_base + "/promotions/newcomer-offer/viewed"
    assert client.post(view, json={"asset_id": asset_id}).json()["eligible"]
    catalog = client.get(buyer_base + "/credits/packages").json()["packages"]
    product = next(row for row in catalog if row["id"] == welcome_credits.PRODUCT.id)
    assert (product["amount_fen"], product["credits"]) == (990, 180)
    with ThreadPoolExecutor(max_workers=2) as pool:
        orders = list(
            pool.map(lambda _: buy(client, buyer_base, product["id"]), range(2))
        )
    assert all(order.status_code == 201 for order in orders)
    order = orders[0].json()
    assert order["id"] == orders[1].json()["id"]
    callback = paid_fields(order, money="9.90")
    assert client.get(NOTIFY, params=callback).text == "success"
    assert client.get(NOTIFY, params=callback).text == "success"
    assert balance(client, buyer_base) == 180
    assert buy(client, buyer_base, product["id"]).status_code == 403
    with client.app.state.session_factory() as session:
        lot = session.scalar(
            select(CreditGrantRecord).where(
                CreditGrantRecord.source_key == order["id"],
            )
        )
        assert abs(
            aware(lot.expires_at) - aware(lot.created_at) - timedelta(days=30)
        ) < timedelta(seconds=5)

    login(site, "inviter", age=3)
    assert balance(client, inviter_base) == 18
    assert client.get(inviter_base + "/invitations").json()["paid_count"] == 1
    login(site, "operator", age=3)
    refund = prepare(client, order, amount=990, credits=180)
    assert refund.status_code == 201, refund.text
    result = resolve(client, refund.json())
    assert result.status_code == 200, result.text
    login(site, "inviter", age=3)
    assert balance(client, inviter_base) == 0
    assert client.get(inviter_base + "/invitations").json()["refunded_count"] == 1


def test_only_visible_result_from_a_depleting_paid_image_job_unlocks_offer(site):
    client, _ = site
    base = login(site, "buyer")
    endpoint = base + "/promotions/newcomer-offer"
    initial = client.get(endpoint).json()
    assert initial["waiting_for_result"]
    assert not initial["eligible"] and not initial["result_asset_ids"]
    older_asset = produce_images(client, base, 1)
    assert balance(client, base) == 45
    assert not client.post(endpoint + "/viewed", json={"asset_id": older_asset}).json()[
        "eligible"
    ]

    latest_asset = produce_images(client, base, 9)
    assert balance(client, base) == 0
    awaiting_view = client.get(endpoint).json()
    assert (
        not awaiting_view["eligible"]
        and latest_asset in awaiting_view["result_asset_ids"]
    )
    assert not client.post(endpoint + "/impression").json()["should_show"]
    assert not client.post(endpoint + "/viewed", json={"asset_id": older_asset}).json()[
        "eligible"
    ]
    assert not client.post(
        endpoint + "/viewed", json={"asset_id": "uploaded-input"}
    ).json()["eligible"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: client.post(
                    endpoint + "/viewed", json={"asset_id": latest_asset}
                ),
                range(2),
            )
        )
    assert all(result.status_code == 200 for result in results)
    assert all(result.json()["eligible"] for result in results)
    assert results[0].json()["window_ends_at"] == results[1].json()["window_ends_at"]
    assert not client.post(endpoint + "/impression").json()["should_show"]

    with client.app.state.session_factory() as session:
        offer = session.scalar(select(NewcomerOfferRecord))
        offer.first_viewed_at = utc_now() - timedelta(minutes=1)
        session.commit()
    assert client.post(endpoint + "/impression").json()["should_show"] is True
    assert client.post(endpoint + "/impression").json()["should_show"] is False
    with client.app.state.session_factory() as session:
        offer = session.scalar(select(NewcomerOfferRecord))
        offer.first_viewed_at = utc_now() - timedelta(hours=25)
        session.commit()
    assert client.get(endpoint).json()["eligible"] is False
    assert buy(client, base, welcome_credits.PRODUCT.id).status_code == 403
