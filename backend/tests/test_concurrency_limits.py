"""Concurrency hardening: Celery time limits, running-job caps, rate limits."""

import asyncio
from types import SimpleNamespace

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import services
from app.celery_app import celery_app
from app.celery_limits import queue_limits, task_annotations
from app.config import Settings
from app.errors import ApiError
from app.execution import JOB_TIME_LIMIT_EXCEEDED
from app.main import create_app
from app.models import (
    JobItemRecord,
    JobRecord,
    WorkspaceCreditAccountRecord,
    utc_now,
)
from app.rate_limit import (
    DEFAULT_TRUSTED_PROXIES,
    RATE_LIMITED_MESSAGE,
    RateLimitMiddleware,
    client_ip,
    parse_networks,
    user_key,
)
from app.tasks import execute_job, soft_time_limit
from app.video_generation import enforce_active_video_limit
from tests.test_customer_credit_billing import WORKSPACE, seed_job

# --- Celery time limits -----------------------------------------------------


def test_queue_limits_follow_settings_and_add_grace():
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert queue_limits(settings, None) == {"soft_time_limit": 2400, "time_limit": 2520}
    assert queue_limits(settings, "domestic_detail_v431")["soft_time_limit"] == 3600
    assert queue_limits(settings, "one_click_replica")["soft_time_limit"] == 3000
    assert queue_limits(settings, "editing")["time_limit"] == 4320
    assert queue_limits(settings, "editing-planning")["soft_time_limit"] == 1800
    custom = settings.model_copy(
        update={
            "celery_soft_time_limit_detail_seconds": 900,
            "celery_time_limit_grace_seconds": 60,
        }
    )
    assert queue_limits(custom, "domestic_detail_v431") == {
        "soft_time_limit": 900,
        "time_limit": 960,
    }


def test_every_long_task_has_a_registered_time_limit():
    annotations = celery_app.conf.task_annotations
    expected = task_annotations(Settings(_env_file=None))  # type: ignore[call-arg]
    for name in (
        "polaris.process_job",
        "polaris.cancel_job",
        "polaris.process_editing_task",
        "polaris.process_editing_planning_task",
    ):
        limits = annotations[name]
        assert limits == expected[name]
        assert limits["time_limit"] > limits["soft_time_limit"] > 0


def test_soft_limit_prefers_the_per_message_value():
    task = SimpleNamespace(
        request=SimpleNamespace(timelimit=(3720, 3600)), soft_time_limit=2400
    )
    assert soft_time_limit(task) == 3600
    task = SimpleNamespace(
        request=SimpleNamespace(timelimit=None), soft_time_limit=2400
    )
    assert soft_time_limit(task) == 2400


def test_dispatcher_sends_per_queue_limits(client, settings, monkeypatch):
    from app import outbox, tasks

    sent = []
    monkeypatch.setattr(
        tasks.process_job, "apply_async", lambda **kwargs: sent.append(kwargs)
    )
    with client.app.state.session_factory() as session:
        job, _ = seed_job(session, kind="reference_remix", count=1, deliverables=False)
        job.configuration = {"settings": {}, "replica_session_id": "rs_1"}
        session.commit()
        job_id = job.id
    celery_settings = settings.model_copy(update={"task_dispatcher": "celery"})
    outbox._dispatch(
        celery_settings,
        client.app.state.task_runner,
        event_type="job.submitted",
        dedupe_key="k1",
        payload={"job_id": job_id},
    )
    assert sent[0]["queue"] == "one_click_replica"
    assert sent[0]["soft_time_limit"] == 3000
    assert sent[0]["time_limit"] == 3120


class HangingRunner:
    def __init__(self, coordinator, error=None):
        self.coordinator = coordinator
        self.error = error

    async def run(self, job_id):
        if self.error is not None:
            raise self.error
        await asyncio.sleep(60)


def _reserved_job(client, *, succeeded=0):
    with client.app.state.session_factory() as session:
        job, items = seed_job(session, count=4, deliverables=False)
        account = session.get(WorkspaceCreditAccountRecord, WORKSPACE)
        balance = account.balance_credits
        hold = services.reserve_image_credits(session, WORKSPACE, job)
        assert hold.reserved_credits == 60
        job.status = "processing"
        items[0].status = "running"
        session.commit()
        return job.id, balance


@pytest.mark.parametrize("via", ["deadline", "celery_soft_limit"])
def test_time_limit_fails_job_and_releases_reservation(client, monkeypatch, via):
    import app.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "DEADLINE_MARGIN_SECONDS", 30)
    job_id, balance = _reserved_job(client)
    coordinator = client.app.state.task_runner.coordinator
    runner = HangingRunner(
        coordinator, SoftTimeLimitExceeded() if via == "celery_soft_limit" else None
    )
    # 30.2 s soft limit minus the 30 s margin -> the job is stopped after ~1 s.
    result = execute_job(runner, job_id, 30.2)
    assert result is not None and result.value == "failed"
    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, job_id)
        assert job.error_code == JOB_TIME_LIMIT_EXCEEDED
        assert "超时" in job.error_message
        items = session.query(JobItemRecord).filter_by(job_id=job_id).all()
        assert {item.status for item in items} == {"failed"}
        account = session.get(WorkspaceCreditAccountRecord, WORKSPACE)
        assert account.reserved_credits == 0
        assert account.balance_credits == balance
    # Repeated timeouts (e.g. redelivery) stay idempotent.
    assert coordinator.fail_timed_out(job_id).value == "failed"


def test_time_limit_does_not_swallow_unrelated_timeouts(client):
    job_id, _ = _reserved_job(client)
    runner = HangingRunner(
        client.app.state.task_runner.coordinator, TimeoutError("upstream")
    )
    with pytest.raises(TimeoutError):
        execute_job(runner, job_id, 2400)


# --- Running-job caps ---------------------------------------------------------


def test_running_image_job_cap_returns_chinese_429(client):
    services.set_user_active_image_job_limit(2)
    try:
        with client.app.state.session_factory() as session:
            for status in (
                "queued",
                "processing",
                "awaiting_confirmation",
                "cancelled",
            ):
                job, _ = seed_job(session, count=1, deliverables=False)
                job.status = status
                if status == "cancelled":
                    job.finished_at = utc_now()
            session.commit()
            with pytest.raises(ApiError) as caught:
                services.enforce_active_job_limit(session, WORKSPACE)
            assert caught.value.status_code == 429
            assert caught.value.code == "USER_ACTIVE_JOB_LIMIT_REACHED"
            assert "2 个生成任务正在进行" in caught.value.message
            session.rollback()
        services.set_user_active_image_job_limit(3)
        with client.app.state.session_factory() as session:
            services.enforce_active_job_limit(session, WORKSPACE)
            session.rollback()
    finally:
        services.set_user_active_image_job_limit(0)


def test_running_image_job_cap_over_http_uses_error_envelope(client):
    from uuid import uuid4

    from tests.test_api import local_edit_payload, upload_asset

    source = upload_asset(client)
    mask = upload_asset(client, filename="mask.png", media_kind="mask")
    services.set_user_active_image_job_limit(1)
    try:
        with client.app.state.session_factory() as session:
            job, _ = seed_job(session, count=1, deliverables=False)
            session.commit()
        response = client.post(
            f"/api/v1/workspaces/{WORKSPACE}/jobs",
            headers={"Idempotency-Key": str(uuid4())},
            json=local_edit_payload(source["id"], mask["id"]),
        )
        assert response.status_code == 429, response.text
        error = response.json()["error"]
        assert error["code"] == "USER_ACTIVE_JOB_LIMIT_REACHED"
        assert "请等待" in error["message"]
    finally:
        services.set_user_active_image_job_limit(0)


def test_video_cap():
    busy = SimpleNamespace(scalar=lambda _query: 1)
    idle = SimpleNamespace(scalar=lambda _query: 0)
    enforce_active_video_limit(idle, "user_1", 1)
    enforce_active_video_limit(busy, "user_1", 0)  # disabled
    with pytest.raises(ApiError) as caught:
        enforce_active_video_limit(busy, "user_1", 1)
    assert caught.value.status_code == 429
    assert caught.value.code == "USER_ACTIVE_VIDEO_LIMIT_REACHED"
    assert "视频正在生成" in caught.value.message


# --- Rate limiting ------------------------------------------------------------


class FakeRedis:
    def __init__(self):
        self.counts: dict[str, int] = {}
        self.fail = False
        self.calls = 0

    async def eval(self, _script, numkeys, *args):
        self.calls += 1
        if self.fail:
            raise ConnectionError("redis down")
        out = []
        for key in args[:numkeys]:
            self.counts[key] = self.counts.get(key, 0) + 1
            out.append(self.counts[key])
        return out


def limited_app(redis, *, per_ip=3, per_user=2, now=lambda: 1000.0):
    app = FastAPI()

    @app.get("/api/v1/ping")
    def ping():
        return {"ok": True}

    @app.get("/health/ready")
    def ready():
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        redis_url="redis://unused",
        window_seconds=60,
        per_ip=per_ip,
        per_user=per_user,
        client_factory=lambda: redis,
        clock=now,
    )
    return app


def test_per_ip_fixed_window_and_health_exempt():
    redis = FakeRedis()
    client = TestClient(limited_app(redis))
    assert [client.get("/api/v1/ping").status_code for _ in range(3)] == [200] * 3
    blocked = client.get("/api/v1/ping")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert blocked.json()["error"]["message"] == RATE_LIMITED_MESSAGE
    assert int(blocked.headers["retry-after"]) >= 1
    calls = redis.calls
    assert all(client.get("/health/ready").status_code == 200 for _ in range(10))
    assert redis.calls == calls


def test_per_user_limit_keys_on_session_not_ip():
    redis = FakeRedis()
    client = TestClient(limited_app(redis, per_ip=100, per_user=2))
    a = {"Cookie": "sAccessToken=token-a"}
    b = {"Cookie": "sAccessToken=token-b"}
    assert client.get("/api/v1/ping", headers=a).status_code == 200
    assert client.get("/api/v1/ping", headers=a).status_code == 200
    assert client.get("/api/v1/ping", headers=a).status_code == 429
    assert client.get("/api/v1/ping", headers=b).status_code == 200
    assert not any("token-a" in key for key in redis.counts)


def test_window_rolls_over():
    redis = FakeRedis()
    clock = {"now": 1000.0}
    client = TestClient(limited_app(redis, per_ip=1, now=lambda: clock["now"]))
    assert client.get("/api/v1/ping").status_code == 200
    assert client.get("/api/v1/ping").status_code == 429
    clock["now"] += 60
    assert client.get("/api/v1/ping").status_code == 200


def test_fails_open_and_pauses_when_redis_is_down():
    redis = FakeRedis()
    redis.fail = True
    client = TestClient(limited_app(redis, per_ip=1))
    assert all(client.get("/api/v1/ping").status_code == 200 for _ in range(5))
    assert redis.calls == 1  # cool-down: no per-request retries against Redis


def test_user_key_hashes_bearer_and_cookie():
    scope = {"headers": [(b"authorization", b"Bearer abc")]}
    assert user_key(scope) and "abc" not in user_key(scope)
    assert user_key({"headers": []}) is None


def test_app_with_unreachable_redis_still_serves(settings):
    unreachable = settings.model_copy(
        update={
            "rate_limit_enabled": True,
            "rate_limit_redis_url": "redis://127.0.0.1:1/0",
        }
    )
    with TestClient(create_app(unreachable)) as client:
        assert client.get("/health/live").status_code in {200, 404}
        assert client.get("/api/v1/workspaces").status_code == 200


TRUSTED = parse_networks(DEFAULT_TRUSTED_PROXIES)


def scope_from(peer, **headers):
    return {
        "type": "http",
        "client": (peer, 5000),
        "headers": [
            (k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()
        ],
    }


def test_spoofed_forwarding_headers_from_untrusted_peer_are_ignored():
    scope = scope_from("203.0.113.9", x_forwarded_for="1.1.1.1", x_real_ip="2.2.2.2")
    assert client_ip(scope, TRUSTED) == "203.0.113.9"


def test_trusted_proxy_forwarded_for_is_used():
    assert (
        client_ip(scope_from("172.18.0.4", x_forwarded_for="198.51.100.7"), TRUSTED)
        == "198.51.100.7"
    )
    # Rightmost untrusted hop wins: a client-injected left value is skipped.
    chained = scope_from(
        "172.18.0.4", x_forwarded_for="1.1.1.1, 198.51.100.7, 10.0.0.3"
    )
    assert client_ip(chained, TRUSTED) == "198.51.100.7"
    assert (
        client_ip(scope_from("172.18.0.4", x_real_ip="198.51.100.8"), TRUSTED)
        == "198.51.100.8"
    )
    assert (
        client_ip(scope_from("172.18.0.4", x_forwarded_for="not-an-ip"), TRUSTED)
        == "172.18.0.4"
    )
    assert client_ip(scope_from("172.18.0.4"), TRUSTED) == "172.18.0.4"


def test_per_ip_limit_is_per_real_client_behind_the_proxy():
    redis = FakeRedis()

    async def ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RateLimitMiddleware(
        ok,
        redis_url="redis://unused",
        window_seconds=60,
        per_ip=1,
        per_user=0,
        client_factory=lambda: redis,
        clock=lambda: 1000.0,
    )

    def status(scope):
        sent = []

        async def send(message):
            sent.append(message)

        async def receive():
            return {"type": "http.request"}

        asyncio.run(
            middleware(
                {**scope, "method": "GET", "path": "/api/v1/ping"}, receive, send
            )
        )
        return sent[0]["status"]

    caddy = "172.18.0.4"
    assert status(scope_from(caddy, x_forwarded_for="198.51.100.1")) == 200
    assert status(scope_from(caddy, x_forwarded_for="198.51.100.2")) == 200
    assert status(scope_from(caddy, x_forwarded_for="198.51.100.1")) == 429
    # An untrusted peer cannot rotate its identity through the header.
    assert status(scope_from("203.0.113.9", x_forwarded_for="198.51.100.3")) == 200
    assert status(scope_from("203.0.113.9", x_forwarded_for="198.51.100.4")) == 429


def test_plan_confirmation_respects_running_cap(client):
    services.set_user_active_image_job_limit(1)
    try:
        with client.app.state.session_factory() as session:
            waiting, _ = seed_job(session, count=1, deliverables=False)
            waiting.status = "awaiting_confirmation"
            session.commit()
            # The waiting job itself is not counted.
            services.enforce_running_image_job_limit(session, WORKSPACE)
            session.rollback()
            running, _ = seed_job(session, count=1, deliverables=False)
            running.status = "processing"
            session.commit()
            with pytest.raises(ApiError) as caught:
                services.enforce_running_image_job_limit(session, WORKSPACE)
            assert caught.value.code == "USER_ACTIVE_JOB_LIMIT_REACHED"
    finally:
        services.set_user_active_image_job_limit(0)
    with client.app.state.session_factory() as session:
        services.enforce_running_image_job_limit(session, WORKSPACE)  # disabled
