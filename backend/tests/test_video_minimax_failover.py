import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.errors import ApiError
from app.video_tts import synthesize
from app.video_voice_catalog import official_voices, select_tao_voice, voice_key

PRIMARY = "https://ai.hashsight.org/v1/t2a_v2"
BACKUP = "https://newapi.qwqtao.one/v1/audio/speech"
SELECTION = {
    "voice_id": "Cantonese_GentleLady",
    "speed": 1.2,
    "model": "speech-2.8-turbo",
    "emotion": "happy",
    "language_boost": "Chinese,Yue",
}
AUDIO = b"ID3-audio-fixture"


def settings(**changes):
    return Settings(
        _env_file=None,
        **{
            "video_providers_enabled": True,
            "video_hashsight_tts_enabled": True,
            "video_hashsight_api_key": "primary-fixture",
            "video_tao_tts_enabled": True,
            "tao_api_key": "backup-fixture",
            **changes,
        },
    )


def success():
    return httpx.Response(
        200,
        json={
            "base_resp": {"status_code": 0},
            "data": {"audio": AUDIO.hex()},
            "extra_info": {"usage_characters": 12},
        },
    )


@pytest.mark.parametrize("model", ["speech-2.8-turbo", "speech-2.8-hd"])
def test_primary_official_payload_receipt_and_no_backup(tmp_path, model):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert str(request.url) == PRIMARY
        assert request.headers["Authorization"] == "Bearer primary-fixture"
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {
            "model": model,
            "text": "你好，世界！",
            "stream": False,
            "language_boost": "Chinese,Yue",
            "voice_setting": {
                "voice_id": SELECTION["voice_id"],
                "speed": 1.2,
                "vol": 1,
                "pitch": 0,
                "emotion": "happy",
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
            },
        }
        return success()

    target = tmp_path / "audio.mp3"
    receipt = synthesize(
        settings(),
        {**SELECTION, "model": model},
        "你好，世界！",
        target,
        httpx.MockTransport(handler),
    )
    assert calls == [PRIMARY]
    assert target.read_bytes() == AUDIO
    assert receipt["provider"] == "hashsight"
    assert receipt["usage_characters"] == 12
    assert receipt["input_characters"] == 6
    assert receipt["actual_cny"] is None and receipt["estimated_cny"] is None
    assert not list(tmp_path.glob("*.part"))


def primary_failure(mode, request):
    if mode == "timeout":
        raise httpx.ReadTimeout("secret-upstream-body", request=request)
    if mode == "connect":
        raise httpx.ConnectError("secret-upstream-body", request=request)
    if mode == "504":
        return httpx.Response(504, text="secret-upstream-body")
    if mode == "401":
        return httpx.Response(401, text="secret-upstream-body")
    if mode == "redirect":
        return httpx.Response(302, headers={"location": "https://untrusted.invalid"})
    if mode == "invalid_json":
        return httpx.Response(200, text="secret-upstream-body")
    payload = {
        "base_resp": {"status_code": 0},
        "data": {"audio": AUDIO.hex()},
    }
    if mode == "business":
        payload["base_resp"]["status_code"] = 2013
    elif mode == "missing_status":
        del payload["base_resp"]
    elif mode == "invalid_hex":
        payload["data"]["audio"] = "xyz"
    elif mode == "empty":
        payload["data"]["audio"] = ""
    elif mode == "missing_audio":
        payload["data"] = None
    elif mode == "wrong_shape":
        return httpx.Response(200, json=[])
    elif mode == "oversize":
        return httpx.Response(200, content=b"x" * 66)
    return httpx.Response(200, json=payload)


@pytest.mark.parametrize(
    "mode",
    [
        "504",
        "401",
        "timeout",
        "connect",
        "redirect",
        "business",
        "invalid_json",
        "missing_status",
        "invalid_hex",
        "empty",
        "missing_audio",
        "wrong_shape",
        "oversize",
    ],
)
def test_primary_failure_falls_back_once_with_unchanged_settings(
    tmp_path, mode, monkeypatch
):
    calls = []
    if mode == "oversize":
        monkeypatch.setattr("app.video_tts.MAX_AUDIO_BYTES", 1)

    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == PRIMARY:
            return primary_failure(mode, request)
        assert str(request.url) == BACKUP
        assert request.headers["Authorization"] == "Bearer backup-fixture"
        body = json.loads(request.content)
        assert body["model"] == SELECTION["model"]
        assert body["input"] == "原始文案"
        assert body["metadata"]["language_boost"] == "Chinese,Yue"
        assert body["metadata"]["voice_setting"]["emotion"] == "happy"
        assert body["voice"] == SELECTION["voice_id"] and body["speed"] == 1.2
        return httpx.Response(
            200, headers={"content-type": "audio/mpeg"}, content=AUDIO
        )

    target = tmp_path / "audio.mp3"
    receipt = synthesize(
        settings(), SELECTION, "原始文案", target, httpx.MockTransport(handler)
    )
    assert calls == [PRIMARY, BACKUP]
    assert target.read_bytes() == AUDIO
    assert receipt["provider"] == "tao" and receipt["fallback_from"] == "hashsight"
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("backup_status", [400, 504])
def test_both_fail_no_loop_no_partial_audio_and_preserve_unknown(
    tmp_path, backup_status
):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(504 if str(request.url) == PRIMARY else backup_status)

    target = tmp_path / "audio.mp3"
    with pytest.raises(ApiError) as error:
        synthesize(settings(), SELECTION, "原稿", target, httpx.MockTransport(handler))
    assert error.value.code == "VIDEO_PROVIDER_OUTCOME_UNKNOWN"
    assert calls == [PRIMARY, BACKUP]
    assert not target.exists() and not list(tmp_path.glob("*.part"))
    assert "fixture" not in str(error.value)


def test_primary_only_configuration_keeps_catalog_and_selection_available(tmp_path):
    config = settings(video_tao_tts_enabled=False, tao_api_key="")
    assert all(v["available"] for v in official_voices(config, "/voices"))
    selection = select_tao_voice(
        config,
        {
            "voiceId": voice_key("Cantonese_GentleLady"),
            "speed": 1,
            "language": "auto",
        },
    )
    assert selection["language_boost"] == "Chinese,Yue"
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(504)

    with pytest.raises(ApiError):
        synthesize(
            config, selection, "文案", tmp_path / "a.mp3", httpx.MockTransport(handler)
        )
    assert calls == [PRIMARY]


def test_global_switch_disables_both_channels(tmp_path):
    def handler(request):
        pytest.fail("Disabled provider was called")

    config = settings(video_providers_enabled=False)
    assert not any(v["available"] for v in official_voices(config, "/voices"))
    with pytest.raises(ApiError) as error:
        synthesize(
            config, SELECTION, "文案", tmp_path / "a.mp3", httpx.MockTransport(handler)
        )
    assert error.value.code == "VIDEO_TTS_NOT_CONFIGURED"


def test_local_persistence_failure_does_not_call_backup(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return success()

    def fail_write(*args, **kwargs):
        raise OSError("Disk full")

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    with pytest.raises(ApiError):
        synthesize(
            settings(),
            SELECTION,
            "文案",
            tmp_path / "a.mp3",
            httpx.MockTransport(handler),
        )
    assert calls == [PRIMARY] and not list(tmp_path.glob("*.part"))
