"""voice_clone e2e (2026-11-25): the provider's 403 AccessDenied.Unpurchased was
discarded, the clone showed no reason, and nothing confirmed the hold was
released. Also covers the standard DashScope (Bailian) endpoint."""

import httpx
from pydantic import SecretStr

from app.config import Settings
from app.video_cosyvoice import (
    SERVICE_UNAVAILABLE,
    CosyVoice,
    api_url,
    provider_error,
    ready,
)
from tests.test_video_credit_billing_voice import fund, priced, state  # noqa: F401
from tests.test_video_generation import video_gen  # noqa: F401
from tests.test_video_voice_cloning import clone_env, create  # noqa: F401

UNPURCHASED = {
    "code": "AccessDenied.Unpurchased",
    "message": "Access to model denied.",
    "request_id": "req-1",
}


def dashscope_settings(**changes):
    return Settings(
        _env_file=None,
        video_providers_enabled=True,
        video_cosyvoice_enabled=True,
        video_cosyvoice_api_key=SecretStr("fixture-private-key"),
        video_cosyvoice_platform="dashscope",
        **changes,
    )


def test_dashscope_platform_uses_the_standard_endpoint_without_workspace():
    settings = dashscope_settings()
    assert ready(settings)
    assert api_url(settings, "customization") == (
        "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
    )
    assert api_url(settings, "SpeechSynthesizer").startswith(
        "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/"
    )


def test_every_cosyvoice_call_goes_to_dashscope():
    seen = []

    def handler(request):
        seen.append((request.url.host, request.url.path))
        action = request.read() and __import__("json").loads(request.content)
        action = action["input"].get("action")
        if action == "list_voice":
            return httpx.Response(200, json={"output": {"voice_list": []}})
        if action == "query_voice":
            return httpx.Response(200, json={"output": {"status": "OK"}})
        return httpx.Response(200, json={"output": {"voice_id": "x"}})

    voice = CosyVoice(dashscope_settings(), httpx.MockTransport(handler))
    voice.query("cosyvoice-v3.5-flash-p1-x")
    voice.post("customization", {"input": {"action": "list_voice"}})
    voice.post("SpeechSynthesizer", {"input": {"text": "你好"}})
    assert {host for host, _ in seen} == {"dashscope.aliyuncs.com"}
    assert {path.rsplit("/", 1)[-1] for _, path in seen} == {
        "customization",
        "SpeechSynthesizer",
    }


def test_unpurchased_maps_to_clear_chinese_message_with_provider_reason():
    error = provider_error(httpx.Response(403, json=UNPURCHASED))
    assert error.code == SERVICE_UNAVAILABLE
    assert error.message == "声音克隆服务暂未开通，请联系客服"
    assert error.details["provider_code"] == "AccessDenied.Unpurchased"
    assert error.details["provider_request_id"] == "req-1"
    other = provider_error(httpx.Response(400, json={"code": "Audio.TooShort"}))
    assert other.code == "VIDEO_PROVIDER_REJECTED" and "Audio.TooShort" in other.message
    assert (
        provider_error(httpx.Response(503, text="busy")).code
        == "VIDEO_PROVIDER_OUTCOME_UNKNOWN"
    )


def test_unpurchased_clone_fails_visibly_and_releases_the_hold(priced):  # noqa: F811
    env, ws = priced
    client, _, _, root, _, _, calls = env
    fund(client, ws, 100)
    calls["mode"] = "unpurchased"
    created = create(env)
    assert created.status_code == 200, created.text
    listed = client.get(root + "/voice-clones").json()
    assert [(v["status"], v["error_code"], v["error_message"]) for v in listed] == [
        ("failed", SERVICE_UNAVAILABLE, "声音克隆服务暂未开通，请联系客服")
    ]
    # Not charged: the hold is released and the balance is unchanged.
    assert state(client, ws) == ((100, 0), [("voice_clone", "released")])
    assert calls["created"] == []
