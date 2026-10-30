"""Bounded planner-only fallback with durable, individually attributable calls."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections.abc import Mapping
from copy import copy, deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .xinghe_agent import (
        PlannerCallResult,
        PlannerRequest,
        TengliOpenAICompatibleGateway,
    )

VERSION = "planner-recovery-v1"
TRANSPORT_ERRORS = frozenset(
    {
        "PROVIDER_TRANSPORT_FAILED",
        "PLANNER_STREAM_INTERRUPTED",
        "PLANNER_STREAM_ERROR",
        "PLANNER_STREAM_INVALID",
        "PROVIDER_RESPONSE_INVALID",
        "PLANNER_RESPONSE_INVALID",
    }
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def retryable(code: str | None, status: int | None) -> bool:
    return (
        code in TRANSPORT_ERRORS
        or status in {401, 402, 403, 404, 408, 409, 425, 429}
        or (status is not None and status >= 500)
    )


def result_digest(value: Mapping[str, Any]) -> str:
    return digest(
        {
            key: value.get(key)
            for key in (
                "payload",
                "provider_request_id",
                "raw_usage",
                "error_code",
                "http_status",
                "content_sha256",
                "content_utf8_bytes",
            )
        }
    )


def _route(gateway: Any, route: Any) -> dict[str, Any]:
    from .domestic_detail.planner_dispatch import route_descriptor

    return route_descriptor(
        provider=gateway.provider_name,
        route=route.name,
        model=route.planner_model,
        endpoint=route.planner_base_url.rstrip("/") + "/v1/chat/completions",
        credential=route.planner_api_key,
    )


class Journal:
    def __init__(
        self, root: Path | None, request: PlannerRequest, routes: list[dict[str, Any]]
    ) -> None:
        self.path: Path | None = None
        self.lock: Path | None = None
        self.lock_fd: int | None = None
        semantics = asdict(request)
        semantics.pop("planning_deadline", None)
        semantics["sources"] = [
            {key: val for key, val in source.items() if key != "payload"}
            for source in semantics["sources"]
        ]
        self.binding = digest(
            {"request": semantics, "routes": routes, "version": VERSION}
        )
        self.state: dict[str, Any] = {"binding": self.binding, "calls": []}
        if root is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request.job_id):
                raise ValueError("Invalid planner job identifier")
            folder = root / digest(request.workspace_id)[:24] / request.job_id
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.path = folder / (digest(request.idempotency_key) + ".json")
            self.lock = self.path.with_suffix(".lock")

    def enter(self) -> dict[str, Any] | None:
        if self.path is None or self.lock is None:
            return None
        self.lock_fd = os.open(self.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        if self.path.exists():
            saved = json.loads(self.path.read_bytes())
            if saved.get("binding") != self.binding:
                raise ValueError(
                    "Planner inputs changed under an existing logical call"
                )
            self.state = saved
            if "result" not in saved:
                raise ValueError(
                    "Reconcile the interrupted planner call before dispatching again"
                )
            if digest(saved["result"]) != saved.get("result_sha256"):
                raise ValueError("Saved planner completion changed")
            return dict(saved["result"])
        return None

    def write(self) -> None:
        if self.path is None:
            return
        pending = self.path.with_suffix(".pending")
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(self.state, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, self.path)

    def begin(self, route: dict[str, Any], ordinal: int) -> None:
        self.state["calls"].append(
            {"ordinal": ordinal, "route": route, "state": "invoked"}
        )
        self.write()

    def returned(self, result: PlannerCallResult) -> None:
        self.state["calls"][-1].update(state="returned", result=asdict(result))
        self.write()

    def finish(self, result: PlannerCallResult) -> None:
        self.state.update(result=asdict(result), result_sha256=digest(asdict(result)))
        self.write()

    def close(self) -> None:
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
            assert self.lock is not None
            self.lock.unlink()


def _not_sent(code: str) -> PlannerCallResult:
    from .xinghe_agent import PlannerCallResult, normalize_usage

    return PlannerCallResult(
        payload=None,
        provider_request_id=None,
        raw_usage=None,
        normalized_usage=normalize_usage(None),
        api_latency_seconds=0,
        actual_cost_micros=0,
        error_code=code,
        error_message="规划回执正在处理或需要核对，未发送重复请求。",
        external_request=False,
    )


def _replayed(value: Mapping[str, Any]) -> PlannerCallResult:
    from .xinghe_agent import PlannerCallResult

    result = PlannerCallResult(**dict(value))
    return replace(
        result,
        external_request=False,
        supplemental_results=tuple(
            _replayed(asdict(call)) for call in result.supplemental_results
        ),
    )


async def recover(
    gateway: TengliOpenAICompatibleGateway, request: PlannerRequest
) -> PlannerCallResult:
    from .domestic_detail.planner_dispatch import (
        NATIVE_PLANNER_PROFILES,
        PlannerDispatchError,
        require_route,
        select_route,
    )

    routes = list(gateway._ordered_routes())[:4]
    descriptors = [_route(gateway, route) for route in routes]
    if request.native_dispatch is not None:
        try:
            select_route(gateway, require_route(request.native_dispatch))
        except PlannerDispatchError as exc:
            return _not_sent(exc.code)
    journal = Journal(gateway.planner_receipt_root, request, descriptors)
    started = time.monotonic()
    calls: list[PlannerCallResult] = []
    records: list[dict[str, Any]] = []
    bound = descriptors[0]
    try:
        saved = journal.enter()
        if saved is not None:
            return _replayed(saved)
        # Each alternate account gets one attempt. Only one additional retry
        # is permitted across the entire chain, after alternates are exhausted.
        schedule = list(enumerate(routes))
        if gateway.planner_transient_retries:
            schedule.append((0, routes[0]))
        schedule = schedule[:5]
        budget = gateway.planner_timeout_seconds or gateway.timeout_seconds
        deadline = min(started + budget, request.planning_deadline or float("inf"))
        for ordinal, (index, route) in enumerate(schedule, 1):
            if ordinal > len(routes):
                if not calls or calls[-1].http_status in {401, 402, 403, 404}:
                    break
                await asyncio.sleep(
                    min(
                        gateway.planner_retry_backoff_seconds,
                        max(0, deadline - time.monotonic()),
                    )
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            child = copy(gateway)
            child.planner_recovery_enabled = False
            child._provider_routes = {route.name: route}
            child._rotation_order = (route.name,)
            child.planner_model = route.planner_model
            child.planner_timeout_seconds = remaining
            if index == 0 and len(routes) > 1:
                child.planner_timeout_seconds = min(
                    remaining, gateway.planner_primary_timeout_seconds
                )
            child.external_network_request_count = 0
            actual_route = descriptors[index]
            call = replace(
                request,
                native_dispatch=actual_route
                if request.planning_profile in NATIVE_PLANNER_PROFILES
                else None,
                idempotency_key=request.idempotency_key
                + ":"
                + VERSION
                + ":"
                + str(ordinal),
                planning_deadline=deadline,
            )
            journal.begin(actual_route, ordinal)
            try:
                result = await child._plan_single(call)
            except Exception:
                result = replace(
                    _not_sent("PLANNER_PROVIDER_FAILED"), actual_cost_micros=None
                )
            gateway.external_network_request_count += (
                child.external_network_request_count
            )
            metadata = {
                "version": VERSION,
                "ordinal": ordinal,
                "route": actual_route,
                "streaming": gateway.planner_streaming_enabled,
                "transport_attempts": child.external_network_request_count,
            }
            result = replace(
                result,
                provider_envelope={
                    **(result.provider_envelope or {}),
                    "planner_attempt": metadata,
                },
                external_request=child.external_network_request_count > 0,
            )
            calls.append(result)
            journal.returned(result)
            records.append(
                {
                    "ordinal": ordinal,
                    "route": actual_route,
                    "http_status": result.http_status,
                    "error_code": result.error_code,
                    "dispatch": (result.provider_envelope or {}).get(
                        "native_planner_dispatch"
                    ),
                    "result_sha256": result_digest(asdict(result)),
                    "provider_request_id": result.provider_request_id,
                    "raw_usage": result.raw_usage,
                    "normalized_usage": result.normalized_usage,
                    "actual_cost_micros": result.actual_cost_micros,
                    "transport_attempts": child.external_network_request_count,
                }
            )
            if result.error_code is None or not retryable(
                result.error_code, result.http_status
            ):
                break
        if not calls:
            return _not_sent("PLANNER_RECOVERY_DEADLINE")
        proof = {
            "version": VERSION,
            "bound_route": bound,
            "routes": descriptors,
            "attempts": records,
            "selected_attempt": len(records),
            "elapsed_seconds": time.monotonic() - started,
        }
        proof["sha256"] = digest(proof)
        result = replace(
            calls[-1],
            provider_envelope={
                **(calls[-1].provider_envelope or {}),
                "planner_recovery": proof,
            },
            supplemental_results=tuple(calls[:-1]),
        )
        journal.finish(result)
        return result
    except FileExistsError:
        return _not_sent("PLANNER_RECOVERY_IN_PROGRESS")
    except (OSError, ValueError, TypeError, KeyError):
        if calls:
            return replace(
                calls[-1],
                payload=None,
                error_code="PLANNER_RECOVERY_RECEIPT_INVALID",
                error_message="规划调用记录需要核对，已停止后续调用。",
                supplemental_results=tuple(calls[:-1]),
            )
        return _not_sent("PLANNER_RECOVERY_RECEIPT_INVALID")
    finally:
        journal.close()


def validate_chain(
    value: Mapping[str, Any], bound: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate all original dispatches before accepting a native fallback reply."""
    from .domestic_detail.planner_dispatch import (
        PlannerDispatchError,
        require_route,
        validate_dispatch_result,
    )

    try:
        proof = value["provider_envelope"]["planner_recovery"]
        assert proof["version"] == VERSION
        assert proof["sha256"] == digest(
            {k: v for k, v in proof.items() if k != "sha256"}
        )
        assert require_route(proof["bound_route"]) == dict(bound)
        allowed = [require_route(route) for route in proof["routes"]]
        assert 1 <= len(allowed) <= 4 and allowed[0] == dict(bound)
        attempts = proof["attempts"]
        assert isinstance(attempts, list) and 1 <= len(attempts) <= min(
            5, len(allowed) + 1
        )
        assert proof["selected_attempt"] == len(attempts)
        for index, attempt in enumerate(attempts):
            route = require_route(attempt["route"])
            expected = allowed[index] if index < len(allowed) else allowed[0]
            assert route == expected and attempt["ordinal"] == index + 1
            assert attempt["transport_attempts"] in (0, 1)
            if index + 1 < len(attempts):
                assert attempt["error_code"] is not None
                assert retryable(attempt["error_code"], attempt["http_status"])
            if index + 1 == len(attempts):
                assert attempt["result_sha256"] == result_digest(value)
                assert (
                    attempt["dispatch"]
                    == value["provider_envelope"]["native_planner_dispatch"]
                )
            else:
                validate_dispatch_result(
                    {
                        "error_code": attempt["error_code"],
                        "provider_envelope": {
                            "native_planner_dispatch": attempt["dispatch"]
                        },
                    },
                    route,
                )
        return require_route(attempts[-1]["route"])
    except (AssertionError, TypeError, KeyError, ValueError) as exc:
        raise PlannerDispatchError(
            "NATIVE_PLANNER_DISPATCH_INVALID",
            "Planner recovery dispatch evidence changed",
        ) from exc


def summary(result: PlannerCallResult) -> dict[str, Any] | None:
    proof = (getattr(result, "provider_envelope", None) or {}).get("planner_recovery")
    return deepcopy(proof) if isinstance(proof, dict) else None


def total_cost(result: PlannerCallResult) -> int | None:
    costs = [
        result.actual_cost_micros,
        *(total_cost(call) for call in getattr(result, "supplemental_results", ())),
    ]
    return (
        sum(value for value in costs if value is not None)
        if all(v is not None for v in costs)
        else None
    )
