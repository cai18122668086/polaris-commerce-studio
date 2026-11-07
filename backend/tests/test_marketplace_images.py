from io import BytesIO
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import Request

import pytest
from PIL import Image

from app import aliexpress_images
from app.errors import ApiError
from app.marketplace_images import ImageRedirects, MarketplaceImageDownloader

URL = "https://p26-item.ecombdimg.com/product.webp"


def test_transient_connection_failure_retries_once_and_import_reuses_preview(
    monkeypatch,
):
    out = BytesIO()
    Image.new("RGB", (80, 90), "blue").save(out, "WEBP")
    payload = out.getvalue()
    calls = []
    replies = iter([URLError(TimeoutError()), payload])

    def open_request(request, timeout):
        calls.append((request, timeout))
        value = next(replies)
        if isinstance(value, Exception):
            raise value
        return BytesIO(value)

    monkeypatch.setattr(
        aliexpress_images,
        "build_opener",
        lambda *args: SimpleNamespace(open=open_request),
    )
    monkeypatch.setattr(aliexpress_images.time, "sleep", lambda *args: None)
    client = MarketplaceImageDownloader()
    assert client.download(URL, 10000) == payload
    assert client.download(URL, 10000) == payload
    assert len(calls) == 2
    assert all(timeout == 10 for _, timeout in calls)
    assert calls[0][0].get_header("Referer") == "https://haohuo.jinritemai.com/"


def test_repeated_transport_errors_stop_without_caching(monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise URLError(TimeoutError())

    monkeypatch.setattr(
        aliexpress_images, "build_opener", lambda *args: SimpleNamespace(open=fail)
    )
    monkeypatch.setattr(aliexpress_images.time, "sleep", lambda *args: None)
    client = MarketplaceImageDownloader()
    with pytest.raises(ApiError):
        client.download(URL, 10000)
    assert len(calls) == 2 and not client._cache


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/a.jpg",
        "https://xhscdn.com.evil.test/a.jpg",
        "https://user:pw@i5.walmartimages.com/image.jpg",
    ],
)
def test_cache_cannot_admit_untrusted_urls_or_redirects(url):
    with pytest.raises(ApiError):
        MarketplaceImageDownloader().download(url, 10000)
    with pytest.raises(ApiError):
        ImageRedirects().redirect_request(Request(URL), None, 302, "", {}, url)
