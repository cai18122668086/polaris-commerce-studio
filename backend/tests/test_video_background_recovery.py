"""Automatic recovery, persistent scheduling and cross-worker paid-call safety."""

import importlib.util
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from pathlib import Path
from threading import Barrier, Event

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import video_generation
from app.main import create_app
from app.models import UserRecord, WorkspaceMemberRecord, WorkspaceRecord, utc_now
from app.video_generation_media import set_stage
from app.video_generation_models import VideoGenerationRecord, VideoGenerationRunRecord
from app.video_generation_recovery import VideoRecoveryService
from app.video_generation_runtime import VideoRunLost, acquire_run
from app.video_stage_timing import transition
from tests.test_video_generation import request_body
from tests.test_video_model_recovery import registered

pytest_plugins = ["tests.test_video_generation"]


@pytest.fixture(autouse=True)
def immediate_lookup(monkeypatch):
    monkeypatch.setattr("app.video_generation_media.MODEL_LOOKUP_WINDOW", 0)


def pending(video_gen):
    client, _, provider, root, pid, _ = video_gen
    provider.audio_seconds = 4
    provider.fail = "/api/digital_human/models"
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "awaiting_resume"
    return job


def due(client, job_id, *, crashed=False):
    with client.app.state.session_factory() as session:
        record = session.get(VideoGenerationRunRecord, job_id)
        record.retry_at = utc_now() - timedelta(seconds=1)
        if crashed:
            record.owner_token = "dead-process"
            record.lease_until = utc_now() - timedelta(seconds=1)
            job = session.get(VideoGenerationRecord, job_id)
            job.status = "running"
            job.updated_at = utc_now() - timedelta(seconds=200)
        session.commit()


def service(client, provider):
    return VideoRecoveryService(
        client.app.state.session_factory, client.app.state.settings, provider
    )


def finish(recovery, job_id):
    recovery.active[job_id][0].result(timeout=15)


def test_background_recovers_after_query_window_without_resume_click(video_gen):
    job = pending(video_gen)
    client, _, provider, root, _, _ = video_gen
    original_audio = job["audio_url"]
    provider.models = lambda: [registered("极光正向动作-" + job["id"])]
    due(client, job["id"])
    recovery = service(client, provider)
    try:
        assert recovery.tick() == 1
        finish(recovery, job["id"])
        done = client.get(root + "/generation-tasks").json()[0]
        assert done["status"] == "completed" and done["audio_url"] == original_audio
        assert [p for _, p, _ in provider.posts] == [
            "/api/tts/generate",
            "/api/digital_human/models",
            "/api/digital_human/submit",
        ]
        assert provider.posts[-1][2]["model_id"] == 951
        assert recovery.tick() == 0
    finally:
        recovery.stop()


def test_backoff_survives_service_restart_then_model_is_automatically_adopted(
    video_gen,
):
    job = pending(video_gen)
    client, _, provider, root, _, _ = video_gen
    due(client, job["id"])
    first = service(client, provider)
    try:
        assert first.tick() == 1
        finish(first, job["id"])
        assert (
            client.get(root + "/generation-tasks").json()[0]["status"]
            == "awaiting_resume"
        )
    finally:
        first.stop()
    second = service(client, provider)
    try:
        assert second.tick() == 0  # The new process respects persisted retry_at.
        with client.app.state.session_factory() as session:
            record = session.get(VideoGenerationRunRecord, job["id"])
            assert record.attempts == 2 and record.retry_at is not None
        provider.models = lambda: [registered("极光正向动作-" + job["id"])]
        due(client, job["id"])
        assert second.tick() == 1
        finish(second, job["id"])
        assert client.get(root + "/generation-tasks").json()[0]["status"] == "completed"
        assert len(provider.posts) == 3
    finally:
        second.stop()


def test_crashed_registration_worker_is_reclaimed_without_paid_registration(video_gen):
    job = pending(video_gen)
    client, _, provider, root, _, _ = video_gen
    due(client, job["id"], crashed=True)
    provider.models = lambda: [registered("极光正向动作-" + job["id"])]
    recovery = service(client, provider)
    try:
        assert recovery.tick() == 1
        finish(recovery, job["id"])
        assert client.get(root + "/generation-tasks").json()[0]["status"] == "completed"
        assert [p for _, p, _ in provider.posts].count("/api/digital_human/models") == 1
    finally:
        recovery.stop()


def test_two_instances_racing_cannot_submit_lipsync_twice(video_gen):
    job = pending(video_gen)
    client, _, provider, root, _, _ = video_gen
    due(client, job["id"])
    entered, proceed = Event(), Event()

    def models():
        entered.set()
        assert proceed.wait(10)
        return [registered("极光正向动作-" + job["id"])]

    provider.models = models
    a, b = service(client, provider), service(client, provider)
    barrier = Barrier(2)

    def tick(instance):
        barrier.wait(timeout=5)
        return instance.tick()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(tick, instance) for instance in [a, b]]
            assert sum(f.result(timeout=10) for f in futures) == 1
        assert entered.wait(5)
        assert a.tick() + b.tick() == 0
        assert (
            client.post(root + f"/generation-tasks/{job['id']}/resume").status_code
            == 409
        )
        proceed.set()
        owner = a if job["id"] in a.active else b
        finish(owner, job["id"])
        assert client.get(root + "/generation-tasks").json()[0]["status"] == "completed"
        assert [p for _, p, _ in provider.posts].count("/api/digital_human/submit") == 1
    finally:
        proceed.set()
        a.stop()
        b.stop()


def test_shutdown_late_lookup_cannot_start_paid_work_and_new_service_continues(
    video_gen,
):
    job = pending(video_gen)
    client, _, provider, root, _, _ = video_gen
    entered, proceed = Event(), Event()

    def models():
        entered.set()
        assert proceed.wait(10)
        return [registered("极光正向动作-" + job["id"])]

    provider.models = models
    due(client, job["id"])
    first = service(client, provider)
    assert first.tick() == 1 and entered.wait(5)
    first.stop()
    proceed.set()
    finish(first, job["id"])
    assert len(provider.posts) == 2  # The retired worker cannot start lipsync.
    due(client, job["id"], crashed=True)
    second = service(client, provider)
    try:
        assert second.tick() == 1
        finish(second, job["id"])
        assert client.get(root + "/generation-tasks").json()[0]["status"] == "completed"
        assert len(provider.posts) == 3
    finally:
        proceed.set()
        second.stop()


@pytest.mark.parametrize("revoked", ["user", "workspace", "membership", "viewer"])
def test_recovery_rechecks_current_owner_permissions_before_provider_calls(
    video_gen, revoked
):
    job = pending(video_gen)
    client, _, provider, _, _, _ = video_gen
    due(client, job["id"])
    with client.app.state.session_factory() as session:
        row = session.get(VideoGenerationRecord, job["id"])
        if revoked == "user":
            session.get(UserRecord, row.owner_user_id).status = "suspended"
        elif revoked == "workspace":
            session.get(WorkspaceRecord, row.workspace_id).status = "suspended"
        else:
            member = session.get(
                WorkspaceMemberRecord, (row.workspace_id, row.owner_user_id)
            )
            if revoked == "viewer":
                member.role = "viewer"
            else:
                member.status = "suspended"
        session.commit()
    provider.models = lambda: pytest.fail(
        "Revoked jobs cannot query or start provider work"
    )
    recovery = service(client, provider)
    try:
        assert recovery.tick() == 0
        assert len(provider.posts) == 2
    finally:
        recovery.stop()


def test_valid_lease_cannot_be_stolen_and_expired_owner_is_fenced(video_gen):
    job = pending(video_gen)
    client, _, provider, _, _, _ = video_gen
    factory, settings = client.app.state.session_factory, client.app.state.settings
    first = acquire_run(factory, settings, job["id"])
    assert first and acquire_run(factory, settings, job["id"]) is None
    with factory() as session:
        record = session.get(VideoGenerationRunRecord, job["id"])
        record.lease_until = utc_now() - timedelta(seconds=1)
        session.commit()
    second = acquire_run(factory, settings, job["id"])
    assert second
    try:
        with factory() as session:
            session.info["video_run_lease"] = first
            row = session.get(VideoGenerationRecord, job["id"])
            with pytest.raises(VideoRunLost):
                set_stage(session, row, "lipsync_submitting")
            session.rollback()
            assert (
                session.get(VideoGenerationRecord, job["id"]).stage
                == "forward_model_submitting"
            )
        first.release()
        with factory() as session:
            assert (
                session.get(VideoGenerationRunRecord, job["id"]).owner_token
                == second.token
            )
            second.guard(session)
            session.commit()
        assert len(provider.posts) == 2
    finally:
        second.release()


@pytest.mark.parametrize(
    "stage",
    [
        "tts_submitting",
        "h3_submitting",
        "lipsync_submitting",
        "backup_lipsync_submitting",
    ],
)
def test_restart_never_resubmits_unconfirmed_paid_operation(
    video_gen, monkeypatch, stage
):
    client, _, provider, root, pid, _ = video_gen
    real_worker = video_generation.process_generation
    monkeypatch.setattr(
        video_generation, "process_generation", lambda *args, **kwargs: None
    )
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = client.get(root + "/generation-tasks").json()[0]
    factory = client.app.state.session_factory
    with factory() as session:
        row = session.get(VideoGenerationRecord, job["id"])
        row.status, row.stage = "running", stage
        row.updated_at = utc_now() - timedelta(seconds=200)
        row.details = {
            **row.details,
            "stage_history": transition([], stage),
            **(
                {
                    "lipsync_routing": {
                        "primary_status": "failed",
                        "backup_submission_started": True,
                    }
                }
                if stage == "backup_lipsync_submitting"
                else {}
            ),
        }
        session.commit()
    recovery = service(client, provider)
    try:
        assert recovery.tick() == 0
        with factory() as session:
            row = session.get(VideoGenerationRecord, job["id"])
            assert row.status == "unknown"
            # Even an old caller putting it back in queued cannot repeat POST.
            row.status = "queued"
            session.commit()
        real_worker(factory, client.app.state.settings, job["id"], provider)
        assert provider.posts == [] and provider.uploads == []
        assert client.get(root + "/generation-tasks").json()[0]["status"] == "unknown"
    finally:
        recovery.stop()


def test_known_remote_task_continues_after_restart_without_any_paid_post(
    video_gen, monkeypatch
):
    client, _, provider, root, pid, _ = video_gen
    monkeypatch.setattr(
        video_generation, "process_generation", lambda *args, **kwargs: None
    )
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = client.get(root + "/generation-tasks").json()[0]
    with client.app.state.session_factory() as session:
        row = session.get(VideoGenerationRecord, job["id"])
        row.status, row.stage, row.provider_task_id = (
            "running",
            "lipsync_generating",
            "existing-task",
        )
        row.updated_at = utc_now() - timedelta(seconds=200)
        row.details = {
            **row.details,
            "audio_url": "https://sowa.oss-cn-beijing.aliyuncs.com/audio.mp3",
            "stage_history": transition([], "lipsync_submitting"),
        }
        session.commit()
    recovery = service(client, provider)
    try:
        assert recovery.tick() == 1
        finish(recovery, job["id"])
        done = client.get(root + "/generation-tasks").json()[0]
        assert done["status"] == "completed" and provider.posts == []
        with client.app.state.session_factory() as session:
            assert (
                session.get(VideoGenerationRecord, job["id"]).provider_task_id
                == "existing-task"
            )
    finally:
        recovery.stop()


def test_real_lifespan_starts_scanner_and_resumes_existing_job(video_gen):
    job = pending(video_gen)
    client, auth, provider, root, _, _ = video_gen
    assert not hasattr(client.app.state, "video_recovery")
    due(client, job["id"])
    provider.models = lambda: [registered("极光正向动作-" + job["id"])]
    settings = client.app.state.settings.model_copy(
        update={
            "video_background_recovery_enabled": True,
            "video_recovery_interval_seconds": 1,
        }
    )
    app = create_app(settings, auth)
    app.state.video_providers = provider
    with TestClient(app) as second:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = second.get(root + "/generation-tasks").json()[0]
            if result["status"] == "completed":
                break
            time.sleep(0.05)
        assert result["status"] == "completed"
        scanner = app.state.video_recovery
    assert scanner.stopped.is_set() and not scanner.thread.is_alive()
    assert len(provider.posts) == 3


def test_additive_runtime_migration_preserves_rows_and_supports_both_databases(
    tmp_path,
):
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261107_0041_video_generation_runs.py"
    )
    spec = importlib.util.spec_from_file_location("video_runs_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.sqlite3"))
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE video_generations (id VARCHAR(40) PRIMARY KEY)")
        )
        connection.execute(text("INSERT INTO video_generations VALUES ('existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        connection.execute(
            text("INSERT INTO video_generation_runs (job_id) VALUES ('existing')")
        )
        assert (
            connection.execute(
                text("SELECT attempts FROM video_generation_runs")
            ).scalar()
            == 0
        )
        assert (
            connection.execute(text("SELECT id FROM video_generations")).scalar()
            == "existing"
        )
    output = StringIO()
    with Operations.context(
        MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
        )
    ):
        module.upgrade()
    sql = output.getvalue()
    assert (
        "TIMESTAMP WITH TIME ZONE" in sql
        and "CREATE TABLE video_generation_runs" in sql
    )
    assert "DROP" not in sql and "UPDATE users" not in sql
