"""Fixed-window per-IP and per-session request rate limiting backed by Redis.

Pure ASGI middleware so it runs before authentication and body parsing. Any
Redis failure lets the request through (fail open) and pauses Redis use for a
short cool-down so an outage never adds latency to every request.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import time
from collections.abc import Callable, Sequence
from http.cookies import SimpleCookie
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

COUNT = """
local out = {}
for i, key in ipairs(KEYS) do
  local n = redis.call('INCR', key)
  if n == 1 then redis.call('EXPIRE', key, tonumber(ARGV[1])) end
  out[i] = n
end
return out
"""
EXEMPT_PREFIXES = ("/health",)
RATE_LIMITED_MESSAGE = "请求过于频繁，请稍后再试。"
# Proxies whose X-Forwarded-For / X-Real-IP are believed: loopback and the
# private ranges Docker networks use. Anything else is the client itself.
DEFAULT_TRUSTED_PROXIES = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "fc00::/7",
)
Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_networks(values: Sequence[str]) -> tuple[Network, ...]:
    return tuple(ipaddress.ip_network(value.strip(), strict=False) for value in values)


def _trusted(address: str, networks: Sequence[Network]) -> bool:
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    return any(ip in network for network in networks)


def client_ip(scope: Scope, trusted: Sequence[Network]) -> str | None:
    """Real client address; forwarding headers count only from trusted peers.

    Walks X-Forwarded-For from the right, skipping trusted proxies, so a value
    the client injected on the left is never used while a real hop exists.
    """

    peer = scope.get("client")
    address = peer[0] if peer else None
    if address is None or not _trusted(address, trusted):
        return address
    forwarded = _header(scope, b"x-forwarded-for")
    if forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        for hop in reversed(hops):
            if not _trusted(hop, trusted):
                return hop if _valid(hop) else address
        if hops and _valid(hops[0]):
            return hops[0]
    real_ip = _header(scope, b"x-real-ip")
    if real_ip and _valid(real_ip):
        return real_ip.strip()
    return address


def _valid(address: str) -> bool:
    try:
        ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    return True


# Session credentials that identify one signed-in user without verifying them.
SESSION_COOKIES = ("sAccessToken", "sRefreshToken")


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def user_key(scope: Scope) -> str | None:
    """Stable per-session key: hash of the session token, never the token."""

    credential = None
    authorization = _header(scope, b"authorization")
    if authorization and authorization.lower().startswith("bearer "):
        credential = authorization[7:].strip()
    if not credential:
        raw = _header(scope, b"cookie")
        if raw:
            cookie: SimpleCookie = SimpleCookie()
            try:
                cookie.load(raw)
            except Exception:
                cookie = SimpleCookie()
            for name in SESSION_COOKIES:
                if name in cookie and cookie[name].value:
                    credential = cookie[name].value
                    break
    if not credential:
        credential = _header(scope, b"x-user-id")
    if not credential:
        return None
    return hashlib.sha256(credential.encode()).hexdigest()[:32]


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        redis_url: str,
        window_seconds: int,
        per_ip: int,
        per_user: int,
        exempt_prefixes: Sequence[str] = EXEMPT_PREFIXES,
        client_factory: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.time,
        trusted_proxies: Sequence[str] = DEFAULT_TRUSTED_PROXIES,
        cooldown_seconds: float = 15,
    ) -> None:
        self.app = app
        self.redis_url = redis_url
        self.window = window_seconds
        self.per_ip = per_ip
        self.per_user = per_user
        self.exempt_prefixes = tuple(exempt_prefixes)
        self.client_factory = client_factory
        self.clock = clock
        self.cooldown = cooldown_seconds
        self.trusted = parse_networks(trusted_proxies)
        self._clients: dict[int, Any] = {}
        self._paused_until = 0.0

    def _client(self) -> Any:
        loop_id = id(asyncio.get_running_loop())
        client = self._clients.get(loop_id)
        if client is None:
            if self.client_factory is not None:
                client = self.client_factory()
            else:
                from redis.asyncio import Redis

                client = Redis.from_url(
                    self.redis_url,
                    socket_connect_timeout=0.25,
                    socket_timeout=0.25,
                    retry_on_timeout=False,
                )
            self._clients = {loop_id: client}
        return client

    def _exempt(self, scope: Scope) -> bool:
        if scope.get("method") == "OPTIONS":
            return True
        path = scope.get("path") or ""
        return any(path.startswith(prefix) for prefix in self.exempt_prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._exempt(scope):
            await self.app(scope, receive, send)
            return
        now = self.clock()
        if now < self._paused_until:
            await self.app(scope, receive, send)
            return
        window_id = int(now // self.window)
        checks: list[tuple[str, int]] = []
        address = client_ip(scope, self.trusted)
        if self.per_ip and address:
            checks.append((f"polaris:rl:v1:ip:{address}:{window_id}", self.per_ip))
        session = user_key(scope)
        if self.per_user and session:
            checks.append((f"polaris:rl:v1:user:{session}:{window_id}", self.per_user))
        if not checks:
            await self.app(scope, receive, send)
            return
        try:
            counts = await self._client().eval(
                COUNT, len(checks), *[key for key, _ in checks], str(self.window + 1)
            )
        except Exception:  # fail open on any Redis problem
            self._paused_until = now + self.cooldown
            logger.warning("rate_limit_redis_unavailable; failing open", exc_info=True)
            await self.app(scope, receive, send)
            return
        if any(
            int(count) > limit
            for count, (_, limit) in zip(counts, checks, strict=False)
        ):
            retry_after = max(1, int(self.window - (now % self.window)) + 1)
            await self._reject(send, retry_after)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Send, retry_after: int) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "RATE_LIMITED",
                    "message": RATE_LIMITED_MESSAGE,
                    "details": {"retry_after_seconds": retry_after},
                    "retryable": True,
                }
            },
            ensure_ascii=False,
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    (b"retry-after", str(retry_after).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
