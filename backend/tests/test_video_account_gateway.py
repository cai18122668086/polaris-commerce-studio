import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from video_account_gateway import (  # noqa: E402
    AUTH_ORIGIN,
    LOCAL_ORIGIN,
    RealAccountGateway,
    local_cookie,
)

from app.supertokens_auth import (  # noqa: E402
    ExternalAuthenticationError,
    ExternalEmailNotVerifiedError,
)


def test_auth_relay_is_same_origin_bounded_and_keeps_cookie_security():
    requests = []

    def upstream(request):
        requests.append(request)
        assert request.url.host == "www.tengliapi.xyz"
        assert "x-user-id" not in request.headers
        assert request.headers["origin"] == AUTH_ORIGIN
        return httpx.Response(
            200,
            json={"status": "OK"},
            headers={
                "set-cookie": (
                    "sAccessToken=fixture; Domain=.tengliapi.xyz; Secure; "
                    "HttpOnly; SameSite=Lax; Path=/"
                ),
            },
        )

    app = FastAPI()
    RealAccountGateway(httpx.MockTransport(upstream)).install_middleware(app)
    with TestClient(app) as client:
        assert client.post("/api/auth/signin", json={}).status_code == 403
        assert (
            client.post(
                "/api/auth/signin", headers={"Origin": "https://other.invalid"}, json={}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/auth/admin", headers={"Origin": LOCAL_ORIGIN}, json={}
            ).status_code
            == 404
        )
        result = client.post(
            "/api/auth/signin",
            headers={"Origin": LOCAL_ORIGIN, "X-User-Id": "forged"},
            json={"formFields": []},
        )
        assert result.status_code == 200
        cookie = result.headers["set-cookie"]
        assert "Domain=" not in cookie and "Secure" in cookie and "HttpOnly" in cookie
        assert len(requests) == 1


def test_cookie_narrows_domain_without_changing_security():
    assert (
        local_cookie(
            "a=b; Secure; HttpOnly; Domain=.example.com; Path=/api/auth; SameSite=None"
        )
        == "a=b; Secure; HttpOnly; Path=/api/auth; SameSite=None"
    )


@pytest.mark.parametrize(
    "status,verified,error",
    [
        (401, True, ExternalAuthenticationError),
        (200, False, ExternalEmailNotVerifiedError),
    ],
)
def test_real_identity_never_comes_from_browser_headers(status, verified, error):
    import asyncio

    def upstream(request):
        return httpx.Response(
            status,
            json={
                "id": "real_user",
                "email": "1474953130@qq.com",
                "email_verified": verified,
                "status": "active",
            },
        )

    request = Request(
        {
            "type": "http",
            "headers": [
                (b"cookie", b"sAccessToken=fixture"),
                (b"x-user-email", b"1474953130@qq.com"),
            ],
        }
    )
    with pytest.raises(error):
        asyncio.run(
            RealAccountGateway(httpx.MockTransport(upstream)).authenticate(request)
        )
