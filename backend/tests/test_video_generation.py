import io
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from uuid import uuid4

import httpx
import imageio_ffmpeg
import pytest
from fastapi.testclient import TestClient

from app.errors import ApiError
from app.main import create_app
from app.video_providers import VideoProviders, safe_media_url
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_projects import payload


class FakeVideoProviders:
    media = None
    directory = None

    def __init__(self):
        self.posts = []
        self.fail = None
        self.uploads = []
        self.downloads = []
        self.audio_seconds = 1
        if FakeVideoProviders.media is None:
            FakeVideoProviders.directory = tempfile.TemporaryDirectory(
                prefix="video-provider-fixture-"
            )
            FakeVideoProviders.media = (
                Path(FakeVideoProviders.directory.name) / "source.mp4"
            )
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
                    "testsrc2=size=64x96:rate=12:duration=2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(FakeVideoProviders.media),
                ],
                check=True,
            )

    def models(self):
        return [
            {
                "id": 11,
                "model_name": "公共形象",
                "is_public": True,
                "is_active": True,
                "model_type": "video",
                "video_url": "https://sowa.oss-cn-beijing.aliyuncs.com/public.mp4",
            },
            {
                "id": 12,
                "model_name": "PRIVATE_MUST_NOT_LEAK",
                "is_public": False,
                "is_active": True,
                "model_type": "video",
                "video_url": "https://sowa.oss-cn-beijing.aliyuncs.com/private.mp4",
            },
        ]

    def voices(self):
        return [{"id": 1, "name": "温柔女声"}]

    def prices(self):
        return {
            "digital_human": {"price_cny": "0.5"},
            "digital_human_model_save": {"price_cny": "0.05"},
        }

    def upload(self, path, mime, purpose):
        self.uploads.append((Path(path), mime, purpose))
        return "https://sowa.oss-cn-beijing.aliyuncs.com/uploaded.mp4"

    def download(self, url, target, **kwargs):
        self.downloads.append((url, target))
        target.parent.mkdir(parents=True, exist_ok=True)
        if "audio" in url or "narration" in target.name:
            with wave.open(str(target), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\0\0" * round(16000 * self.audio_seconds))
        else:
            shutil.copyfile(FakeVideoProviders.media, target)

    def request(self, vendor, method, path, **kwargs):
        if method == "GET" and path == "/api/digital_human/models":
            return {"models": self.models()}
        if method == "POST":
            self.posts.append((vendor, path, kwargs.get("json", {})))
            if self.fail == path:
                raise ApiError(502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "fixture unknown")
        if path == "/api/tts/generate":
            return {
                "audio_url": "https://sowa.oss-cn-beijing.aliyuncs.com/audio.mp3",
                "record_id": 1,
                "duration": 999,
                "billing": {"amount_cny": "-0.01"},
            }
        if path == "/api/digital_human/submit":
            return {"task_id": "lip-fixture", "billing": {"amount_cny": "-0.5"}}
        if path == "/v1/videos":
            return {"id": "h3-fixture"}
        if path == "/api/digital_human/models":
            count = sum(p == path for _, p, _ in self.posts)
            return {"model": {"id": 98 + count}}
        return {"status": "completed", "result": {}}


@pytest.fixture
def video_gen(tmp_path):
    auth = FakeExternalAuthBackend(
        identity=verified_identity(email="1474953130@qq.com")
    )
    settings = external_settings(tmp_path).model_copy(
        update={"video_providers_enabled": True, "video_media_dir": tmp_path / "video"}
    )
    app = create_app(settings, auth)
    provider = FakeVideoProviders()
    app.state.video_providers = provider
    with TestClient(app) as client:
        workspace = client.get("/api/v1/workspaces").json()[0]["id"]
        user = client.get("/api/v1/me").json()["id"]
        root = f"/api/v1/video-studio/workspaces/{workspace}"
        assert client.get(root + "/avatars").status_code == 200
        pid = str(uuid4())
        content = payload()
        content["content"]["draft"].update(avatarId="qy-model-11", voiceId="qy-voice-1")
        assert client.put(root + "/projects/" + pid, json=content).status_code == 200
        yield client, auth, provider, root, pid, user


def request_body(pid):
    return {
        "request_id": str(uuid4()),
        "kind": "lipsync",
        "avatar_id": "qy-model-11",
        "project_id": pid,
        "expected_revision": 1,
    }


def test_catalogue_only_imports_public_models_and_has_real_media_endpoints(video_gen):
    client, _, provider, root, _, _ = video_gen
    response = client.get(root + "/avatars")
    data = response.json()
    assert "PRIVATE_MUST_NOT_LEAK" not in response.text
    public = [a for a in data if a["source"] == "quanyu_public"]
    assert len(public) == 1
    assert public[0]["ready"]
    assert public[0]["cover_url"].endswith("/cover")
    assert provider.posts == []


def test_public_lipsync_bypasses_h3_and_is_persistently_idempotent(video_gen):
    client, _, provider, root, pid, _ = video_gen
    body = request_body(pid)
    first = client.post(root + "/generation-tasks", json=body)
    assert first.status_code == 200, first.text
    again = client.post(root + "/generation-tasks", json=body)
    assert again.status_code == 200
    tasks = client.get(root + "/generation-tasks").json()
    assert len(tasks) == 1 and tasks[0]["status"] == "completed"
    assert [path for _, path, _ in provider.posts] == [
        "/api/tts/generate",
        "/api/digital_human/submit",
    ]
    assert provider.posts[0][2]["cloud_voice_id"] == "1"
    assert client.get(tasks[0]["video_url"]).status_code == 200
    assert client.get(tasks[0]["audio_url"]).status_code == 200
    changed = {**body, "kind": "h3_template"}
    assert client.post(root + "/generation-tasks", json=changed).status_code == 409


def test_self_owned_template_uses_h3_then_registers_and_can_lipsync(video_gen):
    client, _, provider, root, pid, _ = video_gen
    body = {
        "request_id": str(uuid4()),
        "kind": "h3_template",
        "avatar_id": "self-presenter-female-v1",
    }
    r = client.post(root + "/generation-tasks", json=body)
    assert r.status_code == 200, r.text
    assert provider.posts[0][0:2] == ("wuye", "/v1/videos")
    assert provider.posts[0][2]["referenceImages"]
    assert provider.posts[0][2]["model"] == "Minimax-H3-768p-913"
    assert provider.posts[0][2]["duration"] == 15
    jobs = client.get(root + "/generation-tasks").json()
    assert jobs[0]["status"] == "awaiting_review"
    assert len(provider.posts) == 1
    assert jobs[0]["video_url"]
    assert (
        client.post(
            root + f"/generation-tasks/{jobs[0]['id']}/approve-template"
        ).status_code
        == 200
    )
    assert provider.posts[1][1] == "/api/digital_human/models"
    own = next(
        a for a in client.get(root + "/avatars").json() if a["source"] == "self_owned"
    )
    assert own["ready"]
    project = client.get(root + "/projects/" + pid).json()
    content = project["content"]
    content["draft"]["avatarId"] = own["id"]
    client.put(
        root + "/projects/" + pid,
        json={"request_id": str(uuid4()), "expected_revision": 1, "content": content},
    )
    r = client.post(
        root + "/generation-tasks",
        json={**request_body(pid), "avatar_id": own["id"], "expected_revision": 2},
    )
    assert r.status_code == 200
    assert provider.posts[-1][2]["model_id"] == 99


def test_unknown_paid_submission_never_retries_on_replay_or_resume(video_gen):
    client, _, provider, root, pid, _ = video_gen
    provider.fail = "/api/digital_human/submit"
    body = request_body(pid)
    client.post(root + "/generation-tasks", json=body)
    tasks = client.get(root + "/generation-tasks").json()
    assert tasks[0]["status"] == "unknown"
    assert tasks[0]["audio_url"]
    client.post(root + "/generation-tasks", json=body)
    assert (
        client.post(root + f"/generation-tasks/{tasks[0]['id']}/resume").status_code
        == 409
    )
    assert len(provider.posts) == 2


def test_public_avatar_cannot_be_sent_to_h3(video_gen):
    client, _, provider, root, _, _ = video_gen
    r = client.post(
        root + "/generation-tasks",
        json={
            "request_id": str(uuid4()),
            "kind": "h3_template",
            "avatar_id": "qy-model-11",
        },
    )
    assert r.status_code == 422
    assert provider.posts == []


def test_disabled_provider_blocks_new_jobs_without_charging(video_gen):
    client, _, provider, root, pid, _ = video_gen
    client.app.state.settings.video_providers_enabled = False
    assert (
        client.post(root + "/generation-tasks", json=request_body(pid)).status_code
        == 503
    )
    assert client.get(root + "/generation-tasks").json() == []
    assert provider.posts == []


def test_rejected_template_never_registers_or_becomes_ready(video_gen):
    client, _, provider, root, _, _ = video_gen
    client.post(
        root + "/generation-tasks",
        json={
            "request_id": str(uuid4()),
            "kind": "h3_template",
            "avatar_id": "self-presenter-female-v1",
        },
    )
    job = client.get(root + "/generation-tasks").json()[0]
    assert client.get(job["video_url"]).status_code == 200
    assert (
        client.post(root + f"/generation-tasks/{job['id']}/reject-template").status_code
        == 200
    )
    assert (
        client.post(
            root + f"/generation-tasks/{job['id']}/approve-template"
        ).status_code
        == 409
    )
    assert not next(
        a for a in client.get(root + "/avatars").json() if a["source"] == "self_owned"
    )["ready"]
    assert len(provider.posts) == 1


def test_download_failure_resumes_existing_task_without_new_paid_posts(video_gen):
    client, _, provider, root, pid, _ = video_gen
    download = provider.download

    def broken(*args, **kwargs):
        if args[1].name == "result.mp4":
            raise ApiError(
                502, "VIDEO_MEDIA_DOWNLOAD_FAILED", "fixture download interrupted"
            )
        return download(*args, **kwargs)

    provider.download = broken
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "failed" and job["stage"] == "downloading_video"
    provider.download = download
    assert (
        client.post(root + f"/generation-tasks/{job['id']}/resume").status_code == 200
    )
    assert client.get(root + "/generation-tasks").json()[0]["status"] == "completed"
    assert len(provider.posts) == 2


def test_migration_36_preserves_projects_and_supports_sqlite_and_postgresql(video_gen):
    import importlib.util
    from io import StringIO
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.video_generation_models import (
        VideoAudioRecord,
        VideoAvatarRecord,
        VideoGenerationRecord,
    )

    client, _, _, root, pid, _ = video_gen
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261104_0036_video_generation.py"
    )
    spec = importlib.util.spec_from_file_location("video_migration_36", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with client.app.state.engine.begin() as connection:
        for model in [VideoGenerationRecord, VideoAudioRecord, VideoAvatarRecord]:
            model.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
    assert client.get(root + "/projects/" + pid).status_code == 200
    assert client.get(root + "/avatars").status_code == 200
    assert (
        client.post(root + "/generation-tasks", json=request_body(pid)).status_code
        == 200
    )
    output = StringIO()
    with Operations.context(
        MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
        )
    ):
        module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE video_generations" in sql and "JSONB" in sql
    assert "DROP" not in sql and "UPDATE users" not in sql


@pytest.mark.parametrize(
    "route",
    [
        "avatars",
        "voices",
        "generation-prices",
        "generation-tasks",
        "avatars/qy-model-11/cover",
        "avatars/qy-model-11/preview",
    ],
)
def test_all_generation_routes_retain_gray_gate(video_gen, route):
    client, auth, provider, root, pid, _ = video_gen
    auth.identity = verified_identity(email="ordinary@example.com")
    assert (
        client.get(
            root + "/" + route, headers={"X-User-Email": "1474953130@qq.com"}
        ).status_code
        == 404
    )
    assert (
        client.post(root + "/generation-tasks", json=request_body(pid)).status_code
        == 404
    )
    assert provider.posts == []


def test_other_verified_identity_cannot_read_audio_or_task_and_project_ownership(
    video_gen,
):
    client, auth, provider, root, pid, _ = video_gen
    client.post(root + "/generation-tasks", json=request_body(pid))
    task = client.get(root + "/generation-tasks").json()[0]
    auth.identity = verified_identity(
        primary_user_id="another-user", email="1474953130@qq.com"
    )
    assert client.get(task["video_url"]).status_code == 404
    assert (
        client.post(root + "/generation-tasks", json=request_body(pid)).status_code
        == 404
    )


def test_audio_upload_checks_file_content_and_scope(video_gen):
    client, _, provider, root, _, _ = video_gen
    assert (
        client.post(
            root + "/audio-files",
            files={"file": ("wrong.wav", b"not audio", "audio/wav")},
        ).status_code
        == 422
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000)
    response = client.post(
        root + "/audio-files",
        files={"file": ("speech.wav", buffer.getvalue(), "audio/wav")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["duration"] == 1
    assert provider.posts == []


def test_media_host_and_redirects_do_not_leak_provider_credentials(tmp_path):
    for url in [
        "http://127.0.0.1/x",
        "https://evil.example/file.mp4",
        "https://user:pass@quanyu.sowa.chat/file",
    ]:
        with pytest.raises(ApiError):
            safe_media_url(url)
    seen = []

    def transport(request):
        seen.append((request.url.host, request.headers.get("X-API-Key")))
        if request.url.host == "quanyu.sowa.chat":
            return httpx.Response(
                302, headers={"Location": "https://cdn.jihuo.pro/out.mp4"}
            )
        return httpx.Response(200, content=b"video")

    settings = external_settings(tmp_path).model_copy(
        update={
            "video_providers_enabled": True,
            "quanyu_api_key": __import__("pydantic").SecretStr("private-test-token"),
        }
    )
    provider = VideoProviders(settings, httpx.MockTransport(transport))
    provider.download(
        "https://quanyu.sowa.chat/api/download/id",
        tmp_path / "result.mp4",
        vendor="quanyu",
    )
    assert seen == [("quanyu.sowa.chat", "private-test-token"), ("cdn.jihuo.pro", None)]


def test_post_transport_failure_is_unknown_and_not_retried(tmp_path):
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(502, json={"error": "may have been accepted"})

    settings = external_settings(tmp_path).model_copy(
        update={
            "video_providers_enabled": True,
            "quanyu_api_key": __import__("pydantic").SecretStr("private-test-token"),
        }
    )
    provider = VideoProviders(settings, httpx.MockTransport(transport))
    with pytest.raises(ApiError) as error:
        provider.request("quanyu", "POST", "/api/digital_human/submit", json={})
    assert error.value.code == "VIDEO_PROVIDER_OUTCOME_UNKNOWN"
    assert len(calls) == 1
