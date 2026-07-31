"""Compatibility facade for the API/outbox execution dependency."""

import math
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .domain import JobStatus
from .execution import ExecutionCoordinator, build_fake_coordinator
from .services import set_quota_enabled
from .storage import ImageStorage


class MockTaskRunner:
    """Zero-cost runner retaining the Phase 1.1 internal constructor."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        delay_seconds: float,
        *,
        storage: ImageStorage | None = None,
        xinghe_gateway: object | None = None,
        xinghe_concurrency: int = 6,
        budget_limit_micros: int = 200_000_000,
        medium_price_micros: int = 45_000,
        high_price_micros: int = 90_000,
        xinghe_skill_root: Path | None = None,
    ) -> None:
        self.coordinator: ExecutionCoordinator = build_fake_coordinator(
            session_factory,
            delay_seconds,
            storage=storage,
            xinghe_gateway=xinghe_gateway,
            xinghe_concurrency=xinghe_concurrency,
            budget_limit_micros=budget_limit_micros,
            medium_price_micros=medium_price_micros,
            high_price_micros=high_price_micros,
            xinghe_skill_root=xinghe_skill_root,
        )

    @property
    def session_factory(self) -> sessionmaker[Session]:
        return self.coordinator.session_factory

    async def run(self, job_id: str) -> JobStatus | None:
        return await self.coordinator.run(job_id)

    async def cancel(self, job_id: str) -> JobStatus | None:
        return self.coordinator.cancel(job_id)


def validate_task_runner_settings(settings: Settings) -> None:
    """Reject unsafe real-provider configuration without exposing secret values."""

    if settings.task_runner == "mock":
        return
    if not settings.tengli_api_key.get_secret_value().strip():
        raise RuntimeError("tengli task runner requires a non-empty API key")
    budget = settings.tengli_smoke_budget_usd
    if not math.isfinite(budget) or budget <= 0 or budget > 2:
        raise RuntimeError(
            "tengli task runner budget must be greater than 0 and at most USD 2"
        )
    if settings.xinghe_concurrency != 2:
        raise RuntimeError("tengli task runner concurrency must be exactly 2")
    if settings.provider_quota_enabled:
        if settings.tengli_daily_budget_usd <= 0:
            raise RuntimeError("tengli task runner daily budget must be configured")
        if settings.tengli_monthly_budget_usd < settings.tengli_daily_budget_usd:
            raise RuntimeError(
                "tengli task runner monthly budget must cover the daily budget"
            )
        if settings.tengli_daily_request_limit <= 0:
            raise RuntimeError(
                "tengli task runner daily request limit must be configured"
            )

    try:
        endpoint = urlsplit(settings.tengli_base_url)
        valid_endpoint = (
            endpoint.scheme in {"http", "https"} and endpoint.hostname is not None
        )
    except ValueError:
        valid_endpoint = False
    if not valid_endpoint:
        raise RuntimeError("tengli task runner requires a valid provider base URL")
    if not settings.tengli_image_model.strip():
        raise RuntimeError("tengli task runner requires an image model")
    if not settings.tengli_vision_model.strip():
        raise RuntimeError("tengli task runner requires a vision model")


def build_task_runner(
    session_factory: sessionmaker[Session],
    settings: Settings,
    storage: ImageStorage,
) -> MockTaskRunner:
    """Build the configured runner for every API and worker startup path."""

    set_quota_enabled(settings.provider_quota_enabled)
    if settings.task_runner == "mock":
        return MockTaskRunner(
            session_factory,
            settings.mock_job_delay_seconds,
            storage=storage,
            xinghe_concurrency=settings.xinghe_concurrency,
            budget_limit_micros=int(settings.tengli_smoke_budget_usd * 1_000_000),
            medium_price_micros=settings.xinghe_medium_price_micros,
            high_price_micros=settings.xinghe_high_price_micros,
            xinghe_skill_root=settings.xinghe_skill_root,
        )

    validate_task_runner_settings(settings)
    return build_tengli_task_runner(
        session_factory,
        settings,
        storage,
        concurrency=settings.xinghe_concurrency,
    )


def build_tengli_task_runner(
    session_factory: sessionmaker[Session],
    settings: Settings,
    storage: ImageStorage,
    *,
    concurrency: int = 2,
) -> MockTaskRunner:
    """Explicit real-provider factory for the independently controlled smoke."""

    from .xinghe_agent import build_tengli_gateway

    return MockTaskRunner(
        session_factory,
        0,
        storage=storage,
        xinghe_gateway=build_tengli_gateway(settings),
        xinghe_concurrency=concurrency,
        budget_limit_micros=int(settings.tengli_smoke_budget_usd * 1_000_000),
        medium_price_micros=settings.xinghe_medium_price_micros,
        high_price_micros=settings.xinghe_high_price_micros,
        xinghe_skill_root=settings.xinghe_skill_root,
    )
