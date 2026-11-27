"""One AI background for a cover: OpenAI-compatible ``/v1/images/edits``.

Uses the site's configured image route (``POLARIS_IMAGE_BASE_URL`` /
``POLARIS_IMAGE_API_KEY`` / ``POLARIS_IMAGE_MODEL``). Tests and offline runs
replace ``app.state.video_cover_image_client`` with a fake; nothing here is
called unless a priced AI candidate was requested.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Protocol

import httpx
from PIL import Image

from .config import Settings


class CoverImageError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class CoverImageResult:
    image: Image.Image
    model_requested: str
    model_reported: str | None


class CoverImageClient(Protocol):
    def edit(
        self, reference_png: bytes, prompt: str, *, idempotency_key: str
    ) -> CoverImageResult: ...


class HttpCoverImageClient:
    def __init__(self, settings: Settings, timeout_seconds: float = 240):
        self.base_url = settings.image_base_url.rstrip("/")
        self.api_key = settings.image_api_key.get_secret_value()
        self.model = settings.image_model
        self.timeout = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def edit(
        self, reference_png: bytes, prompt: str, *, idempotency_key: str
    ) -> CoverImageResult:
        if not self.configured:
            raise CoverImageError("COVER_IMAGE_NOT_CONFIGURED", "AI 封面服务尚未配置。")
        try:
            response = httpx.post(
                self.base_url + "/v1/images/edits",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Idempotency-Key": idempotency_key,
                },
                data={
                    "model": self.model,
                    "prompt": prompt,
                    "n": "1",
                    "size": "1200x1600",  # 3:4 the relay accepts; resized
                    "quality": "medium",
                    "output_format": "png",
                    "response_format": "b64_json",
                },
                files=[("image", ("frame.png", reference_png, "image/png"))],
                timeout=self.timeout,
            )
        except httpx.TimeoutException:
            raise CoverImageError(
                "COVER_IMAGE_TIMEOUT", "AI 封面生成超时。", retryable=True
            ) from None
        except httpx.HTTPError:
            raise CoverImageError(
                "COVER_IMAGE_UNAVAILABLE", "AI 封面服务暂时连不上。", retryable=True
            ) from None
        if response.status_code >= 400:
            raise CoverImageError(
                "COVER_IMAGE_REJECTED"
                if response.status_code < 500
                else "COVER_IMAGE_UNAVAILABLE",
                "AI 封面服务没有返回图片。",
                retryable=response.status_code >= 500,
            )
        try:
            body = response.json()
            item = body["data"][0]
            raw = base64.b64decode(item["b64_json"])
            image = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:
            raise CoverImageError(
                "COVER_IMAGE_INVALID", "AI 封面服务返回的图片无法读取。"
            ) from None
        return CoverImageResult(
            image, self.model, body.get("model") if isinstance(body, dict) else None
        )
