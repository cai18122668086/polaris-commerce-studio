from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select

from app import services
from app.config import Settings
from app.credit_payment_routes import epay_sign, parse_epay_form
from app.errors import ApiError
from app.main import create_app
from app.models import (
    CreditLedgerEntryRecord,
    CreditPurchaseRecord,
    JobItemRecord,
    JobRecord,
    WorkspaceCreditAccountRecord,
    WorkspaceMemberRecord,
    WorkspaceRecord,
)
from tests.test_customer_credit_billing import seed_job

WORKSPACE = "ws_test"
OTHER = "ws_not_in_pilot"
BASE = f"/api/v1/workspaces/{WORKSPACE}/credits"
NOTIFY = "/api/v1/payments/epay/notify"
SECRET = "test-only-merchant-key-0123456789"


@pytest.fixture
def pilot_client(settings):
    settings.workspace_credit_enforcement_enabled = False
    settings.workspace_credit_pilot_ids = [WORKSPACE]
    settings.provider_quota_enabled = False
    settings.credit_payments_enabled = True
    settings.credit_epay_pid = "1001"
    settings.credit_epay_active_key_id = "v1"
    settings.credit_epay_keys = {"v1": SecretStr(SECRET)}
    with TestClient(create_app(settings)) as client:
        with client.app.state.session_factory() as session:
            session.get(WorkspaceCreditAccountRecord, WORKSPACE).balance_credits = 0
            session.add(
                WorkspaceRecord(
                    id=OTHER, name="Non-pilot", created_by_user_id="usr_test"
                )
            )
            session.flush()
            session.add_all(
                [
                    WorkspaceMemberRecord(
                        workspace_id=OTHER,
                        user_id="usr_test",
                        role="owner",
                        status="active",
                    ),
                    WorkspaceCreditAccountRecord(
                        workspace_id=OTHER, balance_credits=0, reserved_credits=0
                    ),
                ]
            )
            session.commit()
        yield client


def purchase(client, key=None):
    response = client.post(
        BASE + "/purchases",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"package_id": "credits_1500"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def paid_fields(order, *, trade="P2026102712345600001", **changes):
    fields = {
        "pid": "1001",
        "out_trade_no": order["id"],
        "trade_no": trade,
        "type": "alipay",
        "name": order["package_name"],
        "money": "99.00",
        "trade_status": "TRADE_SUCCESS",
        "param": order["id"],
    }
    fields.update(changes)
    fields["sign"] = epay_sign(fields, SECRET)
    fields["sign_type"] = "MD5"
    return fields


def balance(client):
    return client.get(BASE).json()["balance_credits"]


def test_checkout_is_signed_and_creating_order_does_not_credit_wallet(pilot_client):
    key = str(uuid4())
    order = purchase(pilot_client, key)
    assert purchase(pilot_client, key) == order
    assert balance(pilot_client) == 0
    fields = dict(parse_qsl(urlsplit(order["checkout_url"]).query))
    assert fields["sign"] == epay_sign(fields, SECRET)
    assert fields["money"] == "99.00"
    assert SECRET not in order["checkout_url"]
    assert order["credits"] == 1500
    detail = pilot_client.get(
        BASE + "/purchases/" + order["id"], params={"trade_status": "TRADE_SUCCESS"}
    ).json()
    assert detail["status"] == "pending"
    assert balance(pilot_client) == 0


def test_only_allowlisted_workspace_can_create_checkout(pilot_client):
    assert pilot_client.get(BASE).json()["enforcement_enabled"] is True
    other = f"/api/v1/workspaces/{OTHER}/credits"
    assert pilot_client.get(other).json()["enforcement_enabled"] is False
    assert pilot_client.get(other + "/packages").json() == {
        "enabled": False,
        "packages": [],
    }
    assert (
        pilot_client.post(
            other + "/purchases",
            headers={"Idempotency-Key": str(uuid4())},
            json={"package_id": "credits_1500"},
        ).status_code
        == 403
    )
    assert services.credit_enforcement_enabled(OTHER) is False


def test_client_cannot_supply_price_or_credit_amount(pilot_client):
    for extra in [{"amount_fen": 1}, {"credits": 999999}, {"workspace_id": OTHER}]:
        response = pilot_client.post(
            BASE + "/purchases",
            headers={"Idempotency-Key": str(uuid4())},
            json={"package_id": "credits_1500", **extra},
        )
        assert response.status_code == 422
    assert balance(pilot_client) == 0


def test_verified_payment_credits_once_and_appears_in_ledger(pilot_client):
    order = purchase(pilot_client)
    fields = paid_fields(order)
    for _ in range(3):
        response = pilot_client.get(NOTIFY, params=fields)
        assert response.status_code == 200, response.text
        assert response.text == "success"
    assert balance(pilot_client) == 1500
    assert (
        pilot_client.get(BASE + "/purchases/" + order["id"]).json()["checkout_url"]
        is None
    )
    ledger = pilot_client.get(BASE + "/ledger").json()["items"]
    assert len(ledger) == 1
    assert ledger[0]["entry_type"] == "purchase"
    assert ledger[0]["title"] == order["package_name"]
    assert ledger[0]["delta_balance_credits"] == 1500


@pytest.mark.parametrize(
    "changes",
    [
        {"money": "0.01"},
        {"pid": "1002"},
        {"param": "other-order"},
        {"trade_status": "WAIT_BUYER_PAY"},
        {"name": "another product"},
    ],
)
def test_even_signed_mismatched_payment_is_rejected(pilot_client, changes):
    fields = paid_fields(purchase(pilot_client), **changes)
    response = pilot_client.get(NOTIFY, params=fields)
    assert response.status_code == 400, response.text
    assert balance(pilot_client) == 0


def test_bad_signature_and_duplicate_form_fields_are_rejected(pilot_client):
    fields = paid_fields(purchase(pilot_client))
    fields["money"] = "0.01"
    assert pilot_client.get(NOTIFY, params=fields).status_code == 400
    valid = paid_fields(purchase(pilot_client))
    body = urlencode(valid) + "&money=0.01"
    assert (
        pilot_client.post(
            NOTIFY,
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).status_code
        == 400
    )
    assert (
        pilot_client.post(NOTIFY, params={"money": "99.00"}, data=valid).status_code
        == 400
    )
    assert balance(pilot_client) == 0


def test_key_rotation_and_pilot_disable_do_not_lose_paid_order(pilot_client):
    order = purchase(pilot_client)
    settings = pilot_client.app.state.settings
    settings.credit_epay_active_key_id = "v2"
    settings.credit_epay_keys["v2"] = SecretStr("rotated-test-key-0123456789")
    settings.credit_payments_enabled = False
    services.set_credit_pilot_workspaces([])
    assert (
        pilot_client.post(
            BASE + "/purchases",
            headers={"Idempotency-Key": str(uuid4())},
            json={"package_id": "credits_1500"},
        ).status_code
        == 403
    )
    assert pilot_client.get(NOTIFY, params=paid_fields(order)).text == "success"
    assert balance(pilot_client) == 1500


def test_concurrent_duplicate_payment_callbacks_are_idempotent(pilot_client):
    fields = paid_fields(purchase(pilot_client))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: pilot_client.get(NOTIFY, params=fields), range(2))
        )
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    assert balance(pilot_client) == 1500
    with pilot_client.app.state.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(CreditLedgerEntryRecord))
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(CreditPurchaseRecord)
                .where(CreditPurchaseRecord.status == "paid")
            )
            == 1
        )


def test_paid_credits_fund_real_billing_and_rollback_finishes_existing_hold(
    pilot_client,
):
    assert (
        pilot_client.get(NOTIFY, params=paid_fields(purchase(pilot_client))).text
        == "success"
    )
    with pilot_client.app.state.session_factory() as session:
        job, items = seed_job(session, kind="local_edit", count=1)
        reservation = services.reserve_image_credits(session, WORKSPACE, job)
        assert reservation.reserved_credits == 5
        items[0].status = "succeeded"
        session.flush()
        services.set_credit_pilot_workspaces([])
        services.settle_credits(session, job, 0)
        session.commit()
        assert job.actual_credits == 5
    assert balance(pilot_client) == 1495
    assert pilot_client.get(BASE).json()["reserved_credits"] == 0


@pytest.mark.parametrize("value", [["*"], ["owner@example.test"], ["ws_a", "*"]])
def test_pilot_configuration_rejects_wildcards_and_email_identifiers(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, workspace_credit_pilot_ids=value)


@pytest.mark.parametrize(
    "raw", [b"money=1&money=2", b"money=%ZZ", b"money=%ff", b"x[]=1"]
)
def test_strict_callback_parser_rejects_ambiguous_form_data(raw):
    with pytest.raises(ApiError):
        parse_epay_form(raw)


def test_valid_post_notification_and_one_trade_cannot_credit_two_orders(pilot_client):
    first = purchase(pilot_client)
    assert pilot_client.post(NOTIFY, data=paid_fields(first)).text == "success"
    second = purchase(pilot_client)
    response = pilot_client.post(NOTIFY, data=paid_fields(second))
    assert response.status_code == 409
    assert balance(pilot_client) == 1500
    assert (
        pilot_client.get(BASE + "/purchases/" + second["id"]).json()["status"]
        == "pending"
    )


def test_failed_ledger_write_rolls_back_paid_status_and_wallet(
    pilot_client, monkeypatch
):
    from sqlalchemy.orm import Session

    order = purchase(pilot_client)
    original_flush = Session.flush

    def fail_ledger_write(self, *args, **kwargs):
        if any(
            isinstance(row, CreditLedgerEntryRecord) and row.entry_type == "purchase"
            for row in self.new
        ):
            raise RuntimeError("simulated ledger write failure")
        return original_flush(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Session, "flush", fail_ledger_write)
        with pytest.raises(RuntimeError, match="simulated ledger write failure"):
            pilot_client.get(NOTIFY, params=paid_fields(order))
    assert balance(pilot_client) == 0
    assert (
        pilot_client.get(BASE + "/purchases/" + order["id"]).json()["status"]
        == "pending"
    )
    assert pilot_client.get(NOTIFY, params=paid_fields(order)).text == "success"
    assert balance(pilot_client) == 1500


def test_legacy_tracking_reservation_is_not_charged_after_entering_pilot(pilot_client):
    services.set_quota_enabled(True)
    services.set_credit_pilot_workspaces([])
    with pilot_client.app.state.session_factory() as session:
        job, items = seed_job(session, kind="local_edit", count=1)
        reservation = services.reserve_image_credits(session, WORKSPACE, job, 2)
        assert reservation.pricing_snapshot is None
        assert (
            session.get(WorkspaceCreditAccountRecord, WORKSPACE).reserved_credits == 0
        )
        services.set_credit_pilot_workspaces([WORKSPACE])
        items[0].status = "succeeded"
        services.settle_credits(session, job, 0)
        session.commit()
        assert session.get(WorkspaceCreditAccountRecord, WORKSPACE).balance_credits == 0


def test_disabling_pilot_still_releases_previously_held_credits(pilot_client):
    assert (
        pilot_client.get(NOTIFY, params=paid_fields(purchase(pilot_client))).text
        == "success"
    )
    with pilot_client.app.state.session_factory() as session:
        job, _ = seed_job(session, count=6)
        services.reserve_image_credits(session, WORKSPACE, job)
        assert (
            session.get(WorkspaceCreditAccountRecord, WORKSPACE).reserved_credits == 90
        )
        services.set_credit_pilot_workspaces([])
        services.release_credits(session, job)
        session.commit()
        assert (
            session.get(WorkspaceCreditAccountRecord, WORKSPACE).reserved_credits == 0
        )
    assert balance(pilot_client) == 1500


def test_signing_matches_independent_utf8_and_zero_vector():
    parameters = {
        "pid": "1001",
        "name": "测试 商品",
        "money": "99.00",
        "param": "0",
        "empty": "",
        "sign": "ignored",
        "sign_type": "MD5",
    }
    assert epay_sign(parameters, SECRET) == "6c895ac3467280eba9833a475740e07b"


@pytest.mark.parametrize("quota", [False, True])
def test_nonpilot_zero_balance_keeps_legacy_generation_accounting(pilot_client, quota):
    services.set_quota_enabled(quota)
    with pilot_client.app.state.session_factory() as session:
        job = JobRecord(
            id="job_" + uuid4().hex,
            workspace_id=OTHER,
            type="local_edit",
            status="queued",
            stage="queued",
            expected_item_count=1,
            configuration={"settings": {}},
        )
        session.add(job)
        session.flush()
        session.add(
            JobItemRecord(
                id="item_" + uuid4().hex,
                workspace_id=OTHER,
                job_id=job.id,
                item_key="image-0",
                ordinal=0,
                status="pending",
                stage="queued",
            )
        )
        session.flush()
        reservation = services.reserve_image_credits(session, OTHER, job, 2)
        if quota:
            assert reservation is not None
            assert reservation.pricing_snapshot is None
        else:
            assert reservation is None
        services.settle_credits(session, job, 0)
        session.commit()
        account = session.get(WorkspaceCreditAccountRecord, OTHER)
        assert account.balance_credits == account.reserved_credits == 0


def test_nonpilot_quote_keeps_original_estimate_without_enabling_balance_gate(
    pilot_client,
):
    from tests.test_api import local_edit_payload

    payload = local_edit_payload("asset_source", "asset_mask")
    pilot = pilot_client.post(BASE + "/quote", json=payload)
    ordinary = pilot_client.post(
        f"/api/v1/workspaces/{OTHER}/credits/quote", json=payload
    )
    assert pilot.status_code == ordinary.status_code == 200
    assert pilot.json()["estimated_credits"] == 5
    assert pilot.json()["sufficient"] is False
    assert ordinary.json()["estimated_credits"] == 2
    assert ordinary.json()["sufficient"] is True
