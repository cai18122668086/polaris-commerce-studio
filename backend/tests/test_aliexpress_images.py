from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event, Lock
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from PIL import Image

from app import aliexpress_images
from app.aliexpress_images import AliExpressImageDownloader, ImageRedirects
from app.errors import ApiError

URL = "https://ae-pic-a1.aliexpress-media.com/kf/image.jpg"


def image_bytes():
    out = BytesIO()
    Image.new("RGB", (80, 90), "blue").save(out, "WEBP")
    return out.getvalue()


def stub(monkeypatch, replies):
    calls = []
    pending = iter(replies)

    def open_request(request, timeout):
        calls.append(request)
        value = next(pending)
        if isinstance(value, Exception):
            raise value
        return BytesIO(value)

    monkeypatch.setattr(
        aliexpress_images,
        "build_opener",
        lambda *args: SimpleNamespace(open=open_request),
    )
    return calls


def test_negotiates_supported_images_and_reuses_bytes_for_import(monkeypatch):
    payload = image_bytes()
    calls = stub(monkeypatch, [payload])
    client = AliExpressImageDownloader()
    assert client.download(URL, 10000) == payload
    assert client.download(URL, 10000) == payload
    assert len(calls) == 1
    assert calls[0].full_url == URL
    assert "Chrome/" in calls[0].get_header("User-agent")
    assert "image/webp" in calls[0].get_header("Accept")
    assert "image/avif" not in calls[0].get_header("Accept")
    assert calls[0].get_header("Authorization") is None
    with pytest.raises(ApiError) as caught:
        client.download(URL, len(payload) - 1)
    assert caught.value.code == "IMAGE_TOO_LARGE"
    assert len(calls) == 1


def test_duplicate_preview_requests_share_one_download(monkeypatch):
    started, release = Event(), Event()
    payload = image_bytes()
    calls = []

    def open_request(request, timeout):
        calls.append(request)
        started.set()
        assert release.wait(5)
        return BytesIO(payload)

    monkeypatch.setattr(
        aliexpress_images,
        "build_opener",
        lambda *args: SimpleNamespace(open=open_request),
    )
    client = AliExpressImageDownloader()
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(client.download, URL, 10000) for _ in range(5)]
        assert started.wait(5)
        release.set()
        assert [f.result(timeout=5) for f in futures] == [payload] * 5
    assert len(calls) == 1


def test_different_images_have_at_most_two_active_cdn_requests(monkeypatch):
    ready, release, lock = Event(), Event(), Lock()
    active = maximum = 0

    def fetch(url, maximum_bytes):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                ready.set()
        assert release.wait(5)
        with lock:
            active -= 1
        return image_bytes()

    client = AliExpressImageDownloader()
    monkeypatch.setattr(client, "_fetch", fetch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(client.download, URL + f"?id={i}", 10000) for i in range(4)
        ]
        assert ready.wait(5)
        release.set()
        for future in futures:
            assert future.result(timeout=5)
    assert maximum == 2


def test_cache_is_bounded_and_expired_entries_are_refetched(monkeypatch):
    payload = image_bytes()
    calls = stub(monkeypatch, [payload] * 4)
    now = [1.0]
    monkeypatch.setattr(aliexpress_images.time, "monotonic", lambda: now[0])
    client = AliExpressImageDownloader(max_cache_bytes=len(payload) + 1, ttl=10)
    client.download(URL, 10000)
    client.download(URL + "?second", 10000)
    assert client._cache_bytes <= len(payload) + 1
    client.download(URL, 10000)
    assert len(calls) == 3
    now[0] = 12.0
    client.download(URL, 10000)
    assert len(calls) == 4


def test_short_cdn_retry_after_is_respected_once(monkeypatch):
    calls = stub(
        monkeypatch,
        [HTTPError(URL, 429, "busy", {"Retry-After": "2"}, BytesIO()), image_bytes()],
    )
    sleeps = []
    monkeypatch.setattr(aliexpress_images.time, "sleep", sleeps.append)
    assert AliExpressImageDownloader().download(URL, 10000)
    assert len(calls) == 2 and sleeps == [2]


@pytest.mark.parametrize("retry_after", ["60", "Sat, 07 Nov 2026 04:00:00 GMT"])
def test_long_retry_after_does_not_trigger_immediate_retry(monkeypatch, retry_after):
    calls = stub(
        monkeypatch,
        [HTTPError(URL, 429, "busy", {"Retry-After": retry_after}, BytesIO())],
    )
    with pytest.raises(ApiError) as caught:
        AliExpressImageDownloader().download(URL, 10000)
    assert caught.value.code == "IMAGE_SOURCE_BUSY"
    assert len(calls) == 1


def test_repeated_cdn_failure_stops_after_one_retry(monkeypatch):
    calls = stub(monkeypatch, [HTTPError(URL, 503, "busy", {}, BytesIO())] * 2)
    monkeypatch.setattr(aliexpress_images.time, "sleep", lambda *args: None)
    with pytest.raises(ApiError) as caught:
        AliExpressImageDownloader().download(URL, 10000)
    assert caught.value.code == "IMAGE_SOURCE_BUSY"
    assert len(calls) == 2


def test_invalid_image_bytes_are_not_cached(monkeypatch):
    calls = stub(monkeypatch, [b"<html>unavailable</html>", image_bytes()])
    client = AliExpressImageDownloader()
    with pytest.raises(ApiError):
        client.download(URL, 10000)
    assert client.download(URL, 10000)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/image.jpg",
        "https://evil.test/image.jpg",
        "https://ae01.alicdn.com.evil.test/image.jpg",
        "https://user:password@ae01.alicdn.com/image.jpg",
    ],
)
def test_untrusted_image_urls_and_redirects_are_rejected(url):
    with pytest.raises(ApiError):
        AliExpressImageDownloader().download(url, 10000)
    with pytest.raises(ApiError):
        ImageRedirects().redirect_request(Request(URL), None, 302, "", {}, url)
