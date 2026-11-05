"""Loopback-only acceptance with real production authentication and isolated data.

No production deployment, Core key, fake principal, or password persistence.
The owned HTTPS /me endpoint authenticates every business request. Auth cookies
remain HttpOnly/Secure as issued; a Domain attribute is narrowed to localhost.
This is an acceptance gateway, not a new production authentication provider.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import Request, Response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.supertokens_auth import (
    ExternalAuthenticationError,
    ExternalAuthenticationUnavailable,
    ExternalEmailNotVerifiedError,
    ExternalIdentity,
)

AUTH_ORIGIN = "https://www.tengliapi.xyz"
LOCAL_ORIGIN = "http://localhost:3003"
AUTH_PATHS = {
    "signin",
    "signout",
    "session/refresh",
    "user/email/verify",
    "user/email/verify/token",
    "jwt/jwks.json",
}


def forwarded_headers(request):
    # Never trust caller-supplied identity or pass arbitrary application headers.
    selected = {
        name: request.headers[name]
        for name in [
            "cookie",
            "authorization",
            "anti-csrf",
            "rid",
            "st-auth-mode",
            "fdi-version",
            "content-type",
        ]
        if name in request.headers
    }
    selected["origin"] = AUTH_ORIGIN
    return selected


def local_cookie(value):
    # Narrow cookie scope, keeping Secure, HttpOnly, SameSite, Path and expiry.
    return ";".join(
        part
        for part in value.split(";")
        if not part.strip().lower().startswith("domain=")
    )


class RealAccountGateway:
    def __init__(self, transport=None, audit_path=None):
        self.transport = transport
        self.ready = False
        self.audit_path = audit_path

    def audit(self, **event):
        if self.audit_path:
            with self.audit_path.open("a", encoding="utf-8") as output:
                output.write(
                    json.dumps({"at": datetime.now(UTC).isoformat(), **event}) + "\n"
                )

    def initialize(self):
        self.ready = True

    def is_ready(self):
        return self.ready

    def cors_headers(self):
        return ["anti-csrf", "rid", "st-auth-mode", "fdi-version"]

    async def authenticate(self, request):
        if not request.headers.get("cookie") and not request.headers.get(
            "authorization"
        ):
            raise ExternalAuthenticationError("No session")
        try:
            async with httpx.AsyncClient(
                timeout=15, transport=self.transport, follow_redirects=False
            ) as client:
                result = await client.get(
                    AUTH_ORIGIN + "/api/v1/me", headers=forwarded_headers(request)
                )
            if result.status_code == 401:
                raise ExternalAuthenticationError("Session rejected")
            if result.status_code == 403:
                code = result.json().get("error", {}).get("code")
                if code == "EMAIL_NOT_VERIFIED":
                    raise ExternalEmailNotVerifiedError("Verification required")
                raise ExternalAuthenticationError("Account rejected")
            if result.status_code != 200:
                raise ExternalAuthenticationUnavailable("Identity service unavailable")
            user = result.json()
            if (
                not isinstance(user.get("id"), str)
                or not user["id"]
                or len(user["id"]) > 120
                or not isinstance(user.get("email"), str)
                or user.get("status") != "active"
            ):
                raise ExternalAuthenticationError("Invalid identity response")
            if user.get("email_verified") is not True:
                raise ExternalEmailNotVerifiedError("Verification required")
            self.audit(
                kind="identity_verified", remote_user_id=user["id"], email_verified=True
            )
            return ExternalIdentity(
                primary_user_id=user["id"],
                recipe_user_id=user["id"],
                email=user["email"],
                email_verified=True,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ExternalAuthenticationUnavailable(
                "Identity service unavailable"
            ) from None

    def install_middleware(self, application):
        @application.api_route("/api/auth/{path:path}", methods=["GET", "POST"])
        async def relay_auth(path: str, request: Request):
            if path not in AUTH_PATHS:
                return Response(status_code=404)
            # Protect the local credential relay from cross-site form/fetch use.
            origin = request.headers.get("origin")
            if (origin and origin != LOCAL_ORIGIN) or (
                request.method == "POST" and origin != LOCAL_ORIGIN
            ):
                return Response(status_code=403)
            size, chunks = 0, []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 65536:
                    return Response(status_code=413)
                chunks.append(chunk)
            try:
                async with httpx.AsyncClient(
                    timeout=30, transport=self.transport, follow_redirects=False
                ) as client:
                    result = await client.request(
                        request.method,
                        AUTH_ORIGIN + "/api/auth/" + path,
                        params=request.query_params,
                        headers=forwarded_headers(request),
                        content=b"".join(chunks),
                    )
            except httpx.HTTPError:
                return Response(status_code=503)
            self.audit(
                kind="auth_route",
                path=path,
                method=request.method,
                upstream_status=result.status_code,
            )
            response = Response(
                result.content,
                status_code=result.status_code,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Type": result.headers.get(
                        "content-type", "application/json"
                    ),
                },
            )
            for name in [
                "front-token",
                "anti-csrf",
                "st-access-token",
                "st-refresh-token",
                "fdi-version",
            ]:
                if name in result.headers:
                    response.headers[name] = result.headers[name]
            for cookie in result.headers.get_list("set-cookie"):
                response.headers.append("set-cookie", local_cookie(cookie))
            return response


def create_acceptance_app(folder):
    from app.config import Settings
    from app.main import create_app

    real = Settings(_env_file=ROOT / "backend/.env")
    settings = real.model_copy(
        update={
            "environment": "development",
            "auth_mode": "external",
            "database_url": "sqlite:///"
            + (folder / "account-acceptance.db").as_posix(),
            "auto_create_schema": True,
            "auto_process_jobs": False,
            "storage_backend": "local",
            "storage_dir": folder / "storage",
            "video_media_dir": folder / "media",
            "task_dispatcher": "inline",
            "task_runner": "mock",
            "workspace_credit_enforcement_enabled": False,
            "cors_origins": [LOCAL_ORIGIN],
        }
    )
    return create_app(
        settings, RealAccountGateway(audit_path=folder / "auth-audit.jsonl")
    )


if __name__ == "__main__":
    import uvicorn

    folder = ROOT / "outputs/video-studio/real-account-20261105"
    folder.mkdir(parents=True, exist_ok=True)
    uvicorn.run(
        create_acceptance_app(folder),
        host="127.0.0.1",
        port=8013,
        log_level="warning",
        access_log=False,
    )
