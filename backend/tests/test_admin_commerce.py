from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app import services
from app.credit_memberships import add_months, aware, refresh
from app.models import (
    AdminUserRecord,
    CreditGrantRecord,
    CreditMembershipRecord,
    UserRecord,
    WorkspaceCreditAccountRecord,
)
from tests.test_credit_payments import (
    BASE,
    NOTIFY,
    OTHER,
    WORKSPACE,
    paid_fields,
)
from tests.test_credit_payments import pilot_client as pilot_client  # noqa: F401
from tests.test_customer_credit_billing import seed_job

ROOT = "/api/v1/admin/commerce"


@pytest.fixture
def admin(pilot_client):
    pilot_client.app.state.settings.announcement_admin_emails = ["admin@example.com"]
    with pilot_client.app.state.session_factory() as session:
        session.get(UserRecord, "usr_test").email_normalized = "admin@example.com"
        session.commit()
    return pilot_client


def buy(client, product="pack_small", money="29.90"):
    result = client.post(
        BASE + "/purchases",
        headers={"Idempotency-Key": str(uuid4())},
        json={"package_id": product},
    )
    assert result.status_code == 201, result.text
    order = result.json()
    assert client.get(NOTIFY, params=paid_fields(order, money=money)).text == "success"
    return order


def prepare(client, order, amount=2990, credits=300, **kwargs):
    return client.post(
        ROOT + "/orders/" + order["id"] + "/refunds",
        headers={"Idempotency-Key": kwargs.pop("key", str(uuid4()))},
        json={
            "amount_fen": amount,
            "credits": credits,
            "reason": "客户申请退还未用部分",
            **kwargs,
        },
    )


def resolve(client, row, status="completed", **kwargs):
    return client.post(
        ROOT + "/refunds/" + row["id"] + "/resolve",
        json={
            "status": status,
            "confirm_order_id": row["purchase_id"],
            "receipt_reference": "REAL-REFUND-RECEIPT-001"
            if status == "completed"
            else "",
            "receipt_verified": status == "completed",
            "result_note": "人工核验原收款人与退款凭证一致"
            if status == "completed"
            else "客户撤回申请，终止退款",
            **kwargs,
        },
    )


def invariant(client):
    with client.app.state.session_factory() as session:
        a = session.get(WorkspaceCreditAccountRecord, WORKSPACE)
        lots = list(
            session.scalars(
                select(CreditGrantRecord).where(
                    CreditGrantRecord.workspace_id == WORKSPACE
                )
            )
        )
        assert a.balance_credits == sum(lot.remaining for lot in lots)
        assert a.reserved_credits == sum(lot.held for lot in lots)
        assert 0 <= a.reserved_credits <= a.balance_credits


def test_customer_search_notes_and_payment_summary(admin):
    buy(admin)
    rows = admin.get(
        ROOT + "/customers", params={"search": "ADMIN@example.com"}
    ).json()["items"]
    row = next(row for row in rows if row["workspace_id"] == WORKSPACE)
    assert row["email"] == "admin@example.com"
    assert row["paid_fen"] == 2990 and row["balance_credits"] == 300
    assert (
        admin.patch(
            ROOT + "/customers/" + WORKSPACE + "/note",
            json={"note": "已核对支付并回访客户"},
        ).status_code
        == 200
    )
    assert (
        admin.get(ROOT + "/customers", params={"search": WORKSPACE}).json()["items"][0][
            "note"
        ]
        == "已核对支付并回访客户"
    )
    assert admin.get(ROOT + "/orders").headers["cache-control"] == "no-store"
    result = admin.get(ROOT + "/orders").json()["items"][0]
    assert "checkout_url" not in result and "signing_key_id" not in result


def test_non_admin_and_readonly_admin_cannot_change_money(pilot_client):
    assert pilot_client.get(ROOT + "/customers").status_code == 403
    with pilot_client.app.state.session_factory() as session:
        session.add(
            AdminUserRecord(
                user_id="usr_test",
                role="admin",
                status="active",
                permissions=["commerce:read"],
            )
        )
        session.commit()
    assert pilot_client.get(ROOT + "/customers").status_code == 200
    r = pilot_client.post(
        ROOT + "/customers/" + WORKSPACE + "/adjustments",
        headers={"Idempotency-Key": str(uuid4())},
        json={"kind": "gift", "credits": 10, "reason": "用户赠送申请"},
    )
    assert r.status_code == 403


def test_gift_idempotency_and_compensation_requires_same_workspace_job(admin):
    key = str(uuid4())
    url = ROOT + "/customers/" + WORKSPACE + "/adjustments"
    body = {"kind": "gift", "credits": 30, "reason": "新用户体验赠送"}
    first = admin.post(url, headers={"Idempotency-Key": key}, json=body)
    assert first.status_code == 201, first.text
    assert (
        admin.post(url, headers={"Idempotency-Key": key}, json=body).json()
        == first.json()
    )
    assert (
        admin.post(
            url, headers={"Idempotency-Key": key}, json={**body, "credits": 31}
        ).status_code
        == 409
    )
    assert admin.get(BASE).json()["balance_credits"] == 30
    assert (
        admin.post(
            url,
            headers={"Idempotency-Key": str(uuid4())},
            json={**body, "kind": "compensation"},
        ).status_code
        == 422
    )
    with admin.app.state.session_factory() as session:
        job, _ = seed_job(session, count=1)
        session.commit()
        identifier = job.id
    assert (
        admin.post(
            ROOT + "/customers/" + OTHER + "/adjustments",
            headers={"Idempotency-Key": str(uuid4())},
            json={**body, "kind": "compensation", "job_id": identifier},
        ).status_code
        == 422
    )
    assert (
        admin.post(
            url,
            headers={"Idempotency-Key": str(uuid4())},
            json={**body, "kind": "compensation", "job_id": identifier},
        ).status_code
        == 201
    )
    ledger = admin.get(ROOT + "/ledger").json()["items"]
    assert any(
        r["entry_type"] == "compensation" and r["job_id"] == identifier for r in ledger
    )
    invariant(admin)


def test_manual_refund_freezes_original_source_and_finishes_exactly_once(admin):
    order = buy(admin)
    result = prepare(admin, order)
    assert result.status_code == 201, result.text
    row = result.json()
    assert admin.get(BASE).json()["available_credits"] == 0
    assert admin.get(BASE).json()["balance_credits"] == 300
    assert prepare(admin, order, amount=1, credits=0).status_code == 409
    failed = resolve(admin, row, receipt_verified=False)
    assert failed.status_code == 422
    assert resolve(admin, row, confirm_order_id="wrong-order").status_code == 422
    final = resolve(admin, row)
    assert final.status_code == 200, final.text
    assert resolve(admin, row).json() == final.json()
    assert admin.get(BASE).json()["balance_credits"] == 0
    assert admin.get(BASE).json()["reserved_credits"] == 0
    assert prepare(admin, order, amount=1, credits=0).status_code == 422
    assert admin.get(NOTIFY, params=paid_fields(order, money="29.90")).text == "success"
    assert admin.get(BASE).json()["balance_credits"] == 0
    ledger = admin.get(ROOT + "/ledger").json()["items"]
    refunded = [r for r in ledger if r["entry_type"] == "refund"]
    assert len(refunded) == 1 and refunded[0]["purchase_id"] == order["id"]
    invariant(admin)


def test_refund_never_takes_other_order_credits(admin):
    first = buy(admin)
    with admin.app.state.session_factory() as session:
        job, items = seed_job(session, kind="local_edit", count=1)
        services.reserve_image_credits(session, WORKSPACE, job)
        items[0].status = "succeeded"
        services.settle_credits(session, job, 0)
        session.commit()
    second = admin.post(
        BASE + "/purchases",
        headers={"Idempotency-Key": str(uuid4())},
        json={"package_id": "pack_small"},
    ).json()
    assert (
        admin.get(
            NOTIFY, params=paid_fields(second, money="29.90", trade="SECOND-TRADE")
        ).text
        == "success"
    )
    assert prepare(admin, first, credits=300).status_code == 422
    row = prepare(admin, first, credits=295).json()
    assert resolve(admin, row).status_code == 200
    assert admin.get(BASE).json()["balance_credits"] == 300
    invariant(admin)


def test_rejected_refund_releases_frozen_credits(admin):
    order = buy(admin)
    row = prepare(admin, order).json()
    assert resolve(admin, row, status="rejected").status_code == 200
    a = admin.get(BASE).json()
    assert a["balance_credits"] == 300 and a["reserved_credits"] == 0
    assert resolve(admin, row).status_code == 409
    invariant(admin)


def test_expiry_during_refund_keeps_hold_then_releases_expired_lot(admin):
    order = buy(admin)
    row = prepare(admin, order).json()
    with admin.app.state.session_factory() as session:
        lot = session.scalar(
            select(CreditGrantRecord).where(CreditGrantRecord.source_key == order["id"])
        )
        lot.expires_at = aware(lot.created_at) - timedelta(days=1)
        session.commit()
    assert admin.get(BASE).json()["balance_credits"] == 300
    assert resolve(admin, row, status="rejected").status_code == 200
    assert admin.get(BASE).json()["balance_credits"] == 0
    invariant(admin)


def test_membership_refund_pauses_future_grants_and_completion_cancels_order(admin):
    order = buy(admin, "pro_annual", "948.00")
    assert prepare(admin, order, amount=94800, credits=1500).status_code == 422
    row = prepare(
        admin, order, amount=94800, credits=1500, cancel_future_membership=True
    ).json()
    state = admin.get(BASE + "/membership").json()
    assert state["refund_pending"] is True and state["next_grant_at"] is None
    with admin.app.state.session_factory() as session:
        member = session.scalar(select(CreditMembershipRecord))
        later = add_months(member.starts_at, 1) + timedelta(seconds=1)
        refresh(session, WORKSPACE, now=later)
        session.commit()
        assert len(list(session.scalars(select(CreditGrantRecord)))) == 1
    assert resolve(admin, row).status_code == 200
    with admin.app.state.session_factory() as session:
        member = session.scalar(select(CreditMembershipRecord))
        assert member.cancelled_at is not None
        refresh(session, WORKSPACE, now=later)
        session.commit()
        assert len(list(session.scalars(select(CreditGrantRecord)))) == 1
    assert admin.get(BASE + "/membership").json()["plan_id"] is None
    invariant(admin)


def test_support_case_requires_real_job_and_resolution(admin):
    with admin.app.state.session_factory() as session:
        job, _ = seed_job(session, count=1)
        session.commit()
        identifier = job.id
    r = admin.post(
        ROOT + "/cases",
        json={"workspace_id": OTHER, "job_id": identifier, "issue": "客户反馈生成失败"},
    )
    assert r.status_code == 422
    r = admin.post(
        ROOT + "/cases",
        json={
            "workspace_id": WORKSPACE,
            "job_id": identifier,
            "issue": "客户反馈生成失败",
        },
    )
    assert r.status_code == 201, r.text
    url = ROOT + "/cases/" + r.json()["id"]
    assert (
        admin.patch(url, json={"status": "resolved", "resolution": ""}).status_code
        == 422
    )
    assert (
        admin.patch(
            url,
            json={"status": "resolved", "resolution": "已核对失败释放，联系用户重试"},
        ).status_code
        == 200
    )
    assert admin.get(ROOT + "/cases").json()["items"][0]["status"] == "resolved"
    assert admin.get(ROOT + "/audit").json()["pagination"]["total"] == 2


def test_customer_job_list_keeps_provider_details_private(admin):
    with admin.app.state.session_factory() as session:
        job, _ = seed_job(session, count=1)
        job.error_code = "PROVIDER_TIMEOUT"
        job.error_message = "upstream token=never-expose-this-private-value"
        session.commit()
    response = admin.get(ROOT + "/jobs")
    assert response.status_code == 200
    assert "never-expose-this-private-value" not in response.text
    assert response.json()["items"][0]["error_code"] == "PROVIDER_TIMEOUT"
