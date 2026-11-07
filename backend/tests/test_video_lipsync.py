from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app import video_lipsync
from app.errors import ApiError
from app.video_generation_models import VideoGenerationRecord, VideoLipsyncAvatarRecord
from app.video_providers import VideoProviders
from tests.test_video_generation import request_body, video_gen  # noqa: F401


@pytest.fixture
def routed(video_gen, monkeypatch):  # noqa: F811
    client, _, provider, root, pid, _ = video_gen
    clock = SimpleNamespace(seconds=0)
    base = datetime.now(UTC)

    def sleep(seconds):
        clock.seconds += seconds

    monkeypatch.setattr(
        video_lipsync,
        "time",
        SimpleNamespace(
            sleep=sleep,
            monotonic=lambda: clock.seconds,
        ),
    )
    monkeypatch.setattr(
        video_lipsync, "utc_now", lambda: base + timedelta(seconds=clock.seconds)
    )
    settings = client.app.state.settings
    settings.video_lipsync_failover_enabled = True
    settings.skyhuman_api_key = SecretStr("test-sky-secret")
    settings.video_skyhuman_avatar_map = {"11": "same-prepared-avatar"}
    settings.video_lipsync_breaker_seconds = 0
    original = provider.request
    behavior = SimpleNamespace(
        primary="completed", backup="3", clone="3", clone_count=0
    )

    def request(vendor, method, path, **kwargs):
        if vendor == "skyhuman":
            if method == "POST":
                provider.posts.append((vendor, path, kwargs.get("json", {})))
            if path.endswith("create_by_video"):
                behavior.clone_count += 1
                return {"code": 0, "task_id": "clone-fixture"}
            if "/avatar/task?" in path:
                return {
                    "code": 0,
                    "status": int(behavior.clone),
                    "avatar": "registered-same-avatar",
                }
            if path.endswith("create_by_audio"):
                return {"code": 0, "task_id": "backup-fixture"}
            return {
                "code": 0,
                "status": int(behavior.backup),
                "video_url": "https://cdn-oss.pilihu.vip/result.mp4",
            }
        if method == "GET" and path.startswith("/api/status/"):
            status = (
                behavior.primary() if callable(behavior.primary) else behavior.primary
            )
            if isinstance(status, Exception):
                raise status
            return {"status": status, "progress": 20}
        return original(vendor, method, path, **kwargs)

    provider.request = request
    return client, provider, root, pid, clock, behavior


def jobs(client, root):
    return client.get(root + "/generation-tasks").json()


def paid_videos(provider):
    return [
        p
        for p in provider.posts
        if p[1]
        in {
            "/api/digital_human/submit",
            "/api/v2/fly/video/create_by_audio",
        }
    ]


def test_ten_minute_success_never_starts_backup(routed):
    client, provider, root, pid, clock, behavior = routed
    behavior.primary = lambda: "completed" if clock.seconds >= 650 else "processing"
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = jobs(client, root)[0]
    assert job["status"] == "completed"
    assert clock.seconds == 650
    assert job["lipsync_routing"]["selected_provider"] == "quanyu"
    assert len(paid_videos(provider)) == 1
    assert not any(vendor == "skyhuman" for vendor, _, _ in provider.posts)


@pytest.mark.parametrize("primary", ["processing", "queued", "cancelled", "mystery"])
def test_slow_or_nonterminal_task_only_queries_original_on_resume(routed, primary):
    client, provider, root, pid, clock, behavior = routed
    behavior.primary = primary
    body = request_body(pid)
    client.post(root + "/generation-tasks", json=body)
    job = jobs(client, root)[0]
    assert job["status"] == "awaiting_resume"
    assert job["lipsync_routing"]["long_wait"] is True
    assert clock.seconds == 900
    client.post(root + "/generation-tasks", json=body)
    behavior.primary = "completed"
    client.post(root + f"/generation-tasks/{job['id']}/resume")
    assert jobs(client, root)[0]["status"] == "completed"
    assert len(paid_videos(provider)) == 1


def test_status_query_outage_does_not_start_another_paid_task(routed):
    client, provider, root, pid, clock, behavior = routed
    behavior.primary = ApiError(502, "VIDEO_PROVIDER_UNAVAILABLE", "query unavailable")
    client.post(root + "/generation-tasks", json=request_body(pid))
    assert jobs(client, root)[0]["status"] == "awaiting_resume"
    assert clock.seconds == 900
    assert len(paid_videos(provider)) == 1


def test_confirmed_failure_switches_once_and_reuses_audio_and_mapped_avatar(routed):
    client, provider, root, pid, _, behavior = routed
    behavior.primary = "failed"
    body = request_body(pid)
    client.post(root + "/generation-tasks", json=body)
    job = jobs(client, root)[0]
    assert job["status"] == "completed"
    assert job["lipsync_routing"]["switch_reason"] == "primary_failed"
    assert job["lipsync_routing"]["selected_provider"] == "skyhuman"
    posts = paid_videos(provider)
    assert len(posts) == 2 and posts[0][2]["audio_url"] == posts[1][2]["audio_url"]
    assert posts[1][2]["avatar"] == "same-prepared-avatar"
    client.post(root + "/generation-tasks", json=body)
    assert len(paid_videos(provider)) == 2
    assert "https://cdn-oss.pilihu.vip/result.mp4" in [
        url for url, _ in provider.downloads
    ]
    assert "backup_task_id" not in job["lipsync_routing"]


def test_primary_unknown_submission_never_switches(routed):
    client, provider, root, pid, _, _ = routed
    provider.fail = "/api/digital_human/submit"
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = jobs(client, root)[0]
    assert job["status"] == "unknown"
    assert len(paid_videos(provider)) == 1
    assert (
        client.post(root + f"/generation-tasks/{job['id']}/resume").status_code == 409
    )


def test_backup_unknown_submission_never_retries_even_if_worker_restarts(routed):
    client, provider, root, pid, _, behavior = routed
    behavior.primary = "failed"
    original = provider.request

    def request(vendor, method, path, **kwargs):
        result = original(vendor, method, path, **kwargs)
        if path.endswith("create_by_audio"):
            raise ApiError(502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "lost response")
        return result

    provider.request = request
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = jobs(client, root)[0]
    assert job["status"] == "unknown"
    assert len(paid_videos(provider)) == 2
    with client.app.state.session_factory() as session:
        row = session.get(VideoGenerationRecord, job["id"])
        with pytest.raises(ApiError, match="备用提交结果待确认"):
            video_lipsync.run_lipsync(session, row, client.app.state.settings, provider)
    assert len(paid_videos(provider)) == 2


def test_backup_polling_resume_does_not_submit_again(routed):
    client, provider, root, pid, _, behavior = routed
    behavior.primary, behavior.backup = "failed", "2"
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = jobs(client, root)[0]
    assert (
        job["status"] == "awaiting_resume"
        and job["stage"] == "backup_lipsync_generating"
    )
    behavior.backup = "3"
    client.post(root + f"/generation-tasks/{job['id']}/resume")
    assert jobs(client, root)[0]["status"] == "completed"
    assert len(paid_videos(provider)) == 2


def test_two_confirmed_failures_route_next_new_job_directly_to_backup(routed):
    client, provider, root, pid, _, behavior = routed
    client.app.state.settings.video_lipsync_breaker_seconds = 1800
    behavior.primary = "failed"
    for _ in range(3):
        client.post(root + "/generation-tasks", json=request_body(pid))
    assert len([p for p in paid_videos(provider) if p[0] == "quanyu"]) == 2
    assert len([p for p in paid_videos(provider) if p[0] == "skyhuman"]) == 3
    assert (
        jobs(client, root)[0]["lipsync_routing"]["switch_reason"] == "recent_failures"
    )


def test_clone_is_cached_for_exact_prepared_model_and_unknown_is_never_repeated(routed):
    client, provider, root, pid, _, behavior = routed
    settings = client.app.state.settings
    settings.video_skyhuman_auto_register = True
    settings.video_skyhuman_avatar_map = {}
    behavior.primary = "failed"
    for _ in range(2):
        client.post(root + "/generation-tasks", json=request_body(pid))
    assert all(job["status"] == "completed" for job in jobs(client, root))
    assert behavior.clone_count == 1
    clone = next(p for p in provider.posts if p[1].endswith("create_by_video"))
    assert clone[2]["video_url"] == provider.models()[0]["video_url"]
    with client.app.state.session_factory() as session:
        asset = session.scalar(select(VideoLipsyncAvatarRecord))
        asset.status, asset.provider_task_id, asset.avatar_code = "unknown", None, None
        session.commit()
    client.post(root + "/generation-tasks", json=request_body(pid))
    assert jobs(client, root)[0]["status"] == "unknown"
    assert behavior.clone_count == 1


def test_adapter_uses_backup_bearer_without_exposing_it_in_errors(routed):
    client, _, _, _, _, _ = routed
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"code": 1, "message": "secret upstream body"})

    provider = VideoProviders(client.app.state.settings, httpx.MockTransport(handle))
    with pytest.raises(ApiError) as caught:
        provider.request(
            "skyhuman",
            "POST",
            "/api/v2/fly/avatar/create_by_video",
            headers={"Idempotency-Key": "asset-key"},
            json={},
        )
    assert seen[0].url.host == "skyhumanapi.pilihu.vip"
    assert seen[0].headers["authorization"] == "Bearer test-sky-secret"
    assert seen[0].headers["idempotency-key"] == "asset-key"
    assert "secret upstream body" not in str(caught.value)


def test_new_avatar_reservation_waits_without_duplicate_clone(routed):
    client, provider, root, pid, _, behavior = routed
    behavior.primary = "failed"
    client.post(root + "/generation-tasks", json=request_body(pid))
    settings = client.app.state.settings
    settings.video_skyhuman_avatar_map = {}
    settings.video_skyhuman_auto_register = True
    with client.app.state.session_factory() as session:
        job = session.scalar(select(VideoGenerationRecord))
        asset = VideoLipsyncAvatarRecord(
            id="other-worker-reservation",
            workspace_id=job.workspace_id,
            owner_user_id=job.owner_user_id,
            model_id="11",
            status="submitting",
        )
        session.add(asset)
        session.commit()
        assert video_lipsync.avatar_for_backup(session, job, settings, provider) is None
        assert behavior.clone_count == 0
        asset.status, asset.provider_task_id = "processing", "other-worker-task"
        session.commit()
        assert (
            video_lipsync.avatar_for_backup(session, job, settings, provider)
            == "registered-same-avatar"
        )
        assert behavior.clone_count == 0


def test_migration_supports_sqlite_and_postgres_without_touching_existing_rows(routed):
    import importlib.util
    from io import StringIO
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    client, _, root, pid, _, _ = routed
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261107_0040_video_lipsync_avatars.py"
    )
    spec = importlib.util.spec_from_file_location("video_migration_40", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with client.app.state.engine.begin() as connection:
        VideoLipsyncAvatarRecord.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
    assert client.get(root + "/projects/" + pid).status_code == 200
    output = StringIO()
    with Operations.context(
        MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output},
        )
    ):
        module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE video_lipsync_avatars" in sql
    assert "UNIQUE (workspace_id, owner_user_id, model_id)" in sql
    assert "DROP" not in sql and "UPDATE" not in sql
