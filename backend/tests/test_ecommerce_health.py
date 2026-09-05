from __future__ import annotations

from fastapi.testclient import TestClient


def test_ecommerce_health_exposes_aggregate_queue_and_lease_metrics(
    client: TestClient,
) -> None:
    response = client.get("/health/ecommerce")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["metrics"]["task_counts"] == {}
    assert payload["metrics"]["active_leases"] == 0
    assert payload["metrics"]["expired_leases"] == 0
    assert payload["metrics"]["oldest_queued_at"] is None
    assert payload["metrics"]["oldest_queued_age_seconds"] == 0.0


def test_ecommerce_health_counts_queued_tasks_without_exposing_payload(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.ecommerce_crawl_tasks._schedule", lambda app, task_id: None
    )
    created = client.post(
        "/api/ecommerce/crawl-tasks",
        json={
            "workspace_id": "ws_test",
            "url": "https://item.taobao.com/item.htm?id=123456789012",
            "platform": "taobao",
        },
    )
    assert created.status_code == 202

    response = client.get("/health/ecommerce")
    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["task_counts"]["queued"] == 1
    assert "source_url" not in response.text
    assert "profile_path" not in response.text


def test_health_ready_reports_broker_only_for_celery(settings, monkeypatch) -> None:
    settings.task_dispatcher = "celery"
    settings.celery_broker_url = "redis://example.invalid:6379/0"
    monkeypatch.setattr(
        "app.main.check_task_broker", lambda url: "failed" if url else "ok"
    )

    from app.main import create_app

    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["task_broker"] == "failed"
