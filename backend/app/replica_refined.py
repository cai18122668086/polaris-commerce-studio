"""Route only new exact suites to the byte-pinned sister refined pipeline."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
import sys
import tempfile
from copy import deepcopy
from dataclasses import replace
from functools import wraps
from pathlib import Path
from threading import RLock
from types import ModuleType
from typing import Any

VERSION = "exact-compact-v16"
CONTENT_SHA256 = "63df401796fde30686b4485af519a2f5ee0f3a3577cfd2225dfc352d2cd2c59c"
PACKAGE = "app.replica_exact_versions.v16"
ROOT = Path(__file__).parent / "replica_exact_versions/v16"
_lock = RLock()
_loaded = False


def applies(values: dict[str, Any]) -> bool:
    return bool(
        values.get("replication_method") == "exact"
        and values.get("replica_speed") != "fast"
        and (
            values.get("_exact_model_protocol") == VERSION
            or (values.get("native_snapshot", {}).get("model_protocol") or {}).get(
                "version"
            )
            == VERSION
        )
    )


def bundle(name: str) -> ModuleType:
    global _loaded
    with _lock:
        if not _loaded:
            manifest = json.loads(
                (ROOT / "source-manifest.json").read_text(encoding="utf-8")
            )
            names = {Path(p).stem for p in manifest["files"] if p.endswith(".py")}
            shared = set()
            for relative, expected in manifest["files"].items():
                path = ROOT / relative
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != expected["sha256"]:
                    raise RuntimeError("Refined source changed: " + relative)
                if relative.endswith(".py"):
                    parsed = ast.parse(data.decode("utf-8-sig"))
                    if relative == "replica.py":
                        parsed = ast.Module(
                            body=[
                                n
                                for n in parsed.body
                                if isinstance(
                                    n, (ast.FunctionDef, ast.AsyncFunctionDef)
                                )
                            ],
                            type_ignores=[],
                        )
                    for node in ast.walk(parsed):
                        if isinstance(node, ast.ImportFrom) and node.level == 1:
                            if node.module:
                                shared.add(node.module.split(".")[0])
                            else:
                                shared.update(alias.name for alias in node.names)
            package = importlib.import_module(PACKAGE)
            # ORM, auth, storage, gateway and application services are singletons.
            # Frozen quality modules resolve inside this private namespace.
            for module in sorted(shared - names):
                current = importlib.import_module("app." + module)
                sys.modules[PACKAGE + "." + module] = current
                setattr(package, module, current)
            native = importlib.import_module(PACKAGE + ".replica_native")
            if os.name == "nt":
                original_init = native.NativeReplicaRun.__init__

                @wraps(original_init)
                def local_run(self: Any, *args: Any, **kwargs: Any) -> None:
                    # The frozen code's package-relative Windows root exceeds
                    # MAX_PATH once crop evidence hashes are appended. Use the
                    # same temporary runtime location as the Linux service.
                    if kwargs.get("root") is None:
                        kwargs["root"] = (
                            Path(tempfile.gettempdir()) / "polaris-replica" / args[1]
                        )
                    original_init(self, *args, **kwargs)

                native.NativeReplicaRun.__init__ = local_run
            protocol = importlib.import_module(PACKAGE + ".replica_exact_compact")
            if protocol.protocol_binding() != {
                "version": VERSION,
                "content_sha256": CONTENT_SHA256,
            }:
                raise RuntimeError("Refined protocol binding changed")
            direct = importlib.import_module(PACKAGE + ".replica_direct_delivery")
            sister_retry_source = direct.retry_source

            def retry_source(values: Any, request: Any, factory: Any) -> Any:
                source = sister_retry_source(values, request, factory)
                if source:
                    return source
                # The website also permits an explicit continuation after
                # cancellation. Retain the sister plan/pixel validation and
                # require the site's original atomic child authorization.
                from .models import JobRecord
                from .replica_failure_recovery import allows_unconfirmed_retry

                with factory() as session:
                    job = session.get(JobRecord, request.job_id)
                    parent = (
                        session.get(JobRecord, job.retry_of_job_id)
                        if job and job.retry_of_job_id
                        else None
                    )
                    if (
                        not parent
                        or parent.status != "cancelled"
                        or not allows_unconfirmed_retry(job, parent.id)
                        or job.workspace_id != request.workspace_id
                        or parent.workspace_id != request.workspace_id
                        or parent.configuration.get("replica_session_id")
                        != job.configuration.get("replica_session_id")
                        or parent.configuration.get("settings", {}).get(
                            "replica_plan_hash"
                        )
                        != values.get("plan_hash")
                        or not any(
                            e.get("from") == parent.id and e.get("to") == job.id
                            for e in values.get("retry_events", [])
                        )
                    ):
                        return None
                    parent_id = parent.id
                    document_id = job.configuration["replica_session_id"]
                snapshot = (
                    values.get("native_executions", {})
                    .get(parent_id, {})
                    .get("snapshot")
                )
                if not snapshot:
                    raise native.ReplicaNativeError("原任务缺少持久检查点。")
                direct.validate_source(
                    snapshot,
                    values["native_snapshot"],
                    f"{request.workspace_id}/replica/{document_id}/",
                )
                return snapshot, parent_id

            direct.__dict__["retry_source"] = retry_source
            _loaded = True
            analysis_module()
        return importlib.import_module(PACKAGE + "." + name)


def analysis_module() -> ModuleType:
    qualified = PACKAGE + ".replica"
    if qualified in sys.modules:
        return sys.modules[qualified]
    native = bundle("replica_native")
    if qualified in sys.modules:
        return sys.modules[qualified]
    from . import replica

    module = ModuleType(qualified)
    module.__dict__.update(vars(replica))
    module.__name__, module.__package__, module.__file__ = (
        qualified,
        PACKAGE,
        str(ROOT / "replica.py"),
    )
    module.__spec__ = importlib.util.spec_from_file_location(qualified, module.__file__)
    module.__dict__.update(
        {
            name: getattr(native, name)
            for name in (
                "SKILLS",
                "NativeReplicaRun",
                "ReplicaAnalysisUnavailable",
                "ReplicaInputTooLarge",
                "ReplicaNativeError",
                "ReplicaPlanAuditRejected",
                "ReplicaSegmentationInvalid",
                "native_accounting",
                "read_json",
            )
        }
    )
    parsed = ast.parse((ROOT / "replica.py").read_text(encoding="utf-8-sig"))
    functions = [
        n for n in parsed.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for function in functions:
        function.decorator_list = []
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    code = ast.fix_missing_locations(
        ast.Module(body=[future, *functions], type_ignores=[])
    )
    # Compile the original function bodies against site services. The sister
    # product routes and module-level marketplace integrations are not loaded.
    exec(compile(code, module.__file__, "exec"), module.__dict__)
    sys.modules[qualified] = module
    sys.modules[PACKAGE].__dict__["replica"] = module
    return module


class RefinedGateway:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    async def edit(self, request: Any) -> Any:
        # Quality logic is the sister source. Site dispatch/retry policy stays
        # one POST per invocation and retains its existing backup admission.
        return await self.delegate.edit(replace(request, single_dispatch=True))


def delivery_provider(owner: Any) -> Any:
    module = bundle("replica_style_delivery")
    provider = module.ReplicaDeliveryProvider(
        owner.session_factory,
        RefinedGateway(owner.gateway),
        owner.storage,
    )
    provider._load = owner._load
    original_execute = provider.execute
    completion = bundle("replica_completion")
    native = bundle("replica_native")

    async def execute(request: Any) -> Any:
        values, document_id, ordinal = owner._load(request)
        if not completion.available(values.get("native_snapshot", {})):
            return await original_execute(request)
        try:
            # Use the site's authorized child snapshot, including the immutable
            # unknown-call lineage, before the sister completion executor loads it.
            if not values.get("native_executions", {}).get(request.job_id):
                from .models import JobRecord
                from .replica_failure_recovery import allows_unconfirmed_retry

                with owner.session_factory() as session:
                    job = session.get(JobRecord, request.job_id)
                    parent = (
                        session.get(JobRecord, job.retry_of_job_id)
                        if job and job.retry_of_job_id
                        else None
                    )
                    if parent is not None and parent.status == "cancelled":
                        if (
                            not allows_unconfirmed_retry(job, parent.id)
                            or parent.workspace_id != request.workspace_id
                            or parent.configuration.get("replica_session_id")
                            != document_id
                            or parent.configuration.get("settings", {}).get(
                                "replica_plan_hash"
                            )
                            != values.get("plan_hash")
                            or not any(
                                e.get("from") == parent.id and e.get("to") == job.id
                                for e in values.get("retry_events", [])
                            )
                        ):
                            raise native.ReplicaNativeError("接续任务归属不一致。")
                        prior = values.get("native_executions", {}).get(parent.id, {})
                        snapshot = prior.get("snapshot")
                        if (
                            not snapshot
                            or snapshot["files"].get(completion.PLAN)
                            != values["native_snapshot"]["files"][completion.PLAN]
                        ):
                            raise native.ReplicaNativeError("接续缺少一致的持久方案。")
                        values = deepcopy(values)
                        values["native_executions"][job.id] = deepcopy(prior)
            return await completion.execute(
                provider, request, values, document_id, ordinal
            )
        except native.ReplicaNativeError as error:
            from .provider import ProviderOutcome, ProviderResult

            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                error_code=error.code,
                error_message="生成任务的持久检查点无法恢复。",
                retryable=False,
            )

    provider.execute = execute
    return provider
