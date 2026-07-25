import asyncio
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from .models import JobRecord
from .schemas import TERMINAL_JOB_STATUSES, JobStatus, JobType


class MockTaskRunner:
    """Simulates task transitions without invoking external image services."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        delay_seconds: float,
    ) -> None:
        self.session_factory = session_factory
        self.delay_seconds = delay_seconds

    async def run(self, job_id: str) -> JobStatus | None:
        job_type = self._job_type(job_id)
        if job_type is None:
            return None

        if job_type == JobType.DETAIL_PACK:
            if not self._transition(job_id, JobStatus.PLANNING, 12, start=True):
                return self._status(job_id)
            await asyncio.sleep(self.delay_seconds)

        if not self._transition(job_id, JobStatus.PROCESSING, 42, start=True):
            return self._status(job_id)
        await asyncio.sleep(self.delay_seconds)
        return self._complete(job_id)

    def _job_type(self, job_id: str) -> JobType | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id)
            return JobType(job.type) if job else None

    def _status(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id)
            return JobStatus(job.status) if job else None

    def _transition(
        self,
        job_id: str,
        status: JobStatus,
        progress: int,
        *,
        start: bool = False,
    ) -> bool:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id)
            if not job or JobStatus(job.status) in TERMINAL_JOB_STATUSES:
                return False
            job.status = status.value
            job.progress = progress
            if start and job.started_at is None:
                job.started_at = datetime.now(UTC)
            session.commit()
            return True

    def _complete(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id)
            if not job:
                return None
            if JobStatus(job.status) in TERMINAL_JOB_STATUSES:
                return JobStatus(job.status)
            job.status = JobStatus.COMPLETED.value
            job.progress = 100
            job.raw_outputs = [
                {
                    "kind": "phase1_mock_result",
                    "job_id": job.id,
                    "note": "未调用图片 API；仅验证任务状态与输出契约。",
                }
            ]
            job.delivery_outputs = []
            job.usage = {
                "reported": False,
                "reason": "phase1_mock_runner",
            }
            job.api_request_count = 0
            job.actual_cost = 0.0
            job.finished_at = datetime.now(UTC)
            session.commit()
            return JobStatus.COMPLETED
