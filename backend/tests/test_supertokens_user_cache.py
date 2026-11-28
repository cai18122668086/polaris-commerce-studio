"""Authenticated requests reuse a verified Core user record briefly."""

import asyncio
from types import SimpleNamespace

from app.config import Settings
from app.supertokens_auth import USER_CACHE_SECONDS, SuperTokensAuthAdapter


def _adapter(verified=True):
    adapter = SuperTokensAuthAdapter(Settings(_env_file=None))  # type: ignore[call-arg]
    calls = []
    clock = {"now": 100.0}
    method = SimpleNamespace(
        recipe_user_id=SimpleNamespace(get_as_string=lambda: "u1"),
        email="a@example.com",
        verified=verified,
    )
    user = SimpleNamespace(login_methods=[method], time_joined=0)

    async def get_user(user_id):
        calls.append(user_id)
        return user

    async def verify_session(_request):
        return SimpleNamespace(
            get_user_id=lambda: "u1",
            get_recipe_user_id=lambda: SimpleNamespace(get_as_string=lambda: "u1"),
        )

    adapter._initialized = True
    adapter._verify_session = verify_session
    adapter._get_user = get_user
    adapter._clock = lambda: clock["now"]
    return adapter, calls, clock


def test_core_lookup_is_cached_for_verified_users():
    adapter, calls, clock = _adapter()
    for _ in range(5):
        identity = asyncio.run(adapter.authenticate(None))
    assert identity.email == "a@example.com" and identity.email_verified
    assert calls == ["u1"]
    clock["now"] += USER_CACHE_SECONDS + 1
    asyncio.run(adapter.authenticate(None))
    assert calls == ["u1", "u1"]


def test_unverified_users_are_never_cached():
    adapter, calls, _ = _adapter(verified=False)
    for _ in range(3):
        identity = asyncio.run(adapter.authenticate(None))
    assert identity.email_verified is False
    assert len(calls) == 3
