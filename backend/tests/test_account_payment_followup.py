from datetime import timedelta
from urllib.parse import parse_qsl
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app import credit_payment_routes as routes
from app.credit_memberships import aware, refresh
from app.models import (
    CreditGrantRecord,
    CreditMembershipRecord,
)
from tests.test_credit_payments import (
    BASE,
    NOTIFY,
    OTHER,
    WORKSPACE,
    balance,
    paid_fields,
)
from tests.test_credit_payments import pilot_client as pilot_client  # noqa: F401


def create(client, package_id):
    r = client.post(
        BASE + "/purchases",
        json={"package_id": package_id},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert r.status_code == 201, r.text
    return r.json()


def gateway_response(order, status=1, **changes):
    data = {
        "code": 1,
        "status": status,
        "pid": "1001",
        "out_trade_no": order["id"],
        "trade_no": "P" + uuid4().hex,
        "type": "wxpay",
        "name": order["package_name"],
        "money": f"{order['amount_fen'] / 100:.2f}",
        "param": order["id"],
    }
    return {**data, **changes}


HTTPClient = httpx.Client


def mock_gateway(monkeypatch, payload):
    def handle(request):
        assert str(request.url) == "https://pay.tengliapi.xyz/api.php"
        assert request.method == "POST"
        data = dict(parse_qsl(request.content.decode()))
        assert data["key"]
        assert "key=" not in str(request.url)
        assert data["act"] == "order"
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        routes.httpx,
        "Client",
        lambda **kwargs: HTTPClient(transport=httpx.MockTransport(handle), **kwargs),
    )


def test_account_catalog_restores_three_original_packs(pilot_client):
    catalog = pilot_client.get(BASE + "/packages?include_memberships=true").json()
    packs = [p for p in catalog["packages"] if p["kind"] == "pack"]
    assert [
        (p["id"], p["amount_fen"], p["credits"], p["validity_months"]) for p in packs
    ] == [
        ("pack_small", 2990, 300, 12),
        ("pack_medium", 9900, 1100, 12),
        ("pack_large", 29900, 3600, 12),
    ]
    assert len([p for p in catalog["packages"] if p["kind"] == "membership"]) == 6
    # Pack-only clients also see all three offers; old order terms stay frozen.
    packs_only = pilot_client.get(BASE + "/packages").json()["packages"]
    assert [p["id"] for p in packs_only] == ["pack_small", "pack_medium", "pack_large"]


@pytest.mark.parametrize(
    "product,credits",
    [("pack_small", 300), ("pack_medium", 1100), ("pack_large", 3600)],
)
def test_new_pack_callback_replay_and_twelve_month_expiry(
    pilot_client, product, credits
):
    order = create(pilot_client, product)
    fields = paid_fields(order, money=f"{order['amount_fen'] / 100:.2f}")
    for _ in range(2):
        assert pilot_client.get(NOTIFY, params=fields).status_code == 200
        assert balance(pilot_client) == credits
    with pilot_client.app.state.session_factory() as session:
        lot = session.scalar(
            select(CreditGrantRecord).where(CreditGrantRecord.source_key == order["id"])
        )
        assert lot.expires_at is not None
        anchor = aware(lot.expires_at)
        wallet = refresh(session, WORKSPACE, now=anchor - timedelta(seconds=1))
        assert wallet.balance_credits == credits
        wallet = refresh(session, WORKSPACE, now=anchor)
        assert wallet.balance_credits == 0


@pytest.mark.parametrize(
    "product,credits",
    [("pack_medium", 1100), ("pro_monthly", 1500), ("pro_annual", 1500)],
)
def test_server_query_recovers_paid_order_once_without_callback(
    pilot_client, monkeypatch, product, credits
):
    order = create(pilot_client, product)
    payload = gateway_response(order)
    mock_gateway(monkeypatch, payload)
    endpoint = BASE + "/purchases/" + order["id"] + "/reconcile"
    for _ in range(2):
        r = pilot_client.post(endpoint)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "paid"
        assert r.json()["checkout_url"] is None
        assert balance(pilot_client) == credits
    # A delayed legitimate callback still uses the same atomic fulfillment.
    fields = paid_fields(
        order, trade=payload["trade_no"], type="wxpay", money=payload["money"]
    )
    assert pilot_client.get(NOTIFY, params=fields).status_code == 200
    assert balance(pilot_client) == credits
    with pilot_client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CreditGrantRecord)) == 1
        assert session.scalar(
            select(func.count()).select_from(CreditMembershipRecord)
        ) == (product != "pack_medium")


@pytest.mark.parametrize(
    "changes",
    [
        {"pid": "1002"},
        {"out_trade_no": "pay_different"},
        {"money": "0.01"},
        {"name": "different"},
        {"param": "pay_different"},
        {"trade_no": ""},
        {"status": True},
        {"status": 2},
        {"code": True},
    ],
)
def test_query_must_match_verified_merchant_order_before_credit(
    pilot_client, monkeypatch, changes
):
    order = create(pilot_client, "pro_monthly")
    mock_gateway(monkeypatch, gateway_response(order, **changes))
    r = pilot_client.post(BASE + "/purchases/" + order["id"] + "/reconcile")
    assert r.status_code in {400, 502}
    assert balance(pilot_client) == 0
    assert (
        pilot_client.get(BASE + "/purchases/" + order["id"]).json()["status"]
        == "pending"
    )


def test_unconfirmed_payment_query_returns_pending_and_never_credits(
    pilot_client, monkeypatch
):
    order = create(pilot_client, "pro_monthly")
    mock_gateway(monkeypatch, gateway_response(order, status=0))
    r = pilot_client.post(BASE + "/purchases/" + order["id"] + "/reconcile")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    assert balance(pilot_client) == 0


def test_other_workspace_cannot_query_or_credit_order(pilot_client, monkeypatch):
    order = create(pilot_client, "pro_monthly")

    def forbidden(*args, **kwargs):
        pytest.fail("Must check workspace ownership before contacting gateway")

    monkeypatch.setattr(routes, "_query_gateway_order", forbidden)
    r = pilot_client.post(
        f"/api/v1/workspaces/{OTHER}/credits/purchases/{order['id']}/reconcile"
    )
    assert r.status_code == 404
    assert balance(pilot_client) == 0


def test_query_timeout_never_leaks_credentials_or_credits(pilot_client, monkeypatch):
    order = create(pilot_client, "pro_monthly")

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("secret-key-must-not-appear")

    monkeypatch.setattr(
        routes.httpx,
        "Client",
        lambda **kwargs: HTTPClient(transport=httpx.MockTransport(timeout), **kwargs),
    )
    r = pilot_client.post(BASE + "/purchases/" + order["id"] + "/reconcile")
    assert r.status_code == 502
    assert "secret-key-must-not-appear" not in r.text
    assert balance(pilot_client) == 0
