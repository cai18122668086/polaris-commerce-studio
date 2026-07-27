"""Compatibility facade for the API/outbox execution dependency."""

from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .domain import JobStatus
from .execution import ExecutionCoordinator, build_fake_coordinator
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
        )

    @property
    def session_factory(self) -> sessionmaker[Session]:
        return self.coordinator.session_factory

    async def run(self, job_id: str) -> JobStatus | None:
        return await self.coordinator.run(job_id)

    async def cancel(self, job_id: str) -> JobStatus | None:
        return self.coordinator.cancel(job_id)


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
    )
