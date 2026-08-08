from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from threading import Lock
from typing import Any, Protocol, runtime_checkable

from fastapi import FastAPI, Request

from .config import Settings

SUPPORTED_SUPERTOKENS_PYTHON_VERSION = "0.31.3"


@dataclass(frozen=True)
class ExternalIdentity:
    primary_user_id: str
    recipe_user_id: str
    email: str
    email_verified: bool


class ExternalAuthenticationError(RuntimeError):
    """The request did not contain a valid SuperTokens session."""


class ExternalAuthenticationUnavailable(RuntimeError):
    """The configured authentication service could not complete verification."""


class ExternalEmailNotVerifiedError(RuntimeError):
    """The session is valid, but its email-verification claim is false."""


@runtime_checkable
class ExternalAuthBackend(Protocol):
    def initialize(self) -> None: ...

    def install_middleware(self, application: FastAPI) -> None: ...

    def cors_headers(self) -> list[str]: ...

    def is_ready(self) -> bool: ...

    async def authenticate(self, request: Request) -> ExternalIdentity: ...


_INITIALIZATION_LOCK = Lock()
_INITIALIZATION_FINGERPRINT: tuple[object, ...] | None = None


class SuperTokensAuthAdapter:
    """Small, test-replaceable adapter around supertokens-python 0.31.3."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._initialized = False
        self._verify_session: Any = None
        self._get_user: Any = None
        self._middleware: Any = None
        self._cors_headers: list[str] = []

    def _fingerprint(self) -> tuple[object, ...]:
        return (
            self.settings.supertokens_connection_uri,
            self.settings.supertokens_api_key.get_secret_value(),
            self.settings.supertokens_api_domain,
            self.settings.supertokens_website_domain,
            self.settings.supertokens_api_base_path,
            self.settings.supertokens_website_base_path,
            self.settings.supertokens_cookie_secure,
            self.settings.supertokens_cookie_same_site,
            self.settings.auth_smtp_host,
            self.settings.auth_smtp_port,
            self.settings.auth_smtp_username,
            self.settings.auth_smtp_password.get_secret_value(),
            self.settings.auth_smtp_secure,
            self.settings.auth_email_from_name,
            self.settings.auth_email_from_address,
        )

    def initialize(self) -> None:
        global _INITIALIZATION_FINGERPRINT

        if self._initialized:
            return
        try:
            installed_version = version("supertokens-python")
        except PackageNotFoundError as exc:
            raise RuntimeError(
                "external authentication requires supertokens-python==0.31.3"
            ) from exc
        if installed_version != SUPPORTED_SUPERTOKENS_PYTHON_VERSION:
            raise RuntimeError(
                "unsupported supertokens-python version: "
                f"expected {SUPPORTED_SUPERTOKENS_PYTHON_VERSION}, "
                f"found {installed_version}"
            )

        from supertokens_python import (
            InputAppInfo,
            SupertokensConfig,
            get_all_cors_headers,
        )
        from supertokens_python import (
            init as supertokens_init,
        )
        from supertokens_python.asyncio import get_user
        from supertokens_python.framework.fastapi import get_middleware
        from supertokens_python.recipe import emailpassword, emailverification, session
        from supertokens_python.recipe.session.framework.fastapi import verify_session

        password_email_delivery = None
        verification_email_delivery = None
        if self.settings.auth_smtp_host:
            from supertokens_python.ingredients.emaildelivery.types import (
                SMTPSettings,
                SMTPSettingsFrom,
            )
            emailpassword_smtp = import_module(
                "supertokens_python.recipe.emailpassword.emaildelivery.services.smtp"
            )
            emailverification_smtp = import_module(
                "supertokens_python.recipe.emailverification.emaildelivery.services.smtp"
            )

            smtp_settings = SMTPSettings(
                host=self.settings.auth_smtp_host,
                port=self.settings.auth_smtp_port,
                username=self.settings.auth_smtp_username,
                password=self.settings.auth_smtp_password.get_secret_value(),
                secure=self.settings.auth_smtp_secure,
                from_=SMTPSettingsFrom(
                    name=self.settings.auth_email_from_name,
                    email=self.settings.auth_email_from_address,
                ),
            )
            password_email_delivery = emailpassword.EmailDeliveryConfig(
                service=emailpassword_smtp.SMTPService(smtp_settings)
            )
            verification_email_delivery = emailverification.EmailDeliveryConfig(
                service=emailverification_smtp.SMTPService(smtp_settings)
            )

        fingerprint = self._fingerprint()
        with _INITIALIZATION_LOCK:
            if _INITIALIZATION_FINGERPRINT is None:
                api_key = self.settings.supertokens_api_key.get_secret_value() or None
                supertokens_init(
                    app_info=InputAppInfo(
                        app_name=self.settings.app_name,
                        api_domain=self.settings.supertokens_api_domain,
                        website_domain=self.settings.supertokens_website_domain,
                        api_base_path=self.settings.supertokens_api_base_path,
                        website_base_path=self.settings.supertokens_website_base_path,
                    ),
                    framework="fastapi",
                    supertokens_config=SupertokensConfig(
                        connection_uri=self.settings.supertokens_connection_uri,
                        api_key=api_key,
                    ),
                    recipe_list=[
                        emailpassword.init(email_delivery=password_email_delivery),
                        emailverification.init(
                            "REQUIRED", email_delivery=verification_email_delivery
                        ),
                        session.init(
                            cookie_secure=self.settings.supertokens_cookie_secure,
                            cookie_same_site=self.settings.supertokens_cookie_same_site,
                            anti_csrf="VIA_TOKEN",
                            get_token_transfer_method=lambda *_args: "cookie",
                        ),
                    ],
                    telemetry=False,
                )
                _INITIALIZATION_FINGERPRINT = fingerprint
            elif fingerprint != _INITIALIZATION_FINGERPRINT:
                raise RuntimeError(
                    "SuperTokens was already initialized with different settings"
                )

        self._verify_session = verify_session(session_required=True)
        self._get_user = get_user
        self._middleware = get_middleware()
        self._cors_headers = list(get_all_cors_headers())
        self._initialized = True

    def install_middleware(self, application: FastAPI) -> None:
        if not self._initialized or self._middleware is None:
            raise RuntimeError("SuperTokens adapter must be initialized first")
        application.add_middleware(self._middleware)

    def cors_headers(self) -> list[str]:
        return list(self._cors_headers)

    def is_ready(self) -> bool:
        return self._initialized

    async def authenticate(self, request: Request) -> ExternalIdentity:
        if (
            not self._initialized
            or self._verify_session is None
            or self._get_user is None
        ):
            raise ExternalAuthenticationUnavailable(
                "SuperTokens adapter is not initialized"
            )

        from supertokens_python.exceptions import GeneralError
        from supertokens_python.recipe.session.exceptions import (
            InvalidClaimsError,
            SuperTokensSessionError,
        )

        try:
            session_container = await self._verify_session(request)
            if session_container is None:
                raise ExternalAuthenticationError("session is required")
            primary_user_id = session_container.get_user_id()
            recipe_user_id = session_container.get_recipe_user_id().get_as_string()
            supertokens_user = await self._get_user(primary_user_id)
        except InvalidClaimsError as exc:
            if any(error.id_ == "st-ev" for error in exc.payload):
                raise ExternalEmailNotVerifiedError(
                    "email verification is required"
                ) from exc
            raise ExternalAuthenticationError("session claims are invalid") from exc
        except SuperTokensSessionError as exc:
            raise ExternalAuthenticationError("invalid or expired session") from exc
        except GeneralError as exc:
            raise ExternalAuthenticationUnavailable(
                "SuperTokens Core is unavailable"
            ) from exc

        if supertokens_user is None:
            raise ExternalAuthenticationError("session user no longer exists")

        login_method = next(
            (
                method
                for method in supertokens_user.login_methods
                if method.recipe_user_id.get_as_string() == recipe_user_id
            ),
            None,
        )
        if login_method is None or not login_method.email:
            raise ExternalAuthenticationError(
                "the authenticated login method has no email address"
            )

        return ExternalIdentity(
            primary_user_id=primary_user_id,
            recipe_user_id=recipe_user_id,
            email=login_method.email,
            email_verified=bool(login_method.verified),
        )
