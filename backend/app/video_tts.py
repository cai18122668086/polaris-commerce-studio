"""MiniMax system voices: Hashsight first, then one Tao fallback submission."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .config import Settings
from .errors import ApiError

MAX_AUDIO_BYTES = 50 * 1024 * 1024


def synthesize(
    settings: Settings,
    selection: dict[str, Any],
    text: str,
    target: Path,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    if not settings.video_providers_enabled:
        raise ApiError(503, "VIDEO_TTS_NOT_CONFIGURED", "MiniMax 配音尚未配置。")
    primary_error = None
    if (
        settings.video_hashsight_tts_enabled
        and settings.video_hashsight_api_key.get_secret_value()
    ):
        try:
            audio, receipt = _hashsight(settings, selection, text, transport)
        except ApiError as error:
            primary_error = error
        else:
            # A local persistence failure must not trigger a second billable call.
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + "." + str(uuid4()) + ".part")
            try:
                temporary.write_bytes(audio)
                temporary.replace(target)
            except OSError:
                raise ApiError(
                    502,
                    "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                    "配音保存失败，请核对原请求。",
                ) from None
            finally:
                temporary.unlink(missing_ok=True)
            return receipt
    if settings.video_tao_tts_enabled and settings.tao_api_key.get_secret_value():
        try:
            receipt = _synthesize_tao(settings, selection, text, target, transport)
        except ApiError as error:
            # Preserve an uncertain primary result even if the fallback rejects.
            if primary_error and primary_error.code == "VIDEO_PROVIDER_OUTCOME_UNKNOWN":
                raise primary_error from None
            raise error from None
        if primary_error:
            receipt["fallback_from"] = "hashsight"
            receipt["primary_error_code"] = primary_error.code
        return receipt
    if primary_error:
        raise primary_error from None
    raise ApiError(503, "VIDEO_TTS_NOT_CONFIGURED", "MiniMax 配音尚未配置。")


def _hashsight(
    settings: Settings,
    selection: dict[str, Any],
    text: str,
    transport: httpx.BaseTransport | None,
) -> tuple[bytes, dict[str, Any]]:
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
        "text": text,
        "stream": False,
        "language_boost": selection["language_boost"],
        "voice_setting": voice,
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
    }
    try:
        with (
            httpx.Client(
                timeout=httpx.Timeout(90, connect=15),
                transport=transport,
                follow_redirects=False,
            ) as client,
            client.stream(
                "POST",
                "https://ai.hashsight.org/v1/t2a_v2",
                headers={
                    "Authorization": "Bearer "
                    + settings.video_hashsight_api_key.get_secret_value(),
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
                    "主配音渠道未返回成功音频。",
                )
            encoded = bytearray()
            for chunk in response.iter_bytes():
                encoded.extend(chunk)
                if len(encoded) > MAX_AUDIO_BYTES * 2 + 1024 * 1024:
                    raise ValueError("Response too large")
            data = json.loads(encoded)
            if not isinstance(data, dict):
                raise ValueError("Invalid response")
            status = data.get("base_resp")
            if (
                not isinstance(status, dict)
                or type(status.get("status_code")) is not int
            ):
                raise ValueError("Missing provider status")
            if status["status_code"] != 0:
                raise ApiError(
                    502, "VIDEO_PROVIDER_REJECTED", "主配音渠道拒绝了本次合成。"
                )
            payload = data.get("data")
            audio_hex = payload.get("audio") if isinstance(payload, dict) else None
            if not isinstance(audio_hex, str) or len(audio_hex) > MAX_AUDIO_BYTES * 2:
                raise ValueError("Invalid audio")
            audio = bytes.fromhex(audio_hex)
            if not audio:
                raise ValueError("Empty audio")
    except (httpx.HTTPError, ValueError):
        raise ApiError(
            502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "主配音渠道响应未能确认。"
        ) from None
    extra = data.get("extra_info")
    usage = extra.get("usage_characters") if isinstance(extra, dict) else None
    return audio, {
        "provider": "hashsight",
        "model": selection["model"],
        "input_characters": len(text),
        "usage_characters": usage if type(usage) is int and usage >= 0 else None,
        "estimated_cny": None,
        "actual_cny": None,
        "billing_status": "unreconciled",
    }


def _synthesize_tao(
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
