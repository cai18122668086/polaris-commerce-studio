"""Session-bound, short-lived email codes over the existing SuperTokens flow."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from redis.asyncio import Redis

from .config import Settings

TTL = 600
COOLDOWN = 60
MAX_ATTEMPTS = 5

# Checking and consuming are one operation across all API processes. A wrong
# code consumes an attempt, and a correct code can only be redeemed once.
CONSUME = """
local value = redis.call('HGET', KEYS[1], 'digest')
if not value then return false end
if value ~= ARGV[1] then
  local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
  if attempts >= tonumber(ARGV[2]) then redis.call('DEL', KEYS[1]) end
  return false
end
local token = redis.call('HGET', KEYS[1], 'token')
redis.call('DEL', KEYS[1])
return token
"""


class VerificationCodeStore:
    def __init__(self, settings: Settings) -> None:
        self.client = Redis.from_url(
            settings.celery_broker_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        self.secret = settings.access_url_secret.encode()

    def key(self, tenant: str, user: str) -> str:
        scope = hashlib.sha256(f"{tenant}\0{user}".encode()).hexdigest()
        return f"polaris:email-verification:{scope}"

    def digest(self, key: str, code: str) -> str:
        return hmac.new(
            self.secret, f"{key}\0{code}".encode(), hashlib.sha256
        ).hexdigest()

    async def reserve(self, tenant: str, user: str) -> bool:
        return bool(
            await self.client.set(
                self.key(tenant, user) + ":send", "1", nx=True, ex=COOLDOWN
            )
        )

    async def release(self, tenant: str, user: str) -> None:
        await self.client.delete(self.key(tenant, user) + ":send")

    async def issue(self, tenant: str, user: str, token: str) -> str:
        key = self.key(tenant, user)
        code = f"{secrets.randbelow(1_000_000):06d}"
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.hset(
                key,
                mapping={
                    "digest": self.digest(key, code),
                    "token": token,
                    "attempts": 0,
                },
            )
            pipe.expire(key, TTL)
            await pipe.execute()
        return code

    async def consume(self, tenant: str, user: str, code: str) -> str | None:
        key = self.key(tenant, user)
        return await self.client.eval(
            CONSUME, 1, key, self.digest(key, code), MAX_ATTEMPTS
        )


def override_verification_apis(
    original: Any, store: VerificationCodeStore, smtp_ready: bool
) -> Any:
    from supertokens_python.recipe.emailverification.interfaces import (
        EmailVerifyPostInvalidTokenError,
    )
    from supertokens_python.types import GeneralErrorResponse

    send = original.generate_email_verify_token_post
    verify = original.email_verify_post

    async def send_code(session: Any, api_options: Any, user_context: Any) -> Any:
        if not smtp_ready:
            return GeneralErrorResponse("邮箱服务暂不可用，请稍后重试。")
        tenant, user = (
            session.get_tenant_id(),
            session.get_recipe_user_id(user_context).get_as_string(),
        )
        if not await store.reserve(tenant, user):
            return GeneralErrorResponse("验证码已发送，请 60 秒后再试。")
        try:
            return await send(session, api_options, user_context)
        except Exception:
            await store.release(tenant, user)
            raise

    async def verify_code(
        token: str, session: Any, tenant_id: str, api_options: Any, user_context: Any
    ) -> Any:
        if token.isascii() and token.isdigit() and len(token) == 6:
            if session is None:
                return EmailVerifyPostInvalidTokenError()
            resolved_token = await store.consume(
                session.get_tenant_id(),
                session.get_recipe_user_id(user_context).get_as_string(),
                token,
            )
            if not resolved_token:
                return EmailVerifyPostInvalidTokenError()
            token = resolved_token
        # Existing links retain the SDK's normal verification/session handling.
        return await verify(token, session, tenant_id, api_options, user_context)

    original.generate_email_verify_token_post = send_code
    original.email_verify_post = verify_code
    return original
