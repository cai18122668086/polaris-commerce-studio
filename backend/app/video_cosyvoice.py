"""Official CosyVoice HTTP adapter. No redirects or automatic POST retries."""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from mutagen.mp3 import MP3, MPEGInfo

from .config import Settings
from .errors import ApiError
from .video_voice_models import VideoClonedVoiceRecord

MODEL = "cosyvoice-v3.5-flash"
PREVIEW_TEXT = "你好，这是我的专属声音。用自然的表达，讲好每一个故事。"
CONSENT_VERSION = "own-voice-2026-11-05"
LANGUAGES = {
    "auto": "自动识别文案语言",
    "Chinese": "普通话",
    "Chinese,Yue": "粤语",
    "English": "英语",
    "French": "法语",
    "German": "德语",
    "Japanese": "日语",
    "Korean": "韩语",
    "Russian": "俄语",
    "Portuguese": "葡萄牙语",
    "Thai": "泰语",
    "Indonesian": "印尼语",
    "Vietnamese": "越南语",
}
HINTS = dict(
    zip(
        list(LANGUAGES)[1:],
        ["zh", "zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi"],
        strict=True,
    )
)
EMOTIONS = {
    "自然": "",
    "平静": "请用平静自然的语气讲述。",
    "愉快": "请用愉快的语气讲述。",
    "悲伤": "请用悲伤的语气讲述。",
    "愤怒": "请用愤怒的语气讲述。",
    "害怕": "请用害怕的语气讲述。",
    "厌恶": "请用厌恶的语气讲述。",
    "惊讶": "请用惊讶的语气讲述。",
}


def ready(settings: Settings) -> bool:
    return bool(
        settings.video_providers_enabled
        and settings.video_cosyvoice_enabled
        and settings.video_cosyvoice_api_key.get_secret_value()
        and (
            settings.video_cosyvoice_platform == "qianwen"
            or settings.video_cosyvoice_workspace_id
        )
    )


def account_scope(settings: Settings) -> str:
    return (
        settings.video_cosyvoice_platform + ":" + settings.video_cosyvoice_workspace_id
    )


def api_url(settings: Settings, path: str) -> str:
    if not ready(settings):
        raise ApiError(
            503, "VIDEO_CLONE_NOT_CONFIGURED", "专属声音服务尚未配置，请联系管理员。"
        )
    if settings.video_cosyvoice_platform == "qianwen":
        return f"https://maas.qianwenaiapi.com/api/v1/services/audio/tts/{path}"
    return f"https://{settings.video_cosyvoice_workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/{path}"


class CosyVoice:
    def __init__(
        self, settings: Settings, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.settings = settings
        self.transport = transport

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = api_url(self.settings, path)
        try:
            with (
                httpx.Client(
                    timeout=httpx.Timeout(180, connect=15),
                    transport=self.transport,
                    follow_redirects=False,
                ) as client,
                client.stream(
                    "POST",
                    url,
                    json=body,
                    headers={
                        "Authorization": "Bearer "
                        + self.settings.video_cosyvoice_api_key.get_secret_value(),
                    },
                ) as response,
            ):
                if not response.is_success:
                    raise ApiError(
                        502,
                        "VIDEO_PROVIDER_OUTCOME_UNKNOWN"
                        if response.status_code >= 500 or response.status_code == 408
                        else "VIDEO_PROVIDER_REJECTED",
                        "声音服务未返回成功结果，请查看原任务。",
                    )
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 1024 * 1024:
                        raise ValueError()
                    chunks.append(chunk)
                data = json.loads(b"".join(chunks))
            if (
                not isinstance(data, dict)
                or data.get("code")
                or not isinstance(data.get("output"), dict)
            ):
                raise ValueError()
            return data
        except (httpx.HTTPError, ValueError, TypeError):
            raise ApiError(
                502,
                "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                "声音服务结果尚未确认，请勿重复提交。",
            ) from None

    def create(self, row: VideoClonedVoiceRecord) -> str:
        audio = "data:audio/wav;base64," + base64.b64encode(
            Path(row.sample_path).read_bytes()
        ).decode("ascii")
        data = self.post(
            "customization",
            {
                "model": "voice-enrollment",
                "input": {
                    "action": "create_voice",
                    "target_model": row.model,
                    "prefix": row.prefix,
                    "audio": audio,
                    "language_hints": ["zh"],
                    "max_prompt_audio_length": 20,
                },
            },
        )
        voice_id = data["output"].get("voice_id")
        if (
            not isinstance(voice_id, str)
            or not voice_id.startswith(row.model + "-" + row.prefix + "-")
            or len(voice_id) > 240
        ):
            raise ApiError(
                502,
                "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                "克隆结果尚未确认，请查询原任务。",
            )
        return voice_id

    def query(self, voice_id: str) -> dict[str, Any]:
        return self.post(
            "customization",
            {
                "model": "voice-enrollment",
                "input": {"action": "query_voice", "voice_id": voice_id},
            },
        )["output"]

    def find(self, row: VideoClonedVoiceRecord) -> str | None:
        result = self.post(
            "customization",
            {
                "model": "voice-enrollment",
                "input": {
                    "action": "list_voice",
                    "prefix": row.prefix,
                    "page_size": 100,
                    "page_index": 0,
                },
            },
        )
        candidates = [
            v["voice_id"]
            for v in result["output"].get("voice_list", [])
            if isinstance(v, dict)
            and isinstance(v.get("voice_id"), str)
            and v["voice_id"].startswith(row.model + "-" + row.prefix + "-")
        ]
        return candidates[0] if len(candidates) == 1 else None

    def synthesize(
        self, selection: dict[str, Any], text: str, target: Path
    ) -> dict[str, Any]:
        if selection.get("model", MODEL) != MODEL or selection.get(
            "provider_workspace", account_scope(self.settings)
        ) != account_scope(self.settings):
            raise ApiError(
                409,
                "VIDEO_CLONE_ACCOUNT_CHANGED",
                "声音服务账号或模型已变化，请联系管理员。",
            )
        inputs = {
            "text": text,
            "voice": selection["voice_id"],
            "format": "mp3",
            "sample_rate": 24000,
            "rate": selection["speed"],
        }
        if selection.get("instruction"):
            inputs["instruction"] = selection["instruction"]
        hint = HINTS.get(selection.get("language_boost") or "")
        if hint:
            inputs["language_hints"] = [hint]
        data = self.post("SpeechSynthesizer", {"model": MODEL, "input": inputs})
        url = data["output"].get("audio", {}).get("url", "")
        self.download(url, target)
        count = sum(
            2
            if "\u3400" <= c <= "\u9fff"
            or "\uf900" <= c <= "\ufaff"
            or ord(c) >= 0x20000
            and ord(c) <= 0x323AF
            else 1
            for c in text
        )
        return {
            "provider": "cosyvoice",
            "model": MODEL,
            "input_characters": count,
            "estimated_cny": str(Decimal(count) * Decimal("0.8") / 10000),
            "actual_cny": None,
            "billing_status": "estimate_only",
            "provider_request_id": data.get("request_id"),
            "provider_usage": data.get("usage", {}),
        }

    def download(self, url: str, target: Path) -> None:
        temporary = target.with_name(target.name + "." + str(uuid4()) + ".part")
        try:
            parts = urlsplit(url)
            if parts.scheme == "http" and (parts.hostname or "").endswith(
                ".aliyuncs.com"
            ):
                url = parts._replace(scheme="https").geturl()
                parts = urlsplit(url)
            if (
                parts.scheme != "https"
                or not (parts.hostname or "").endswith(".aliyuncs.com")
                or parts.username
                or parts.password
                or parts.port not in {None, 443}
            ):
                raise ValueError()
            target.parent.mkdir(parents=True, exist_ok=True)
            # Signed OSS URL, never forward API Authorization to media hosts.
            with (
                httpx.Client(
                    timeout=120, transport=self.transport, follow_redirects=False
                ) as client,
                client.stream("GET", url) as response,
            ):
                if response.status_code != 200:
                    raise ValueError()
                size = 0
                with temporary.open("wb") as output:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 50 * 1024 * 1024:
                            raise ValueError()
                        output.write(chunk)
            info = cast(MPEGInfo | None, MP3(temporary).info)
            if info is None or info.length <= 0:
                raise ValueError()
            temporary.replace(target)
        except Exception:
            raise ApiError(
                502,
                "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                "配音已提交但音频未能确认，请勿重复生成。",
            ) from None
        finally:
            temporary.unlink(missing_ok=True)
