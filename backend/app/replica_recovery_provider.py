"""Application recovery wrapper; frozen native protocols remain byte-identical."""

from copy import deepcopy
from dataclasses import replace
from typing import Any

from .models import JobRecord
from .replica_failure_recovery import allows_unconfirmed_retry, derived_retry_snapshot
from .replica_style_delivery import ReplicaDeliveryProvider


class RecoverableReplicaProvider(ReplicaDeliveryProvider):
    def __init__(
        self, session_factory: Any, gateway: Any, storage: Any, **kwargs: Any
    ) -> None:
        super().__init__(
            session_factory,
            RecoveryImageGateway(gateway, session_factory),
            storage,
            **kwargs,
        )

    def _load(self, request: Any) -> tuple[dict[str, Any], str, int]:
        values, document_id, ordinal = super()._load(request)
        if values.get("native_executions", {}).get(request.job_id):
            return values, document_id, ordinal
        with self.session_factory() as session:
            job = session.get(JobRecord, request.job_id)
            if job is None or not allows_unconfirmed_retry(job, job.retry_of_job_id):
                return values, document_id, ordinal
            parent_id = job.retry_of_job_id
            grant = dict(job.configuration["_replica_retry"])
        prior = values.get("native_executions", {}).get(parent_id, {})
        if prior.get("snapshot"):
            values = deepcopy(values)
            values["native_executions"][parent_id]["snapshot"] = derived_retry_snapshot(
                prior["snapshot"], parent_id, grant
            )
        return values, document_id, ordinal

    async def execute(self, request: Any) -> Any:
        from . import replica_completion
        from .provider import ProviderOutcome, ProviderResult
        from .replica_native import ReplicaNativeError

        try:
            values, document_id, ordinal = self._load(request)
            from .replica_refined import applies, delivery_provider

            if applies(values):
                provider = delivery_provider(self)
                return await provider.execute(request)
            if replica_completion.available(values.get("native_snapshot", {})):
                return await replica_completion.execute(
                    self, request, values, document_id, ordinal
                )
        except ReplicaNativeError as error:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                error_code=error.code,
                error_message="生成任务的持久检查点无法恢复。",
                retryable=False,
            )
        return await super().execute(request)


class RecoveryImageGateway:
    def __init__(self, delegate: Any, session_factory: Any) -> None:
        self.delegate, self.session_factory = delegate, session_factory

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    async def edit(self, request: Any) -> Any:
        with self.session_factory() as session:
            job = session.get(JobRecord, request.job_id)
            if job is not None and allows_unconfirmed_retry(job, job.retry_of_job_id):
                request = replace(
                    request,
                    image_route=job.configuration["_replica_retry"]["image_route"],
                )
        return await self.delegate.edit(request)
