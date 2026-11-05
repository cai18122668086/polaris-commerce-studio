import io
import json
import wave
import zipfile
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.errors import ApiError
from app.video_tts import synthesize
from app.video_voice_catalog import VOICES, preview_path, voice_key
from tests.test_video_generation import request_body

pytest_plugins = ["tests.test_video_generation"]

KEY = voice_key("Chinese (Mandarin)_Warm_Bestie")


def speech_settings():
    return Settings(
        _env_file=None,
        video_providers_enabled=True,
        video_tao_tts_enabled=True,
        tao_api_key="fixture-not-secret",
    )


def test_tao_forwards_full_voice_settings_and_omits_auto_emotion(tmp_path):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        assert request.url == "https://newapi.qwqtao.one/v1/audio/speech"
        assert request.headers["Authorization"] == "Bearer fixture-not-secret"
        return httpx.Response(
            200, headers={"content-type": "audio/mpeg"}, content=b"ID3-audio-fixture"
        )

    selection = {
        "voice_id": VOICES[KEY]["voice_id"],
        "speed": 1.2,
        "model": "speech-2.8-turbo",
        "emotion": None,
        "language_boost": "auto",
    }
    target = tmp_path / "voice.mp3"
    receipt = synthesize(
        speech_settings(), selection, "你好", target, httpx.MockTransport(handler)
    )
    assert target.read_bytes() == b"ID3-audio-fixture"
    assert seen[0]["metadata"] == {
        "voice_setting": {
            "voice_id": selection["voice_id"],
            "speed": 1.2,
            "vol": 1,
            "pitch": 0,
        },
        "language_boost": "auto",
    }
    assert receipt["actual_cny"] is None and receipt["estimated_cny"] == "0.00024"
    synthesize(
        speech_settings(),
        {**selection, "emotion": "happy", "language_boost": "English"},
        "Hello",
        target,
        httpx.MockTransport(handler),
    )
    assert seen[1]["metadata"]["voice_setting"]["emotion"] == "happy"
    assert seen[1]["metadata"]["language_boost"] == "English"


@pytest.mark.parametrize("mode", ["timeout", "json", "empty", "500", "redirect"])
def test_tao_unknown_outcome_is_single_submit_and_never_publishes_audio(tmp_path, mode):
    calls = []

    def handler(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("fixture")
        return {
            "json": httpx.Response(200, json={"token": "must-not-leak"}),
            "empty": httpx.Response(
                200, headers={"content-type": "audio/mpeg"}, content=b""
            ),
            "500": httpx.Response(500),
            "redirect": httpx.Response(
                302, headers={"location": "https://untrusted.invalid"}
            ),
        }[mode]

    target = tmp_path / "voice.mp3"
    with pytest.raises(ApiError) as error:
        synthesize(
            speech_settings(),
            {
                "voice_id": "v",
                "speed": 1,
                "model": "speech-2.8-turbo",
                "language_boost": "auto",
            },
            "text",
            target,
            httpx.MockTransport(handler),
        )
    assert len(calls) == 1 and not target.exists()
    assert not list(tmp_path.glob("*.part"))
    assert "must-not-leak" not in str(error.value)


def configure_tao(client, root, pid, **draft_values):
    settings = client.app.state.settings
    settings.video_tao_tts_enabled = True
    settings.tao_api_key = SecretStr("fixture")
    project = client.get(root + "/projects/" + pid).json()
    project["content"]["draft"].update(
        voiceId=KEY, emotion="愉快", language="auto", **draft_values
    )
    result = client.put(
        root + "/projects/" + pid,
        json={
            "request_id": str(uuid4()),
            "expected_revision": project["revision"],
            "content": project["content"],
        },
    )
    assert result.status_code == 200, result.text
    return result.json()["project"]["revision"]


def fake_synthesis(calls):
    def run(settings, selection, text, target, transport=None):
        calls.append((selection, text))
        target.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(b"\0\0" * 16000)
        return {"estimated_cny": "0.001", "actual_cny": None}

    return run


def test_tao_pipeline_freezes_settings_recovers_upload_and_exports_exact_script(
    video_gen, monkeypatch
):
    client, auth, provider, root, pid, _ = video_gen
    revision = configure_tao(client, root, pid)
    calls = []
    monkeypatch.setattr("app.video_generation.synthesize", fake_synthesis(calls))
    upload = provider.upload
    failed_once = False

    def fail_upload(path, mime, purpose):
        nonlocal failed_once
        if not failed_once and purpose == "digital_human_audio":
            failed_once = True
            raise ApiError(502, "VIDEO_UPLOAD_FAILED", "fixture")
        return upload(path, mime, purpose)

    provider.upload = fail_upload
    body = {**request_body(pid), "expected_revision": revision}
    response = client.post(root + "/generation-tasks", json=body)
    job_id = response.json()["id"]
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["stage"] == "uploading_tts_audio" and job["can_resume"]
    assert len(calls) == 1 and calls[0][0]["emotion"] == "happy"
    assert calls[0][0]["language_boost"] == "auto"
    assert not any(path == "/api/tts/generate" for _, path, _ in provider.posts)
    assert client.post(root + f"/generation-tasks/{job_id}/resume").status_code == 200
    assert client.post(root + "/generation-tasks", json=body).status_code == 200
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "completed" and len(calls) == 1
    assert job["audio_duration_seconds"] == 1
    assert all(
        stage["finished_at"] and stage["duration_seconds"] >= 0
        for stage in job["stage_history"]
    )
    original = job["snapshot"]["draft"]["text"]
    configure_tao(client, root, pid, text="这是后来修改的文案")
    bundle = client.get(job["handoff_url"])
    assert bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert archive.read("confirmed-script.txt").decode() == original
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["confirmed_version_id"] == job["confirmed_version_id"]
        assert manifest["subtitles"]["status"] == "pending_alignment"
        assert manifest["idempotency_key"] == job_id
        assert archive.read("narration.mp3") and archive.read("talking-head.mp4")
        assert "fixture" not in json.dumps(manifest)
    assert not list(
        (client.app.state.settings.video_media_dir / "handoffs").glob("*.zip")
    )
    auth.identity = replace(auth.identity, email="outside@example.com")
    assert client.get(job["handoff_url"]).status_code == 404


def test_preview_is_cached_authorized_and_does_not_synthesize(video_gen):
    client, auth, provider, root, _, _ = video_gen
    path = preview_path(client.app.state.settings, KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"sample")
    voices = client.get(root + "/voices").json()
    official = [v for v in voices if v["id"] in VOICES]
    assert len(official) == 327 and not official[0]["available"]
    voice = next(v for v in official if v["id"] == KEY)
    assert "whisper" not in voice["emotions"]
    assert client.get(voice["preview_url"]).content == b"sample"
    assert client.get(voice["preview_url"]).content == b"sample" and not provider.posts
    auth.identity = replace(auth.identity, email="outside@example.com")
    assert client.get(voice["preview_url"]).status_code == 404


def test_preview_batch_does_not_repeat_unknown_paid_attempt(tmp_path, monkeypatch):
    from scripts import prepare_voice_previews as previews

    settings = speech_settings().model_copy(update={"video_media_dir": tmp_path})
    calls = []

    def unknown(*args):
        calls.append(args)
        raise ApiError(502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "fixture")

    monkeypatch.setattr(previews, "synthesize", unknown)
    previews.prepare(settings, generate=True, keys=[KEY])
    previews.prepare(settings, generate=True, keys=[KEY])
    assert len(calls) == 1
    assert preview_path(settings, KEY).with_suffix(".intent").is_file()
    assert not preview_path(settings, KEY).is_file()


def test_preview_batch_reuses_completed_sample(tmp_path, monkeypatch):
    from scripts import prepare_voice_previews as previews

    settings = speech_settings().model_copy(update={"video_media_dir": tmp_path})
    calls = []
    monkeypatch.setattr(previews, "synthesize", fake_synthesis(calls))
    previews.prepare(settings, generate=True, keys=[KEY])
    previews.prepare(settings, generate=True, keys=[KEY])
    assert len(calls) == 1
    assert preview_path(settings, KEY).is_file()
