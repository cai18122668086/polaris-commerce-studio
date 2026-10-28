"""Shared image admission across API instances and Celery worker processes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from time import time
from typing import Any
from uuid import uuid4

from redis import Redis

ACQUIRE = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return 0 end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[4])
redis.call('EXPIRE', KEYS[1], 1800)
return 1
"""
RENEW = """
if not redis.call('ZSCORE', KEYS[1], ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
redis.call('EXPIRE', KEYS[1], 1800)
return 1
"""


class ImageCapacity:
    def __init__(self, url: str, limit: int) -> None:
        self.client = Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3)
        self.limit = limit
        self.key = "polaris:image-capacity:v1"

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        token = uuid4().hex
        while not await asyncio.to_thread(
            self.client.eval,
            ACQUIRE,
            1,
            self.key,
            str(time()),
            str(time() + 1200),
            str(self.limit),
            token,
        ):
            await asyncio.sleep(0.25)

        async def renew() -> None:
            while True:
                await asyncio.sleep(30)
                if not await asyncio.to_thread(
                    self.client.eval, RENEW, 1, self.key, token, str(time() + 1200)
                ):
                    raise RuntimeError("Image capacity lease was lost")

        heartbeat = asyncio.create_task(renew())
        try:
            yield
        finally:
            heartbeat.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await heartbeat
            finally:
                await asyncio.to_thread(self.client.zrem, self.key, token)


def limit_gateway(gateway: Any, url: str, limit: int) -> Any:
    admission = ImageCapacity(url, limit)
    for name in ("edit", "edit_masked"):
        original = getattr(gateway, name)

        def wrap(
            call: Callable[[Any], Awaitable[Any]],
        ) -> Callable[[Any], Awaitable[Any]]:
            async def limited(request: Any) -> Any:
                async with admission.slot():
                    return await call(request)

            return limited

        setattr(gateway, name, wrap(original))
    return gateway
