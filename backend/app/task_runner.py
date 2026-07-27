"""Compatibility facade for the API/outbox execution dependency."""

from sqlalchemy.orm import Session, sessionmaker

from .domain import JobStatus
from .execution import ExecutionCoordinator, build_fake_coordinator


class MockTaskRunner:
    """Zero-cost runner retaining the Phase 1.1 internal constructor."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        delay_seconds: float,
    ) -> None:
        self.coordinator: ExecutionCoordinator = build_fake_coordinator(
            session_factory,
            delay_seconds,
        )

    @property
    def session_factory(self) -> sessionmaker[Session]:
        return self.coordinator.session_factory

    async def run(self, job_id: str) -> JobStatus | None:
        return await self.coordinator.run(job_id)

    async def cancel(self, job_id: str) -> JobStatus | None:
        return self.coordinator.cancel(job_id)
