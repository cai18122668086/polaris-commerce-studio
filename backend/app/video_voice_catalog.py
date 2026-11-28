"""Pinned official system voices; catalogue membership is not provider acceptance."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import Settings
from .video_voice_names import clean_original, minimax_display

EMOTIONS = ["自然", "平静", "愉快", "悲伤", "愤怒", "害怕", "厌恶", "惊讶"]
EMOTION_CODES = dict(
    zip(
        EMOTIONS[1:],
        ["calm", "happy", "sad", "angry", "fearful", "disgusted", "surprised"],
        strict=True,
    )
)
LANGUAGES = {
    "auto": "自动识别文案语言",
    "Chinese": "普通话",
    "Chinese,Yue": "粤语",
    "English": "英语",
    "Arabic": "阿拉伯语",
    "Russian": "俄语",
    "Spanish": "西班牙语",
    "French": "法语",
    "Portuguese": "葡萄牙语",
    "German": "德语",
    "Turkish": "土耳其语",
    "Dutch": "荷兰语",
    "Ukrainian": "乌克兰语",
    "Vietnamese": "越南语",
    "Indonesian": "印尼语",
    "Japanese": "日语",
    "Italian": "意大利语",
    "Korean": "韩语",
    "Thai": "泰语",
    "Polish": "波兰语",
    "Romanian": "罗马尼亚语",
    "Greek": "希腊语",
    "Czech": "捷克语",
    "Finnish": "芬兰语",
    "Hindi": "印地语",
    "Bulgarian": "保加利亚语",
    "Danish": "丹麦语",
    "Hebrew": "希伯来语",
    "Malay": "马来语",
    "Persian": "波斯语",
    "Slovak": "斯洛伐克语",
    "Swedish": "瑞典语",
    "Croatian": "克罗地亚语",
    "Filipino": "菲律宾语",
    "Hungarian": "匈牙利语",
    "Norwegian": "挪威语",
    "Slovenian": "斯洛文尼亚语",
    "Catalan": "加泰罗尼亚语",
    "Nynorsk": "新挪威语",
    "Tamil": "泰米尔语",
    "Afrikaans": "南非荷兰语",
}


def voice_key(voice_id: str) -> str:
    return "mm-voice-" + hashlib.sha256(voice_id.encode()).hexdigest()[:20]


CATALOG = json.loads(
    (Path(__file__).parent / "data/minimax-system-voices.json").read_text(
        encoding="utf-8"
    )
)
VOICES = {voice_key(v["voice_id"]): v for v in CATALOG["voices"]}


def referenced_voice_ids(
    session: Any, workspace_id: str, owner_user_id: str
) -> set[str]:
    """本工作区固定形象、作品条目、历史口播任务用过的声音 id。

    隐藏的声音（角色化 / beta 重复等）只要被引用过就照常放回列表，保证旧搭配可用。
    只取 voice_id 列和 JSON 里的单个字段，PostgreSQL / SQLite 都能跑。
    """
    from sqlalchemy import select

    from .video_generation_models import VideoGenerationRecord
    from .video_persona_models import VideoPersonaRecord
    from .video_work_models import VideoWorkItemRecord

    ids: set[str] = set()
    for model in (VideoPersonaRecord, VideoWorkItemRecord):
        ids.update(
            session.scalars(
                select(model.voice_id)
                .where(
                    model.workspace_id == workspace_id,
                    model.owner_user_id == owner_user_id,
                    model.voice_id.is_not(None),
                )
                .distinct()
            )
        )
    raw = session.scalars(
        select(VideoGenerationRecord.details["tts"]["voice_id"].as_string())
        .where(
            VideoGenerationRecord.workspace_id == workspace_id,
            VideoGenerationRecord.owner_user_id == owner_user_id,
        )
        .distinct()
    )
    ids.update(voice_key(value) for value in raw if value)
    return {value for value in ids if value}


def tao_ready(settings: Settings) -> bool:
    return bool(
        settings.video_providers_enabled
        and (
            settings.video_hashsight_tts_enabled
            and settings.video_hashsight_api_key.get_secret_value()
            or settings.video_tao_tts_enabled
            and settings.tao_api_key.get_secret_value()
        )
    )


def preview_path(settings: Settings, key: str, model: str | None = None) -> Path:
    # Keys are looked up in VOICES by callers, never used as arbitrary paths.
    return (
        settings.video_media_dir
        / "voice-previews"
        / (model or settings.video_tao_tts_model)
        / (key + ".mp3")
    )


def official_voices(
    settings: Settings, root: str, include: set[str] | frozenset[str] = frozenset()
) -> list[dict[str, Any]]:
    """系统声音列表。显示名来自 video_voice_names；隐藏的声音只有在 include
    （被固定形象 / 作品条目 / 历史任务引用）里时才放回，显示供应商原名。"""
    available = tao_ready(settings)
    result = []
    for key, v in VOICES.items():
        shown = minimax_display(v)
        if shown is None and key not in include:
            continue
        result.append(
            {
                "id": key,
                "name": shown["name"] if shown else clean_original(v["name"]),
                "gender": shown["gender"] if shown else voice_gender(v),
                "tag": v["language"],
                "description": shown["description"] if shown else "系统声音",
                "provider": "tao",
                "available": available,
                "language": v["language"],
                "emotions": EMOTIONS,
                "languages": LANGUAGES,
                "preview_url": root + f"/voices/{key}/preview"
                if preview_path(settings, key).is_file()
                else None,
            }
        )
    return result


def voice_gender(voice: dict[str, Any]) -> str:
    # Only explicit gendered labels in the published name/ID are classified.
    # Neutral/ambiguous voice names remain unlabelled.
    text = voice["name"] + " " + voice["voice_id"].replace("_", " ").replace("-", " ")
    if re.search(
        r"\b(female|woman|girl|lady|sister|mother|aunt|queen|princess)\b", text, re.I
    ) or any(
        word in voice["name"]
        for word in ["女", "闺蜜", "姐", "奶奶", "大婶", "阿姨", "空姐", "小姐"]
    ):
        return "女"
    if re.search(
        r"\b(male|man|boy|gentleman|brother|father|uncle|king|prince)\b", text, re.I
    ) or any(
        word in voice["name"]
        for word in ["男", "弟", "哥", "大爷", "小伙", "少爷", "学长", "竹马"]
    ):
        return "男"
    return "未知"


def select_tao_voice(settings: Settings, draft: dict[str, Any]) -> dict[str, Any]:
    voice = VOICES.get(draft["voiceId"])
    if not voice or not tao_ready(settings):
        from .errors import ApiError

        raise ApiError(
            503,
            "VIDEO_TTS_NOT_CONFIGURED",
            "MiniMax 配音尚未配置，请选择现有公共音色。",
        )
    emotion = draft.get("emotion", "自然")
    language = draft.get("language", "auto")
    if language == "auto" and voice["language"] == "中文 (粤语)":
        language = "Chinese,Yue"
    if emotion not in EMOTIONS or language not in LANGUAGES:
        from .errors import ApiError

        raise ApiError(
            422, "VIDEO_VOICE_SETTING_INVALID", "请选择此音色支持的情绪与语言。"
        )
    return {
        "provider": "tao",
        "model": settings.video_tao_tts_model,
        "voice_id": voice["voice_id"],
        "voice_name": voice["name"],
        "speed": draft["speed"],
        "emotion": EMOTION_CODES.get(emotion),
        "language_boost": language,
    }
