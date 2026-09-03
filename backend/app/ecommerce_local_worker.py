"""Local-only runtime primitives for the outbound ecommerce worker.

This module is intentionally transport- and browser-client-agnostic.  It owns
local profile paths and locks, while :class:`WorkerApiClient` sends only the
structured worker protocol messages.  No profile contents, cookies, local
storage, or CDP endpoint are ever serialized by this module.
"""

from __future__ import annotations

import errno
import json
import os
import re
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SENSITIVE_KEYS = {
    "cookie",
    "cookies",
    "localstorage",
    "profile",
    "profilepath",
    "cdp",
    "debuggingport",
}


class LocalWorkerError(RuntimeError):
    """A safe, non-secret local worker error."""


def _validate_id(value: str, label: str) -> str:
    normalized = value.strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise LocalWorkerError(f"INVALID_{label.upper()}")
    return normalized


def _assert_no_sensitive_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).replace("_", "").casefold()
            if normalized in _SENSITIVE_KEYS:
                raise LocalWorkerError("SENSITIVE_FIELD_BLOCKED")
            _assert_no_sensitive_fields(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_no_sensitive_fields(child)


class LocalProfileStore:
    """Resolve account profiles below one user-selected local directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks = self.root / ".locks"
        self._locks.mkdir(parents=True, exist_ok=True)

    def profile_path(self, account_id: str) -> Path:
        safe_account = _validate_id(account_id, "account_id")
        path = (self.root / "accounts" / safe_account).resolve()
        if not path.is_relative_to(self.root):
            raise LocalWorkerError("PROFILE_PATH_OUTSIDE_ROOT")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @contextmanager
    def lock(
        self, account_id: str, *, stale_after_seconds: int = 3600
    ) -> Iterator[Path]:
        """Hold an exclusive cross-process lock for one account profile."""

        safe_account = _validate_id(account_id, "account_id")
        lock_path = self._locks / f"{safe_account}.lock"
        descriptor: int | None = None
        for attempt in range(2):
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError as exc:
                if attempt == 0 and self._reclaim_dead_lock(
                    lock_path, stale_after_seconds
                ):
                    continue
                raise LocalWorkerError("PROFILE_BUSY") from exc
        if descriptor is None:
            raise LocalWorkerError("PROFILE_BUSY")
        try:
            try:
                os.write(descriptor, str(os.getpid()).encode("ascii"))
            finally:
                os.close(descriptor)
            yield self.profile_path(safe_account)
        finally:
            with suppress(FileNotFoundError):
                lock_path.unlink()

    @staticmethod
    def _reclaim_dead_lock(lock_path: Path, stale_after_seconds: int) -> bool:
        try:
            if time.time() - lock_path.stat().st_mtime <= stale_after_seconds:
                return False
            owner_pid = int(lock_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return False
        try:
            os.kill(owner_pid, 0)
        except ProcessLookupError:
            with suppress(FileNotFoundError):
                lock_path.unlink()
            return True
        except PermissionError:
            # Windows may deny the probe for a live process. Never reclaim it.
            return False
        except OSError as exc:
            # Windows reports an invalid PID as ERROR_INVALID_PARAMETER rather
            # than raising ProcessLookupError; both mean the owner is gone.
            if exc.errno == errno.ESRCH or getattr(exc, "winerror", None) in {
                87,
                128,
            }:
                with suppress(FileNotFoundError):
                    lock_path.unlink()
                return True
            return False
        return False


class WorkerApiClient:
    """Small outbound HTTPS client for the worker protocol."""

    def __init__(
        self, base_url: str, session_token: str, *, timeout: float = 20.0
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            raise LocalWorkerError("WORKER_API_REQUIRES_HTTPS")
        if not parsed.netloc:
            raise LocalWorkerError("INVALID_WORKER_API_URL")
        if not session_token.strip():
            raise LocalWorkerError("WORKER_TOKEN_REQUIRED")
        self.base_url = base_url.rstrip("/") + "/"
        self.session_token = session_token
        self.timeout = timeout

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        _assert_no_sensitive_fields(payload)
        body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=body,
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                parsed = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError) as exc:
            raise LocalWorkerError("WORKER_API_UNAVAILABLE") from exc
        except (TypeError, ValueError) as exc:
            raise LocalWorkerError("WORKER_API_INVALID_RESPONSE") from exc
        if not isinstance(parsed, dict):
            raise LocalWorkerError("WORKER_API_INVALID_RESPONSE")
        return parsed

    def heartbeat(self, worker_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._post(
            f"/api/ecommerce/workers/{_validate_id(worker_id, 'worker_id')}/heartbeat",
            payload,
        )

    def claim(
        self, worker_id: str, platforms: list[str] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if platforms is not None:
            payload["platforms"] = platforms
        worker = _validate_id(worker_id, "worker_id")
        return self._post(f"/api/ecommerce/workers/{worker}/tasks/claim", payload)

    def renew_lease(
        self, worker_id: str, task_id: str, fencing_token: int
    ) -> dict[str, Any]:
        worker = _validate_id(worker_id, "worker_id")
        task = _validate_id(task_id, "task_id")
        return self._post(
            f"/api/ecommerce/workers/{worker}/tasks/{task}/lease",
            {"fencing_token": fencing_token},
        )

    def complete(
        self, worker_id: str, task_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        worker = _validate_id(worker_id, "worker_id")
        task = _validate_id(task_id, "task_id")
        return self._post(
            f"/api/ecommerce/workers/{worker}/tasks/{task}/complete", payload
        )

    def upload_result(
        self, worker_id: str, task_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        worker = _validate_id(worker_id, "worker_id")
        task = _validate_id(task_id, "task_id")
        return self._post(
            f"/api/ecommerce/workers/{worker}/tasks/{task}/result", payload
        )


class LocalWorkerRuntime:
    """Execute one claimed task with a local profile and report safe outcomes."""

    def __init__(
        self, api: WorkerApiClient, worker_id: str, profiles: LocalProfileStore
    ) -> None:
        self.api = api
        self.worker_id = _validate_id(worker_id, "worker_id")
        self.profiles = profiles

    def execute_claimed(
        self,
        task: Mapping[str, Any],
        crawl: Callable[[Path, Mapping[str, Any]], Mapping[str, Any]],
    ) -> dict[str, Any]:
        _assert_no_sensitive_fields(task)
        task_id = _validate_id(str(task.get("id", "")), "task_id")
        account_id = task.get("account_id")
        if not isinstance(account_id, str):
            raise LocalWorkerError("TASK_ACCOUNT_REQUIRED")
        lease = task.get("lease")
        if not isinstance(lease, Mapping) or not isinstance(
            lease.get("fencing_token"), int
        ):
            raise LocalWorkerError("TASK_LEASE_REQUIRED")
        fencing_token = int(lease["fencing_token"])
        try:
            with self.profiles.lock(account_id) as profile_path:
                result = crawl(profile_path, task)
                if not isinstance(result, Mapping):
                    raise LocalWorkerError("WORKER_RESULT_INVALID")
                return self.api.upload_result(
                    self.worker_id,
                    task_id,
                    {"fencing_token": fencing_token, "result": dict(result)},
                )
        except LocalWorkerError:
            raise
        except Exception as exc:
            with suppress(Exception):
                self.api.complete(
                    self.worker_id,
                    task_id,
                    {
                        "fencing_token": fencing_token,
                        "outcome": "failed",
                        "error_code": "WORKER_BROWSER_CRASH",
                        "error_message_safe": "本机浏览器执行失败。",
                    },
                )
            raise LocalWorkerError("WORKER_BROWSER_CRASH") from exc
