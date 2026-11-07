"""AliExpress image negotiation and bounded reuse between preview and import."""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from concurrent.futures import Future
from io import BytesIO
from threading import BoundedSemaphore, Lock
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from PIL import Image

from .commerce_images import image_url
from .errors import ApiError
from .justone import domain_matches

IMAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0.0.0 Safari/537.36"
    ),
    # AVIF is intentionally not advertised: preview and import accept the
    # established JPEG / PNG / WebP / GIF contract, regardless of URL suffix.
    "Accept": "image/webp,image/png,image/jpeg,image/gif;q=0.8,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.aliexpress.com/",
}


def is_aliexpress_image(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return bool(
        domain_matches(host, ("aliexpress-media.com",))
        or re.fullmatch(r"ae\d{2}\.alicdn\.com", host)
    )


class ImageRedirects(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        if not image_url(newurl) or not is_aliexpress_image(newurl):
            raise ApiError(400, "IMAGE_REDIRECT_REJECTED", "图片重定向地址不受支持。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class AliExpressImageDownloader:
    def __init__(self, *, max_cache_bytes: int = 64 * 1024 * 1024, ttl: int = 600):
        self._max_cache_bytes = max_cache_bytes
        self._ttl = ttl
        self._cache: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._cache_bytes = 0
        self._pending: dict[str, Future[bytes]] = {}
        self._lock = Lock()
        self._slots = BoundedSemaphore(2)

    @staticmethod
    def _bounded(payload: bytes, max_bytes: int) -> bytes:
        if len(payload) > max_bytes:
            raise ApiError(413, "IMAGE_TOO_LARGE", "图片过大，请选择其他参考图。")
        return payload

    def download(self, url: str, max_bytes: int) -> bytes:
        if not image_url(url) or not is_aliexpress_image(url):
            raise ApiError(400, "IMAGE_URL_REJECTED", "图片地址不受支持。")
        with self._lock:
            now = time.monotonic()
            for stale in [
                u for u, (expires, _) in self._cache.items() if expires <= now
            ]:
                _, payload = self._cache.pop(stale)
                self._cache_bytes -= len(payload)
            if url in self._cache:
                _, payload = self._cache[url]
                self._cache.move_to_end(url)
                return self._bounded(payload, max_bytes)
            pending = self._pending.get(url)
            owner = pending is None
            if pending is None:
                pending = Future()
                self._pending[url] = pending
        if not owner:
            try:
                return self._bounded(pending.result(timeout=90), max_bytes)
            except TimeoutError:
                raise ApiError(
                    502, "IMAGE_SOURCE_BUSY", "图片来源繁忙，请稍后重新加载。"
                ) from None
        try:
            if not self._slots.acquire(timeout=40):
                raise ApiError(
                    502, "IMAGE_SOURCE_BUSY", "图片来源繁忙，请稍后重新加载。"
                )
            try:
                payload = self._fetch(url, max_bytes)
            finally:
                self._slots.release()
            with self._lock:
                if len(payload) <= self._max_cache_bytes:
                    while (
                        self._cache
                        and self._cache_bytes + len(payload) > self._max_cache_bytes
                    ):
                        _, (_, removed) = self._cache.popitem(last=False)
                        self._cache_bytes -= len(removed)
                    self._cache[url] = (time.monotonic() + self._ttl, payload)
                    self._cache_bytes += len(payload)
            pending.set_result(payload)
            return payload
        except Exception as error:
            pending.set_exception(error)
            raise
        finally:
            with self._lock:
                self._pending.pop(url, None)

    def _fetch(self, url: str, max_bytes: int) -> bytes:
        # One short retry only when the CDN permits it. No host rotation,
        # generated replacement URL, external proxy, or unbounded retry loop.
        for attempt in range(2):
            try:
                with build_opener(ProxyHandler({}), ImageRedirects()).open(
                    Request(url, headers=IMAGE_HEADERS), timeout=20
                ) as response:
                    payload = self._bounded(response.read(max_bytes + 1), max_bytes)
                with Image.open(BytesIO(payload)) as source:
                    if source.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                        raise ValueError("Unsupported image format")
                    source.verify()
                return payload
            except HTTPError as error:
                if error.code in {429, 503}:
                    retry_after = (
                        error.headers.get("Retry-After", "1") if error.headers else "1"
                    )
                    if (
                        attempt == 0
                        and retry_after.isdigit()
                        and 0 <= int(retry_after) <= 5
                    ):
                        time.sleep(max(1, int(retry_after)))
                        continue
                    raise ApiError(
                        502,
                        "IMAGE_SOURCE_BUSY",
                        "图片来源暂时限制访问，请稍后重新加载或导入。",
                    ) from None
                raise ApiError(
                    502, "IMAGE_DOWNLOAD_FAILED", "该图片暂时无法读取，请稍后重新加载。"
                ) from None
            except ApiError:
                raise
            except Exception:
                raise ApiError(
                    502, "IMAGE_DOWNLOAD_FAILED", "该图片暂时无法读取，请稍后重新加载。"
                ) from None
        raise AssertionError("unreachable")


downloader = AliExpressImageDownloader()
