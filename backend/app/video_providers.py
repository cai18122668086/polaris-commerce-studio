"""Server-only provider adapter. POST operations are never retried implicitly."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .config import Settings
from .errors import ApiError

MEDIA_HOSTS = {
    "skyhumanapi.pilihu.vip",
    "cdn-oss.pilihu.vip",
    "quanyu.sowa.chat",
    "www.wuyeai.cn",
    "res.chanjing.cc",
    "cdn.jihuo.pro",
    "sowa.oss-cn-beijing.aliyuncs.com",
    "openpt1.oss-cn-shanghai.aliyuncs.com",
}


def safe_media_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        port = parts.port
    except (ValueError, TypeError):
        raise ApiError(502, "VIDEO_MEDIA_HOST_REJECTED", "素材地址无效。") from None
    if (
        parts.scheme != "https"
        or parts.hostname not in MEDIA_HOSTS
        or parts.username
        or parts.password
        or port not in {None, 443}
    ):
        raise ApiError(502, "VIDEO_MEDIA_HOST_REJECTED", "供应商素材地址暂不受支持。")
    return url


class VideoProviders:
    def __init__(
        self, settings: Settings, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.settings = settings
        self.transport = transport

    def request(
        self, vendor: str, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        if not self.settings.video_providers_enabled:
            raise ApiError(503, "VIDEO_PROVIDER_DISABLED", "视频服务尚未配置。")
        if vendor not in {"quanyu", "wuye", "skyhuman"}:
            raise ApiError(503, "VIDEO_PROVIDER_DISABLED", "视频服务尚未配置。")
        key = {
            "quanyu": self.settings.quanyu_api_key,
            "wuye": self.settings.wuye_api_key,
            "skyhuman": self.settings.skyhuman_api_key,
        }[vendor].get_secret_value()
        if not key:
            raise ApiError(503, "VIDEO_PROVIDER_DISABLED", "视频服务尚未配置。")
        host = {
            "quanyu": "https://quanyu.sowa.chat",
            "wuye": "https://www.wuyeai.cn",
            "skyhuman": "https://skyhumanapi.pilihu.vip",
        }[vendor]
        headers = (
            {"X-API-Key": key}
            if vendor == "quanyu"
            else {"Authorization": "Bearer " + key}
        )
        headers = {**kwargs.pop("headers", {}), **headers}
        try:
            with httpx.Client(
                timeout=httpx.Timeout(120, connect=15),
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = client.request(
                    method, host + path, headers=headers, **kwargs
                )
        except (httpx.HTTPError, ValueError):
            raise ApiError(
                502,
                "VIDEO_PROVIDER_OUTCOME_UNKNOWN"
                if method == "POST"
                else "VIDEO_PROVIDER_UNAVAILABLE",
                "供应商响应未能确认，请保留原任务查询，避免重复提交。",
            ) from None
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected object")
        except ValueError:
            raise ApiError(
                502,
                "VIDEO_PROVIDER_OUTCOME_UNKNOWN"
                if method == "POST"
                else "VIDEO_PROVIDER_UNAVAILABLE",
                "供应商响应未能解析。",
            ) from None
        task_status_response = (
            method == "GET"
            and "status" in data
            and (path.startswith("/api/status/") or path.startswith("/v1/videos/"))
        )
        if (
            not response.is_success
            or data.get("error")
            and not task_status_response
            or vendor == "skyhuman"
            and data.get("code", 0) != 0
        ):
            # Never expose raw upstream bodies (they may contain URLs or tokens).
            raise ApiError(
                502,
                "VIDEO_PROVIDER_OUTCOME_UNKNOWN"
                if method == "POST"
                and (response.status_code >= 500 or response.status_code == 408)
                else "VIDEO_PROVIDER_REJECTED",
                "供应商未接受请求，请检查余额、形象或音色配置。",
                {"vendor": vendor, "upstream_status": response.status_code},
            )
        return data

    def models(self) -> list[dict[str, Any]]:
        return self.request("quanyu", "GET", "/api/digital_human/models").get(
            "models", []
        )

    def voices(self) -> list[dict[str, Any]]:
        return self.request("quanyu", "GET", "/api/tts/preset-voices").get("voices", [])

    def prices(self) -> dict[str, Any]:
        return self.request("quanyu", "GET", "/api/billing/features").get(
            "features", {}
        )

    def upload(self, path: Path, mime: str, purpose: str) -> str:
        policy = self.request(
            "quanyu",
            "POST",
            "/api/oss/upload_policy",
            json={"ext": path.suffix.lstrip("."), "purpose": purpose},
        )
        host = safe_media_url(policy["host"])
        url = safe_media_url(policy["object_url"])
        try:
            with (
                httpx.Client(timeout=180, transport=self.transport) as client,
                path.open("rb") as file,
            ):
                result = client.post(
                    host,
                    data={
                        "OSSAccessKeyId": policy["access_key_id"],
                        "policy": policy["policy"],
                        "signature": policy["signature"],
                        "key": policy["key"],
                        "success_action_status": "200",
                    },
                    files={"file": (path.name, file, mime)},
                )
                result.raise_for_status()
        except (httpx.HTTPError, KeyError):
            raise ApiError(
                502, "VIDEO_UPLOAD_FAILED", "素材上传失败，请重试上传。"
            ) from None
        return url

    def download(
        self,
        url: str,
        target: Path,
        limit: int = 200 * 1024 * 1024,
        vendor: str | None = None,
    ) -> None:
        import time

        for attempt in range(3):
            try:
                return self._download_once(url, target, limit, vendor)
            except httpx.HTTPError:
                if attempt == 2:
                    raise ApiError(
                        502,
                        "VIDEO_MEDIA_DOWNLOAD_FAILED",
                        "素材下载中断，可继续原任务下载，无需重新生成。",
                    ) from None
                time.sleep(1)

    def _download_once(
        self,
        url: str,
        target: Path,
        limit: int = 200 * 1024 * 1024,
        vendor: str | None = None,
    ) -> None:
        safe_media_url(url)
        headers = (
            {"Authorization": "Bearer " + self.settings.wuye_api_key.get_secret_value()}
            if vendor == "wuye"
            else {}
        )
        if vendor == "quanyu":
            headers = {"X-API-Key": self.settings.quanyu_api_key.get_secret_value()}
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + "." + str(uuid4()) + ".part")
        with httpx.Client(
            timeout=180, transport=self.transport, follow_redirects=False
        ) as client:
            for _ in range(4):
                with client.stream("GET", url, headers=headers) as response:
                    if response.is_redirect:
                        url = safe_media_url(str(response.headers.get("location", "")))
                        headers = {}  # Never forward credentials to a media host.
                        continue
                    response.raise_for_status()
                    size = 0
                    with temporary.open("wb") as file:
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > limit:
                                raise ApiError(
                                    502,
                                    "VIDEO_MEDIA_TOO_LARGE",
                                    "供应商素材超过大小限制。",
                                )
                            file.write(chunk)
                    temporary.replace(target)
                    return
        raise ApiError(502, "VIDEO_MEDIA_DOWNLOAD_FAILED", "供应商素材暂时无法下载。")
