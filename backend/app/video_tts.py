"""Single-submit Tao Speech adapter. Persist audio before any downstream upload."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .config import Settings
from .errors import ApiError


def synthesize(
    settings: Settings,
    selection: dict[str, Any],
    text: str,
    target: Path,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    if (
        not settings.video_providers_enabled
        or not settings.video_tao_tts_enabled
        or not settings.tao_api_key.get_secret_value()
    ):
        raise ApiError(503, "VIDEO_TTS_NOT_CONFIGURED", "MiniMax 配音尚未配置。")
    voice = {
        "voice_id": selection["voice_id"],
        "speed": selection["speed"],
        "vol": 1,
        "pitch": 0,
    }
    if selection.get("emotion"):
        voice["emotion"] = selection["emotion"]
    body = {
        "model": selection["model"],
        "input": text,
        "voice": selection["voice_id"],
        "speed": selection["speed"],
        "response_format": "mp3",
        "metadata": {
            "voice_setting": voice,
            "language_boost": selection["language_boost"],
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + str(uuid4()) + ".part")
    try:
        with (
            httpx.Client(
                timeout=httpx.Timeout(180, connect=15),
                transport=transport,
                follow_redirects=False,
            ) as client,
            client.stream(
                "POST",
                "https://newapi.qwqtao.one/v1/audio/speech",
                headers={
                    "Authorization": "Bearer " + settings.tao_api_key.get_secret_value()
                },
                json=body,
            ) as response,
        ):
            if not response.is_success:
                raise ApiError(
                    502,
                    "VIDEO_PROVIDER_OUTCOME_UNKNOWN"
                    if response.status_code >= 500 or response.status_code == 408
                    else "VIDEO_PROVIDER_REJECTED",
                    "配音供应商未返回成功音频。",
                )
            if response.headers.get("content-type", "").split(";")[0] not in {
                "audio/mpeg",
                "audio/mp3",
                "application/octet-stream",
            }:
                raise ApiError(
                    502,
                    "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                    "配音响应格式未能确认，请勿重复提交。",
                )
            size = 0
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 50 * 1024 * 1024:
                        raise ApiError(
                            502,
                            "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                            "配音结果超过处理限制，请核对原请求。",
                        )
                    output.write(chunk)
            if size == 0:
                raise ApiError(
                    502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "配音供应商返回空音频。"
                )
            temporary.replace(target)
    except (httpx.HTTPError, OSError, ValueError):
        raise ApiError(
            502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "配音响应未能确认，请勿重复提交。"
        ) from None
    finally:
        temporary.unlink(missing_ok=True)
    rate = (
        Decimal("120") if selection["model"] == "speech-2.8-turbo" else Decimal("210")
    )
    # This is an estimate, not an actual usage/billing receipt.
    return {
        "provider": "tao",
        "model": selection["model"],
        "input_characters": len(text),
        "estimated_cny": str(rate * len(text) / 1_000_000),
        "actual_cny": None,
        "billing_status": "estimate_only",
    }
