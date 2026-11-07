"""Lost model replies must recover without repeating any paid operation."""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.errors import ApiError
from app.video_generation_models import VideoGenerationRecord
from app.video_providers import VideoProviders
from tests.test_video_generation import request_body

pytest_plugins = ["tests.test_video_generation"]


@pytest.fixture(autouse=True)
def immediate_lookup(monkeypatch):
    monkeypatch.setattr("app.video_generation_media.MODEL_LOOKUP_WINDOW", 0)


def registered(name, **changes):
    return {
        "id": 951,
        "model_name": name,
        "model_type": "video",
        "is_active": True,
        "is_public": False,
        # The real provider copies the uploaded video, changing its URL.
        "video_url": "https://sowa.oss-cn-beijing.aliyuncs.com/copied.mp4",
        **changes,
    }


def latest(client, root):
    return client.get(root + "/generation-tasks").json()[0]


def test_lost_forward_reply_recovers_and_submits_lipsync_once(video_gen):
    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    provider.fail = "/api/digital_human/models"
    provider.models = lambda: [registered(provider.posts[-1][2]["model_name"])]
    body = request_body(pid)
    client.post(root + "/generation-tasks", json=body)
    job = latest(client, root)
    assert job["status"] == "completed"
    assert provider.posts[-1][2]["model_id"] == 951
    assert [p for _, p, _ in provider.posts] == [
        "/api/tts/generate",
        "/api/digital_human/models",
        "/api/digital_human/submit",
    ]
    client.post(root + "/generation-tasks", json=body)
    assert len(provider.posts) == 3
    with client.app.state.session_factory() as session:
        details = session.get(VideoGenerationRecord, job["id"]).details
        assert details["model_registration"]["reconciled"] is True
        assert details["forward_model_id"] == 951


def test_old_unknown_recovers_951_without_tts_upload_or_registration(video_gen):
    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    provider.fail = "/api/digital_human/models"
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = latest(client, root)
    with client.app.state.session_factory() as session:
        row = session.get(VideoGenerationRecord, job["id"])
        details = dict(row.details)
        details.pop("model_registration")  # Exact pre-fix production state.
        row.details, row.status = details, "unknown"
        session.commit()
    assert latest(client, root)["can_resume"]
    provider.models = lambda: [registered("极光正向动作-" + job["id"])]
    uploads = len(provider.uploads)
    assert (
        client.post(root + f"/generation-tasks/{job['id']}/resume").status_code == 200
    )
    assert latest(client, root)["status"] == "completed"
    assert len(provider.uploads) == uploads
    assert provider.posts[-1][2]["model_id"] == 951
    assert [p for _, p, _ in provider.posts].count("/api/tts/generate") == 1
    assert [p for _, p, _ in provider.posts].count("/api/digital_human/models") == 1


@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "unavailable",
        "duplicate",
        "public",
        "inactive",
        "prefix",
        "invalid_id",
    ],
)
def test_uncertain_lookup_only_queries_until_exact_model_appears(video_gen, mode):
    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    provider.fail = "/api/digital_human/models"
    request = provider.request

    def query(vendor, method, path, **kwargs):
        if method == "GET" and path == "/api/digital_human/models":
            name = (
                "极光正向动作-" + latest_id[0]
                if latest_id
                else provider.posts[-1][2]["model_name"]
            )
            if mode == "unavailable":
                raise ApiError(502, "VIDEO_PROVIDER_UNAVAILABLE", "unavailable")
            values = {
                "missing": [],
                "duplicate": [registered(name), registered(name, id=952)],
                "public": [registered(name, is_public=True)],
                "inactive": [registered(name, is_active=False)],
                "prefix": [registered(name + "-other")],
                "invalid_id": [registered(name, id=True)],
            }
            return {"models": values[mode]}
        return request(vendor, method, path, **kwargs)

    latest_id = []
    provider.request = query
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = latest(client, root)
    latest_id.append(job["id"])
    assert job["status"] == "awaiting_resume" and job["can_resume"]
    client.post(root + f"/generation-tasks/{job['id']}/resume")
    assert latest(client, root)["status"] == "awaiting_resume"
    assert len(provider.posts) == 2  # Still only one TTS and one registration.
    provider.request = request
    provider.models = lambda: [registered("极光正向动作-" + job["id"])]
    client.post(root + f"/generation-tasks/{job['id']}/resume")
    assert latest(client, root)["status"] == "completed"
    assert len(provider.posts) == 3


def test_delayed_visibility_is_polled_in_same_run(video_gen, monkeypatch):
    from app import video_generation_media as media

    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    provider.fail = "/api/digital_human/models"
    clock = [0]
    monkeypatch.setattr(media, "MODEL_LOOKUP_WINDOW", 20)
    monkeypatch.setattr(
        media,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        ),
    )
    calls = []

    def models():
        calls.append(True)
        return (
            [] if len(calls) < 3 else [registered(provider.posts[-1][2]["model_name"])]
        )

    provider.models = models
    client.post(root + "/generation-tasks", json=request_body(pid))
    assert latest(client, root)["status"] == "completed"
    assert len(calls) == 3 and clock[0] == 10
    assert len(provider.posts) == 3


def test_original_avatar_registration_uses_same_recovery(video_gen):
    client, _, provider, root, _, _ = video_gen
    client.post(
        root + "/generation-tasks",
        json={
            "request_id": str(uuid4()),
            "kind": "h3_template",
            "avatar_id": "self-presenter-female-v1",
        },
    )
    job = latest(client, root)
    provider.fail = "/api/digital_human/models"
    provider.models = lambda: [registered("极光原创-" + job["id"])]
    client.post(root + f"/generation-tasks/{job['id']}/approve-template")
    assert latest(client, root)["status"] == "completed"
    assert [p for _, p, _ in provider.posts] == [
        "/v1/videos",
        "/api/digital_human/models",
    ]


@pytest.mark.parametrize("failure", ["504", "transport", "missing_id", "non_json"])
def test_registration_transport_extends_timeout_and_never_retries(video_gen, failure):
    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    seen = []

    def handle(request):
        seen.append((request.method, request.extensions["timeout"]))
        if request.method == "POST":
            if failure == "transport":
                raise httpx.ReadTimeout("timed out", request=request)
            if failure == "non_json":
                return httpx.Response(502, text="gateway unavailable")
            if failure == "missing_id":
                return httpx.Response(200, json={})
            return httpx.Response(504, json={"error": "upstream timed out"})
        name = provider.posts[-1][2]["model_name"]
        return httpx.Response(200, json={"models": [registered(name)]})

    settings = client.app.state.settings.model_copy(
        update={"quanyu_api_key": SecretStr("test-key")}
    )
    adapter = VideoProviders(settings, httpx.MockTransport(handle))
    request = provider.request

    def route(vendor, method, path, **kwargs):
        if path == "/api/digital_human/models":
            if method == "POST":
                provider.posts.append((vendor, path, kwargs["json"]))
            return adapter.request(vendor, method, path, **kwargs)
        return request(vendor, method, path, **kwargs)

    provider.request = route
    client.post(root + "/generation-tasks", json=request_body(pid))
    assert latest(client, root)["status"] == "completed"
    assert [method for method, _ in seen] == ["POST", "GET"]
    assert seen[0][1]["read"] == 180
    assert seen[0][1]["connect"] == 15
    assert seen[1][1]["read"] <= 15


def test_saved_success_receipt_survives_restart_before_business_checkpoint(video_gen):
    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    provider.fail = "/api/digital_human/models"
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = latest(client, root)
    with client.app.state.session_factory() as session:
        row = session.get(VideoGenerationRecord, job["id"])
        row.status = "unknown"
        receipt = {**row.details["model_registration"], "model_id": 951}
        row.details = {**row.details, "model_registration": receipt}
        session.commit()
    provider.models = lambda: pytest.fail("Successful saved receipt must be reused")
    client.post(root + f"/generation-tasks/{job['id']}/resume")
    assert latest(client, root)["status"] == "completed"
    assert provider.posts[-1][2]["model_id"] == 951
    assert len(provider.posts) == 3


def test_definite_registration_rejection_does_not_poll_or_retry(video_gen):
    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    request = provider.request

    def rejected(vendor, method, path, **kwargs):
        if path == "/api/digital_human/models":
            assert method == "POST"
            provider.posts.append((vendor, path, kwargs["json"]))
            raise ApiError(502, "VIDEO_PROVIDER_REJECTED", "rejected")
        return request(vendor, method, path, **kwargs)

    provider.request = rejected
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = latest(client, root)
    assert job["status"] == "failed" and not job["can_resume"]
    assert (
        client.post(root + f"/generation-tasks/{job['id']}/resume").status_code == 409
    )
    assert len(provider.posts) == 2
