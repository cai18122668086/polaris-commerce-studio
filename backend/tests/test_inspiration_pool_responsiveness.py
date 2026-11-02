"""Inspiration image bursts must not occupy DB slots or block authentication."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import main
from tests.test_inspiration_thumbnails import published_picture


# This is a setup watchdog, not an endpoint latency requirement. Shared CI
# runners can pause a metadata worker; keep room below the real cache's 10s
# deadline while retaining the independent 1s authentication assertion below.
BURST_START_TIMEOUT_SECONDS = 8


@pytest.mark.parametrize("variant", ["original", "thumbnail"])
@pytest.mark.parametrize("request_count", [8, 48])
def test_inspiration_image_burst_releases_database_while_images_wait(
    settings, monkeypatch, variant, request_count
):
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        pool_size=2,
        max_overflow=0,
        pool_timeout=0.25,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "build_database", lambda _url: (engine, factory))
    app = main.create_app(settings)
    with TestClient(app) as setup:
        url, original, _ = published_picture(setup)

        async def scenario():
            release = asyncio.Event()
            image_waiting: asyncio.Queue[None] = asyncio.Queue()
            thumbnail_get = app.state.thumbnails.get

            async def slow_read(_key):
                if variant == "original":
                    image_waiting.put_nowait(None)
                await release.wait()
                return original

            async def observed_thumbnail(key, read):
                # Observe every waiting HTTP request, including those sharing
                # the real thumbnail cache's single in-flight production task.
                image_waiting.put_nowait(None)
                return await thumbnail_get(key, read)

            monkeypatch.setattr(app.state.storage, "read_bytes", slow_read)
            monkeypatch.setattr(app.state.thumbnails, "get", observed_thumbnail)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://testserver",
            ) as client:
                tasks = []
                try:
                    for _ in range(request_count):
                        tasks.append(
                            asyncio.create_task(
                                client.get(url, params={"variant": variant})
                            )
                        )
                        arrival = asyncio.create_task(image_waiting.get())
                        try:
                            done, _ = await asyncio.wait(
                                (arrival, tasks[-1]),
                                timeout=BURST_START_TIMEOUT_SECONDS,
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if arrival not in done:
                                result = "request still pending"
                                if tasks[-1].done():
                                    response = tasks[-1].result()
                                    result = (
                                        f"HTTP {response.status_code}: "
                                        f"{response.text[:300]}"
                                    )
                                pytest.fail(
                                    f"Image request {len(tasks)}/{request_count} "
                                    f"({variant}) did not reach its I/O wait: {result}"
                                )
                        finally:
                            arrival.cancel()
                            await asyncio.gather(arrival, return_exceptions=True)
                        # Connections must be available even before the image
                        # request finishes, so later DB queries cannot starve.
                        assert engine.pool.checkedout() == 0
                    assert not any(task.done() for task in tasks)
                    ready, identity = await asyncio.wait_for(
                        asyncio.gather(
                            client.get("/health/ready"),
                            client.get("/api/v1/me"),
                        ),
                        timeout=1,
                    )
                    assert ready.status_code == identity.status_code == 200
                    assert not release.is_set()
                finally:
                    release.set()
                    responses = await asyncio.gather(*tasks, return_exceptions=True)
                assert all(
                    isinstance(response, httpx.Response) and response.status_code == 200
                    for response in responses
                )
                if variant == "original":
                    assert all(response.content == original for response in responses)
                else:
                    assert all(
                        response.headers["content-type"] == "image/webp"
                        for response in responses
                    )

        asyncio.run(scenario())


@pytest.mark.parametrize("variant", ["original", "thumbnail"])
def test_slow_inspiration_database_query_does_not_block_event_loop(settings, variant):
    app = main.create_app(settings)
    entered, release = threading.Event(), threading.Event()
    with TestClient(app) as setup:
        url, _, _ = published_picture(setup)

        def delay_inspiration_query(_conn, _cursor, statement, *_args):
            if "FROM inspiration_cases" in statement:
                entered.set()
                assert release.wait(3), "watchdog: inspiration query was not released"

        event.listen(app.state.engine, "before_cursor_execute", delay_inspiration_query)

        async def scenario():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://testserver",
            ) as client:
                image_task = asyncio.create_task(
                    client.get(url, params={"variant": variant})
                )
                try:
                    assert await asyncio.to_thread(entered.wait, 1)
                    response = await asyncio.wait_for(client.get("/health/live"), 1)
                    assert response.status_code == 200
                    assert not release.is_set()
                finally:
                    release.set()
                    image_response = await image_task
                assert image_response.status_code == 200

        try:
            # Also unblocks the old synchronous implementation if it stalls
            # the event loop, ensuring the regression fails instead of hanging.
            with ThreadPoolExecutor(max_workers=1) as executor:
                watchdog = executor.submit(lambda: release.wait(2) or release.set())
                asyncio.run(scenario())
                watchdog.result()
        finally:
            release.set()
            event.remove(
                app.state.engine, "before_cursor_execute", delay_inspiration_query
            )
