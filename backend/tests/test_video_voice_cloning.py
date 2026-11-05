import io
import json
import math
import struct
import subprocess
import wave
import zipfile
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import imageio_ffmpeg
import pytest
from pydantic import SecretStr

from app.errors import ApiError
from app.video_cosyvoice import CONSENT_VERSION, MODEL, CosyVoice
from app.video_generation_models import VideoGenerationRecord
from app.video_voice_models import VideoClonedVoiceRecord
from tests.test_video_generation import request_body

pytest_plugins = ["tests.test_video_generation"]


def sample(seconds=6):
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(
            b"".join(
                struct.pack("<h", int(1000 * math.sin(i * 0.1)))
                for i in range(24000 * seconds)
            )
        )
    return data.getvalue()


@pytest.fixture
def clone_env(video_gen, tmp_path):
    client, auth, provider, root, pid, user = video_gen
    settings = client.app.state.settings
    settings.video_cosyvoice_enabled = True
    settings.video_cosyvoice_api_key = SecretStr("fixture-private-key")
    state = {"created": [], "synthesis": [], "query": [], "mode": "ok", "status": "OK"}
    mp3 = tmp_path / "fixture.mp3"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            str(mp3),
        ],
        check=True,
    )

    def handler(req):
        if req.method == "GET":
            assert "authorization" not in req.headers
            if state["mode"] == "media_bad":
                return httpx.Response(302, headers={"location": "https://evil.invalid"})
            return httpx.Response(200, content=mp3.read_bytes())
        assert req.url.host == "maas.qianwenaiapi.com"
        assert req.headers["authorization"] == "Bearer fixture-private-key"
        body = json.loads(req.content)
        inputs = body["input"]
        if inputs.get("action") == "create_voice":
            assert body["model"] == "voice-enrollment"
            assert inputs["audio"].startswith("data:audio/wav;base64,")
            assert inputs["target_model"] == MODEL
            vid = MODEL + "-" + inputs["prefix"] + "-fixture"
            state["created"].append(vid)
            if state["mode"] == "create_timeout":
                raise httpx.ReadTimeout("do-not-leak-private-key")
            return httpx.Response(200, json={"output": {"voice_id": vid}})
        if inputs.get("action") == "list_voice":
            return httpx.Response(
                200,
                json={
                    "output": {
                        "voice_list": [{"voice_id": v} for v in state["created"]]
                    }
                },
            )
        if inputs.get("action") == "query_voice":
            state["query"].append(inputs["voice_id"])
            return httpx.Response(
                200, json={"output": {"target_model": MODEL, "status": state["status"]}}
            )
        state["synthesis"].append(body)
        if state["mode"] == "tts_timeout":
            raise httpx.ReadTimeout("do-not-leak-private-key")
        return httpx.Response(
            200,
            json={
                "output": {
                    "audio": {
                        "url": "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.mp3"
                    }
                },
                "usage": {"characters": 10},
                "request_id": "fixture-request",
            },
        )

    transport = httpx.MockTransport(handler)
    client.app.state.video_cosyvoice = CosyVoice(settings, transport)
    provider.transport = transport
    return client, auth, provider, root, pid, user, state


def create(env, request_id=None, audio=None, **fields):
    client, _, _, root, *_ = env
    data = {
        "request_id": request_id or str(uuid4()),
        "name": "我的声音",
        "consent": CONSENT_VERSION,
        **fields,
    }
    return client.post(
        root + "/voice-clones",
        data=data,
        files={
            "file": ("sample.wav", sample() if audio is None else audio, "audio/wav")
        },
    )


def test_clone_idempotency_catalog_and_private_fields(clone_env):
    client, _, _, root, _, _, state = clone_env
    rid = str(uuid4())
    first = create(clone_env, rid)
    assert first.status_code == 200, first.text
    vid = first.json()["id"]
    assert create(clone_env, rid).json()["id"] == vid
    assert create(clone_env).json()["id"] == vid
    assert len(state["created"]) == 1
    status = client.get(root + "/voice-clones/" + vid)
    assert status.json()["status"] == "ready"
    assert (
        "fixture-private-key" not in status.text
        and state["created"][0] not in status.text
    )
    assert "sample_path" not in status.text and "source.wav" not in status.text
    assert create(clone_env, rid, name="另一个名称").status_code == 409
    voices = client.get(root + "/voices").json()
    own = next(v for v in voices if v["id"] == vid)
    assert own["available"] and own["source"] == "own" and own["preview_url"] is None
    assert not state["synthesis"]


@pytest.mark.parametrize("consent", ["", "false", "other"])
def test_requires_explicit_own_voice_consent(clone_env, consent):
    assert create(clone_env, consent=consent).status_code == 422
    assert not clone_env[-1]["created"]


@pytest.mark.parametrize("audio", [b"not-audio", sample(1), sample(62)])
def test_invalid_samples_never_reach_provider(clone_env, audio):
    assert create(clone_env, audio=audio).status_code == 422
    assert not clone_env[-1]["created"]


def test_disabled_and_oversize_are_rejected(clone_env):
    client = clone_env[0]
    client.app.state.settings.video_cosyvoice_enabled = False
    assert create(clone_env).status_code == 503
    client.app.state.settings.video_cosyvoice_enabled = True
    assert create(clone_env, audio=b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
    assert not clone_env[-1]["created"]


def test_unknown_creation_recovers_by_prefix_without_resubmission(clone_env):
    client, _, _, root, _, _, state = clone_env
    state["mode"] = "create_timeout"
    rid = str(uuid4())
    vid = create(clone_env, rid).json()["id"]
    assert client.get(root + "/voice-clones/" + vid).json()["status"] == "unknown"
    assert create(clone_env, rid).json()["id"] == vid
    assert len(state["created"]) == 1
    state["mode"] = "ok"
    result = client.post(root + f"/voice-clones/{vid}/refresh")
    assert result.json()["status"] == "ready"
    assert len(state["created"]) == 1


def test_preview_is_opt_in_and_cached_once(clone_env):
    client, _, _, root, _, _, state = clone_env
    vid = create(clone_env).json()["id"]
    path = root + f"/voice-clones/{vid}/preview"
    assert client.get(path).status_code == 404 and not state["synthesis"]
    assert client.post(path).status_code == 200
    for _ in range(2):
        assert client.post(path).status_code == 200
        assert client.get(path).status_code == 200
    assert len(state["synthesis"]) == 1
    status = client.get(root + "/voice-clones/" + vid).json()
    assert "preview_billing" not in status and "model" not in status
    with client.app.state.session_factory() as session:
        receipt = session.get(VideoClonedVoiceRecord, vid).details["preview_billing"]
        assert receipt["actual_cny"] is None
        assert receipt["provider_usage"] == {"characters": 10}


@pytest.mark.parametrize("mode", ["tts_timeout", "media_bad"])
def test_unknown_preview_never_resubmits(clone_env, mode):
    client, _, _, root, _, _, state = clone_env
    vid = create(clone_env).json()["id"]
    state["mode"] = mode
    path = root + f"/voice-clones/{vid}/preview"
    client.post(path)
    client.post(path)
    assert len(state["synthesis"]) == 1
    status = client.get(root + "/voice-clones/" + vid)
    assert status.json()["preview_status"] == "unknown"
    assert "do-not-leak" not in status.text


def test_real_generation_uses_exact_owned_clone_and_frozen_settings(clone_env):
    client, _, provider, root, pid, _, state = clone_env
    vid = create(clone_env).json()["id"]
    project = client.get(root + "/projects/" + pid).json()
    project["content"]["draft"].update(
        voiceId=vid, text="中文。", emotion="愉快", language="Chinese", speed=1.1
    )
    saved = client.put(
        root + "/projects/" + pid,
        json={
            "request_id": str(uuid4()),
            "expected_revision": project["revision"],
            "content": project["content"],
        },
    ).json()
    body = {**request_body(pid), "expected_revision": saved["project"]["revision"]}
    result = client.post(root + "/generation-tasks", json=body)
    assert result.status_code == 200, result.text
    job = next(
        j
        for j in client.get(root + "/generation-tasks").json()
        if j["id"] == result.json()["id"]
    )
    assert job["status"] == "completed", job
    assert set(job["tts"]) == {"voice_name"}
    assert job["snapshot"]["draft"]["text"] == "中文。"
    assert "billing" not in job
    bundle = client.get(job["handoff_url"])
    assert bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert "billing" not in manifest
        assert not {"provider", "model", "voice_id"}.intersection(manifest["tts"])
    with client.app.state.session_factory() as session:
        details = session.get(VideoGenerationRecord, job["id"]).details
        assert details["tts"]["provider"] == "cosyvoice"
        assert details["billing"][0]["estimated_cny"] == "0.0004"
    inputs = state["synthesis"][0]["input"]
    assert inputs["voice"] == state["created"][0] and inputs["rate"] == 1.1
    assert inputs["language_hints"] == ["zh"] and "愉快" in inputs["instruction"]
    assert all(path != "/api/tts/generate" for _, path, _ in provider.posts)
    client.post(root + "/generation-tasks", json=body)
    assert len(state["synthesis"]) == 1


def test_customer_responses_keep_supplier_details_internal(clone_env):
    client, _, provider, root, _, _, _ = clone_env
    vid = create(clone_env).json()["id"]
    config = client.get(root + "/voice-clone-config").json()
    assert "model" not in config
    row = client.get(root + f"/voice-clones/{vid}").json()
    assert "model" not in row and "preview_billing" not in row
    voices = client.get(root + "/voices").json()
    assert all("provider" not in voice and "model" not in voice for voice in voices)
    provider.prices = lambda: pytest.fail("Customer pricing must not call supplier")
    assert client.get(root + "/generation-prices").json() == {
        "pricing_available": False
    }


def test_cross_owner_and_gray_gate_reject_clone_access(clone_env):
    client, auth, _, root, _, _, state = clone_env
    vid = create(clone_env).json()["id"]
    with client.app.state.session_factory() as session:
        row = session.get(VideoClonedVoiceRecord, vid)
        # Same workspace membership alone must never expose another owner's voice.
        row.owner_user_id = "different-owner-fixture"
        session.commit()
    for suffix in ["", "/preview"]:
        assert client.get(root + "/voice-clones/" + vid + suffix).status_code == 404
    for suffix in ["/refresh", "/preview"]:
        assert client.post(root + "/voice-clones/" + vid + suffix).status_code == 404
    assert client.get(root + "/voice-clones").json() == []
    auth.identity = replace(auth.identity, email="other@example.com")
    assert client.get(root + "/voice-clone-config").status_code == 404
    assert len(state["created"]) == 1


def test_model_and_account_mismatch_cannot_synthesize(clone_env):
    client, _, _, root, _, _, state = clone_env
    vid = create(clone_env).json()["id"]
    client.app.state.settings.video_cosyvoice_workspace_id = "another-workspace"
    assert client.post(root + f"/voice-clones/{vid}/preview").status_code == 409
    assert not state["synthesis"]


def test_download_rejects_untrusted_host_and_invalid_audio(clone_env, tmp_path):
    api = clone_env[0].app.state.video_cosyvoice
    for url in [
        "https://evil.invalid/audio",
        "https://127.0.0.1/audio",
        "https://a.aliyuncs.com@evil.invalid/audio",
    ]:
        with pytest.raises(ApiError):
            api.download(url, tmp_path / "out.mp3")


def test_create_response_id_must_match_model_and_request_prefix(clone_env, tmp_path):
    api = clone_env[0].app.state.video_cosyvoice
    api.transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"output": {"voice_id": "foreign-voice"}})
    )
    path = tmp_path / "sample.wav"
    path.write_bytes(sample())
    with pytest.raises(ApiError):
        api.create(
            SimpleNamespace(model=MODEL, prefix="polaris", sample_path=str(path))
        )
