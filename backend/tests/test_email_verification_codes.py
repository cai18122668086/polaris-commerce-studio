import asyncio
from types import SimpleNamespace

import fakeredis.aioredis

from app.config import Settings
from app.email_verification_codes import (
    MAX_ATTEMPTS,
    VerificationCodeStore,
    override_verification_apis,
)
from app.supertokens_auth import _override_verification_email_service


def make_store():
    store = VerificationCodeStore(
        Settings(_env_file=None, access_url_secret="test-secret")
    )
    store.client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return store


def test_code_is_scoped_single_use_expiring_and_attempt_limited():
    async def scenario():
        store = make_store()
        assert await store.reserve("tenant", "user")
        assert not await store.reserve("tenant", "user")
        code = await store.issue("tenant", "user", "real-sdk-token")
        assert len(code) == 6 and code.isdigit()
        assert await store.consume("other", "user", code) is None
        assert await store.consume("tenant", "other", code) is None
        results = await asyncio.gather(
            *(store.consume("tenant", "user", code) for _ in range(8))
        )
        assert results.count("real-sdk-token") == 1
        code = await store.issue("tenant", "user", "new-sdk-token")
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(MAX_ATTEMPTS):
            assert await store.consume("tenant", "user", wrong) is None
        assert await store.consume("tenant", "user", code) is None
        await store.issue("tenant", "user", "expired")
        await store.client.expire(store.key("tenant", "user"), 0)
        assert await store.consume("tenant", "user", code) is None
        await store.client.aclose()

    asyncio.run(scenario())


def test_otp_uses_the_existing_sdk_verification_and_session(monkeypatch):
    async def scenario():
        store = make_store()
        calls = []

        async def verify(*args):
            calls.append(args)
            return "verified"

        original = SimpleNamespace(
            email_verify_post=verify, generate_email_verify_token_post=verify
        )
        api = override_verification_apis(original, store, True)
        session = SimpleNamespace(
            get_tenant_id=lambda: "public",
            get_recipe_user_id=lambda _: SimpleNamespace(
                get_as_string=lambda: "recipe-user"
            ),
        )
        code = await store.issue("public", "recipe-user", "sdk-token")
        assert (
            await api.email_verify_post(code, session, "public", "options", {})
            == "verified"
        )
        assert calls[0][0] == "sdk-token" and calls[0][1] is session
        assert (
            await api.email_verify_post(code, session, "public", "options", {})
        ).__class__.__name__ == "EmailVerifyPostInvalidTokenError"
        assert (
            await api.email_verify_post(
                "existing-link-token", session, "public", "options", {}
            )
            == "verified"
        )
        assert calls[-1][0] == "existing-link-token"
        await store.client.aclose()

    asyncio.run(scenario())


def test_verification_email_contains_code_without_link(monkeypatch):
    async def scenario():
        store = make_store()
        monkeypatch.setattr(
            "app.email_verification_codes.secrets.randbelow", lambda _: 42
        )
        service = _override_verification_email_service(
            SimpleNamespace(), "极光商绘", store
        )
        template = SimpleNamespace(
            tenant_id="public",
            email_verify_link="https://example.com/auth/verify-email?token=secret-token",
            user=SimpleNamespace(
                email="test@example.com",
                recipe_user_id=SimpleNamespace(get_as_string=lambda: "user"),
            ),
        )
        content = await service.get_content(template, {})
        assert "000042" in content.body and "10 分钟" in content.body
        assert "secret-token" not in content.body and "href=" not in content.body
        assert await store.consume("public", "user", "000042") == "secret-token"
        await store.client.aclose()

    asyncio.run(scenario())
