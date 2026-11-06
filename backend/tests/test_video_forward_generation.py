import io
import wave
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.video_generation_models import VideoAvatarRecord
from app.video_template_media import prepare_forward, run_media, video_info
from tests.test_video_generation import FakeVideoProviders, request_body

pytest_plugins = ["tests.test_video_generation"]


def test_approved_h3_source_extends_to_audio_without_another_h3_call(video_gen):
    client, _, provider, root, pid, _ = video_gen
    client.post(
        root + "/generation-tasks",
        json={
            "request_id": str(uuid4()),
            "kind": "h3_template",
            "avatar_id": "self-presenter-female-v1",
        },
    )
    template = client.get(root + "/generation-tasks").json()[0]
    client.post(root + f"/generation-tasks/{template['id']}/approve-template")
    content = client.get(root + "/projects/" + pid).json()["content"]
    content["draft"]["avatarId"] = "self-presenter-female-v1"
    client.put(
        root + "/projects/" + pid,
        json={"request_id": str(uuid4()), "expected_revision": 1, "content": content},
    )
    provider.audio_seconds = 4.123
    client.post(
        root + "/generation-tasks",
        json={
            **request_body(pid),
            "avatar_id": "self-presenter-female-v1",
            "expected_revision": 2,
        },
    )
    job = next(
        j
        for j in client.get(root + "/generation-tasks").json()
        if j["kind"] == "lipsync"
    )
    assert job["status"] == "completed"
    assert job["audio_duration_seconds"] == pytest.approx(4.123, abs=0.0001)
    assert provider.posts[-1][2]["model_id"] == 100
    assert [p for _, p, _ in provider.posts].count("/v1/videos") == 1


def test_tts_duration_is_decoded_and_long_public_video_is_forward_prepared(video_gen):
    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 8.123
    body = request_body(pid)
    assert client.post(root + "/generation-tasks", json=body).status_code == 200
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "completed"
    assert job["audio_duration_seconds"] == pytest.approx(8.123, abs=0.0001)
    assert job["template_preparation"]["target_seconds"] >= 8.123
    assert job["template_preparation"]["recipe"] == "forward-cycle-v1"
    assert job["template_preparation"]["reversed_frames"] is False
    prepared = next(
        p for p, _, purpose in provider.uploads if purpose == "digital_human_model"
    )
    assert video_info(prepared)["duration"] >= 8.123
    assert [p for _, p, _ in provider.posts] == [
        "/api/tts/generate",
        "/api/digital_human/models",
        "/api/digital_human/submit",
    ]
    assert provider.posts[-1][2]["model_id"] == 99
    client.post(root + "/generation-tasks", json=body)
    assert len(provider.posts) == 3


def test_uploaded_audio_measures_fractional_duration_and_preserves_original_wave(
    video_gen,
):
    client, _, provider, root, pid, _ = video_gen
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 50400)
    audio = client.post(
        root + "/audio-files",
        files={"file": ("speech.wav", data.getvalue(), "audio/wav")},
    ).json()
    content = client.get(root + "/projects/" + pid).json()["content"]
    content["draft"].update(drive="audio", audioAssetId=audio["id"])
    client.put(
        root + "/projects/" + pid,
        json={"request_id": str(uuid4()), "expected_revision": 1, "content": content},
    )
    client.post(
        root + "/generation-tasks", json={**request_body(pid), "expected_revision": 2}
    )
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "completed" and job["audio_duration_seconds"] == 3.15
    assert all(p != "/api/tts/generate" for _, p, _ in provider.posts)
    response = client.get(job["audio_url"])
    assert response.content == data.getvalue()
    assert response.headers["content-type"].startswith("audio/wav")


def test_forward_registration_unknown_is_not_retried_or_lipsynced(video_gen):
    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    provider.fail = "/api/digital_human/models"
    body = request_body(pid)
    client.post(root + "/generation-tasks", json=body)
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "unknown" and job["stage"] == "forward_model_submitting"
    assert job["can_resume"] is False
    assert job["audio_url"]
    client.post(root + "/generation-tasks", json=body)
    assert (
        client.post(root + f"/generation-tasks/{job['id']}/resume").status_code == 409
    )
    assert [p for _, p, _ in provider.posts] == [
        "/api/tts/generate",
        "/api/digital_human/models",
    ]


def test_forward_upload_resume_reuses_tts_and_prepared_file(video_gen):
    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    upload = provider.upload

    def failing(path, mime, purpose):
        if purpose == "digital_human_model":
            raise ApiError(502, "VIDEO_UPLOAD_FAILED", "fixture interrupted")
        return upload(path, mime, purpose)

    provider.upload = failing
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "failed" and job["stage"] == "uploading_forward_template"
    assert job["can_resume"] is True
    path = (
        client.app.state.settings.video_media_dir
        / "jobs"
        / job["id"]
        / "forward-template.mp4"
    )
    stamp = path.stat().st_mtime_ns
    provider.upload = upload
    client.post(root + f"/generation-tasks/{job['id']}/resume")
    assert client.get(root + "/generation-tasks").json()[0]["status"] == "completed"
    assert path.stat().st_mtime_ns == stamp
    assert [p for _, p, _ in provider.posts].count("/api/tts/generate") == 1
    assert [p for _, p, _ in provider.posts].count("/api/digital_human/models") == 1


def test_forward_preparation_resume_reuses_existing_tts(video_gen, monkeypatch):
    from app import video_generation_media

    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    original = video_generation_media.prepare_forward

    def failing(*args, **kwargs):
        raise ApiError(422, "VIDEO_MEDIA_PROCESSING_FAILED", "fixture interrupted")

    monkeypatch.setattr(video_generation_media, "prepare_forward", failing)
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "failed" and job["stage"] == "preparing_forward_template"
    assert job["can_resume"] is True
    original_audio = job["audio_url"]
    monkeypatch.setattr(video_generation_media, "prepare_forward", original)
    client.post(root + f"/generation-tasks/{job['id']}/resume")
    resumed = client.get(root + "/generation-tasks").json()[0]
    assert resumed["status"] == "completed" and resumed["id"] == job["id"]
    assert resumed["audio_url"] == original_audio
    assert [p for _, p, _ in provider.posts].count("/api/tts/generate") == 1
    assert [p for _, p, _ in provider.posts].count("/api/digital_human/submit") == 1


def test_forward_25fps_template_covers_saved_narration_and_decodes(tmp_path):
    source, target = tmp_path / "source.mp4", tmp_path / "forward.mp4"
    run_media(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x96:rate=25:duration=10.92",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-video_track_timescale",
            "90000",
            str(source),
        ]
    )
    prepare_forward(source, target, 46.1715)
    info = video_info(target)
    assert info["fps"] == 25
    assert info["duration"] + 0.005 >= 46.1715
    run_media(["-xerror", "-i", str(target), "-map", "0:v:0", "-f", "null", "-"])


def test_source_is_snapshotted_before_avatar_library_changes(video_gen, monkeypatch):
    from app import video_generation

    client, _, provider, root, pid, _ = video_gen
    worker = video_generation.process_generation
    monkeypatch.setattr(video_generation, "process_generation", lambda *args: None)
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = client.get(root + "/generation-tasks").json()[0]
    with client.app.state.session_factory() as session:
        row = session.get(VideoAvatarRecord, "qy-model-11")
        row.video_url = "https://sowa.oss-cn-beijing.aliyuncs.com/changed.mp4"
        row.provider_model_id = 321
        session.commit()
    worker(
        client.app.state.session_factory, client.app.state.settings, job["id"], provider
    )
    assert provider.posts[-1][2]["model_id"] == 11
    assert any(url.endswith("/public.mp4") for url, _ in provider.downloads)
    assert not any(url.endswith("/changed.mp4") for url, _ in provider.downloads)


@pytest.mark.parametrize("seconds", [0.4, 2, 8.125, 321.013])
def test_forward_media_covers_short_fractional_and_long_audio_without_many_inputs(
    tmp_path, seconds
):
    provider = FakeVideoProviders()
    target = tmp_path / "forward.mp4"
    report = prepare_forward(provider.media, target, seconds)
    assert video_info(target)["duration"] + 0.005 >= seconds
    assert report["target_seconds"] >= seconds
    assert report["reversed_frames"] is False
    assert not list(tmp_path.glob("*.cycle-*"))
