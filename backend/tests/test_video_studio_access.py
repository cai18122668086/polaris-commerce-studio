from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import Principal
from app.domain import UserStatus
from app.errors import ApiError
from app.main import create_app
from app.models import UserRecord
from app.supertokens_auth import ExternalAuthenticationUnavailable, ExternalIdentity
from app.video_studio_access import VideoStudioDependency, require_video_studio_access
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)

EMAIL = "1474953130@qq.com"
ACCESS = "/api/v1/video-studio/access"


@pytest.mark.parametrize("email", [EMAIL, "  1474953130@QQ.COM  "])
def test_verified_external_identity_allowed_and_not_cached(tmp_path: Path, email: str):
    backend = FakeExternalAuthBackend(identity=verified_identity(email=email))
    with TestClient(create_app(external_settings(tmp_path), backend)) as client:
        response = client.get(ACCESS)
    assert response.status_code == 200
    assert response.json()["allowed"] is True
    assert response.json()["user_id"].startswith("usr_st_")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    assert EMAIL not in response.text


@pytest.mark.parametrize("email", ["ordinary@example.com", "", " "])
def test_other_or_missing_email_cannot_spoof_access(tmp_path: Path, email: str):
    backend = FakeExternalAuthBackend(identity=verified_identity(email=email))
    with TestClient(create_app(external_settings(tmp_path), backend)) as client:
        response = client.get(
            ACCESS + "?email=" + EMAIL + "&allowed=true",
            headers={
                "X-User-Id": "usr_spoofed",
                "X-User-Email": EMAIL,
                "X-Email-Verified": "true",
                "X-Video-Studio-Allowed": "true",
            },
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert EMAIL not in response.text


def test_missing_session_and_unverified_and_unavailable_fail_closed(tmp_path: Path):
    backend = FakeExternalAuthBackend()
    with TestClient(create_app(external_settings(tmp_path), backend)) as client:
        assert (
            client.get(
                ACCESS, headers={"X-User-Id": EMAIL, "X-User-Email": EMAIL}
            ).status_code
            == 401
        )
        backend.identity = ExternalIdentity("unverified", "unverified", EMAIL, False)
        assert client.get(ACCESS).status_code == 403
        backend.authentication_error = ExternalAuthenticationUnavailable("test outage")
        assert client.get(ACCESS).status_code == 503


def test_account_switch_signout_and_suspension_recheck_server(tmp_path: Path):
    backend = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
    with TestClient(create_app(external_settings(tmp_path), backend)) as client:
        allowed = client.get(ACCESS)
        assert allowed.status_code == 200
        backend.identity = verified_identity(
            primary_user_id="other", email="other@example.com"
        )
        assert client.get(ACCESS).status_code == 404
        backend.identity = None
        assert client.get(ACCESS).status_code == 401
        backend.identity = verified_identity(email=EMAIL)
        with cast(FastAPI, client.app).state.session_factory() as session:
            user = session.get(UserRecord, allowed.json()["user_id"])
            user.status = UserStatus.SUSPENDED.value
            session.commit()
        assert client.get(ACCESS).status_code == 403


@pytest.mark.parametrize(
    "principal",
    [
        Principal("missing"),
        Principal("unverified", email=EMAIL, email_verified=False),
        Principal("disabled", email=EMAIL, status=UserStatus.SUSPENDED),
    ],
)
def test_dependency_defensively_rejects_invalid_principals(principal: Principal):
    with pytest.raises(ApiError) as error:
        require_video_studio_access(principal)
    assert error.value.status_code == 404


def test_development_default_is_not_allowlisted(tmp_path: Path):
    settings = external_settings(tmp_path).model_copy(
        update={"auth_mode": "development"}
    )
    with TestClient(create_app(settings)) as client:
        assert client.get(ACCESS).status_code == 404


def test_future_api_can_reuse_same_dependency(tmp_path: Path):
    backend = FakeExternalAuthBackend(
        identity=verified_identity(email="other@example.com")
    )
    app = create_app(external_settings(tmp_path), backend)

    @app.get("/test-video-business")
    def business(principal: VideoStudioDependency):
        return {"user": principal.user_id}

    with TestClient(app) as client:
        assert client.get("/test-video-business").status_code == 404
        backend.identity = verified_identity(email=EMAIL)
        assert client.get("/test-video-business").status_code == 200
