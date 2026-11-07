"""Bounded CDN downloads shared by all other commerce preview/import routes."""

from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler

from .aliexpress_images import IMAGE_HEADERS, AliExpressImageDownloader
from .commerce_images import download_url, image_url
from .errors import ApiError


class ImageRedirects(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        if not image_url(newurl):
            raise ApiError(400, "IMAGE_REDIRECT_REJECTED", "图片重定向地址不受支持。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class MarketplaceImageDownloader(AliExpressImageDownloader):
    request_timeout = 10
    retry_transport_errors = True

    @staticmethod
    def accepts(url: str) -> bool:
        return bool(image_url(url))

    @staticmethod
    def request_url(url: str) -> str:
        return download_url(url)

    @staticmethod
    def headers(url: str) -> dict[str, str]:
        headers = {
            key: value for key, value in IMAGE_HEADERS.items() if key != "Referer"
        }
        host = (urlparse(url).hostname or "").lower()
        if host.endswith(".ecombdimg.com"):
            headers["Referer"] = "https://haohuo.jinritemai.com/"
        return headers

    @staticmethod
    def redirects() -> HTTPRedirectHandler:
        return ImageRedirects()


downloader = MarketplaceImageDownloader()
