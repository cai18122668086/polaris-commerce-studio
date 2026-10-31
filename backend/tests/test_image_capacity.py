import asyncio
from contextlib import suppress
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


def test_backup_capacity_is_shared_across_clients_and_separate_from_main():
    async def scenario():
        server = fakeredis.FakeServer()
        backup = [
            ImageCapacity("redis://localhost", 4, key="backup-account")
            for _ in range(2)
        ]
        main = ImageCapacity("redis://localhost", 20)
        for gate in [*backup, main]:
            gate.client = fakeredis.FakeRedis(server=server)
        active = {"backup": 0, "main": 0}
        peak = dict(active)

        async def call(gate, channel):
            async with gate.slot():
                active[channel] += 1
                peak[channel] = max(peak[channel], active[channel])
                await asyncio.sleep(0.03)
                active[channel] -= 1

        await asyncio.gather(
            *(call(backup[i % 2], "backup") for i in range(20)),
            *(call(main, "main") for _ in range(8)),
        )
        assert peak == {"backup": 4, "main": 8}
        assert (
            main.client.zcard(main.key) == backup[0].client.zcard("backup-account") == 0
        )

    asyncio.run(scenario())


def test_cancelling_a_queued_image_does_not_leak_an_extra_slot():
    async def scenario():
        gate = ImageCapacity("redis://localhost", 1, key="backup-account")
        gate.client = fakeredis.FakeRedis()

        async def waiting():
            async with gate.slot():
                raise AssertionError("Cancelled request must never enter")

        async with gate.slot():
            task = asyncio.create_task(waiting())
            await asyncio.sleep(0.05)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            assert gate.client.zcard(gate.key) == 1
        assert gate.client.zcard(gate.key) == 0

    asyncio.run(scenario())


def test_redis_release_failure_preserves_returned_image_and_expiring_lease(monkeypatch):
    from redis.exceptions import ConnectionError

    async def scenario():
        gate = ImageCapacity("redis://localhost", 1, key="backup-account")
        gate.client = fakeredis.FakeRedis()

        def unavailable(*args):
            raise ConnectionError("Synthetic outage")

        monkeypatch.setattr(gate.client, "zrem", unavailable)
        async with gate.slot():
            result = "completed upstream image"
        assert result == "completed upstream image"
        assert gate.client.zcard(gate.key) == 1
        assert gate.client.ttl(gate.key) > 0

    asyncio.run(scenario())


def test_renewal_outage_does_not_discard_completed_image(monkeypatch):
    from redis.exceptions import ConnectionError

    from app.image_capacity import RENEW

    original_sleep = asyncio.sleep

    async def fast_heartbeat(seconds):
        await original_sleep(0.005 if seconds == 30 else seconds)

    monkeypatch.setattr("app.image_capacity.asyncio.sleep", fast_heartbeat)

    async def scenario():
        gate = ImageCapacity("redis://localhost", 1, key="backup-account")
        gate.client = fakeredis.FakeRedis()
        original_eval = gate.client.eval
        renewed = False

        def fail_renew(script, *args):
            nonlocal renewed
            if script == RENEW:
                renewed = True
                raise ConnectionError("Synthetic renewal outage")
            return original_eval(script, *args)

        monkeypatch.setattr(gate.client, "eval", fail_renew)
        async with gate.slot():
            await original_sleep(0.03)
            image = "completed upstream image"
        assert renewed and image == "completed upstream image"
        assert gate.client.zcard(gate.key) == 0

    asyncio.run(scenario())
