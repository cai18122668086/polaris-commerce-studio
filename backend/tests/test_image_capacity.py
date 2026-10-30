import asyncio
from time import time

import fakeredis

from app.config import Settings
from app.image_capacity import ImageCapacity


def test_shared_limit_releases_and_recovers_expired_slots():
    async def scenario():
        first, second = (
            ImageCapacity("redis://localhost", 1),
            ImageCapacity("redis://localhost", 1),
        )
        server = fakeredis.FakeServer()
        first.client = fakeredis.FakeRedis(server=server)
        second.client = fakeredis.FakeRedis(server=server)
        first.client.zadd(first.key, {"dead-worker": time() - 1})
        waiting = asyncio.Event()
        entered = asyncio.Event()

        async def follower():
            waiting.set()
            async with second.slot():
                entered.set()

        async with first.slot():
            follower_task = asyncio.create_task(follower())
            await waiting.wait()
            await asyncio.sleep(0.05)
            assert not entered.is_set()
            assert first.client.zcard(first.key) == 1
        await asyncio.wait_for(follower_task, 2)
        assert entered.is_set() and first.client.zcard(first.key) == 0

    asyncio.run(scenario())


def test_capacity_accepts_3000_and_rejects_values_above_it():
    import pytest
    from pydantic import ValidationError

    assert Settings(_env_file=None).image_global_concurrency == 3000
    assert Settings(_env_file=None, xinghe_concurrency=3000).xinghe_concurrency == 3000
    with pytest.raises(ValidationError):
        Settings(_env_file=None, image_global_concurrency=3001)
