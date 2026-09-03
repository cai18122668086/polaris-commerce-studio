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
import threading
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


class LocalWorkerTaskError(LocalWorkerError):
    """A safe task outcome that can be reported to the control plane."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


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

    def _request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        body = None
        if payload is not None:
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
            method=method,
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

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def _get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

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

    def control(self, worker_id: str, task_id: str) -> dict[str, Any]:
        worker = _validate_id(worker_id, "worker_id")
        task = _validate_id(task_id, "task_id")
        return self._get(f"/api/ecommerce/workers/{worker}/tasks/{task}/control")


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
        except LocalWorkerTaskError as exc:
            with suppress(Exception):
                self.api.complete(
                    self.worker_id,
                    task_id,
                    {
                        "fencing_token": fencing_token,
                        "outcome": "failed",
                        "error_code": exc.code,
                        "error_message_safe": exc.message,
                    },
                )
            raise
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


def build_local_product_crawler(
    *, timeout_ms: int = 30_000
) -> Callable[[Path, Mapping[str, Any]], Mapping[str, Any]]:
    """Build a profile-backed browser crawler for claimed domestic tasks.

    The returned callback accepts only the local profile path and server task
    metadata. It never reads or serializes profile files itself; the platform
    adapters use the path to launch their isolated browser session.
    """

    if timeout_ms <= 0:
        raise LocalWorkerError("BROWSER_TIMEOUT_INVALID")

    def crawl(profile_path: Path, task: Mapping[str, Any]) -> Mapping[str, Any]:
        from .ecommerce_1688 import crawl_one_1688_browser
        from .ecommerce_fetcher import crawl_one_browser
        from .ecommerce_jd import crawl_one_jd_browser
        from .ecommerce_pinduoduo import crawl_one_pinduoduo_browser
        from .ecommerce_routes import _normalise

        url = task.get("canonical_url") or task.get("source_url")
        if not isinstance(url, str) or not url.strip():
            raise LocalWorkerTaskError("TASK_URL_REQUIRED", "任务缺少商品链接。")
        task_platform = task.get("platform")
        if not isinstance(task_platform, str):
            raise LocalWorkerTaskError("TASK_PLATFORM_REQUIRED", "任务缺少平台标识。")
        request_payload = task.get("request_payload")
        include_desc = True
        if isinstance(request_payload, Mapping):
            include_desc = bool(request_payload.get("includeDescImages", True))
        platform = task_platform.casefold()
        result: Any
        try:
            if platform in {"taobao", "tmall"}:
                result = crawl_one_browser(url, timeout_ms, str(profile_path))
            elif platform == "1688":
                result = crawl_one_1688_browser(url, timeout_ms, str(profile_path))
            elif platform == "jd":
                result = crawl_one_jd_browser(url, timeout_ms, str(profile_path))
            elif platform == "pinduoduo":
                result = crawl_one_pinduoduo_browser(url, timeout_ms, str(profile_path))
            else:
                raise LocalWorkerTaskError(
                    "PLATFORM_NOT_SUPPORTED", "本机代理暂不支持该平台。"
                )
        except LocalWorkerTaskError:
            raise
        except TimeoutError as exc:
            raise LocalWorkerTaskError(
                "WORKER_TIMEOUT", "本机浏览器执行超时，请稍后重试。"
            ) from exc
        except Exception as exc:
            raise LocalWorkerTaskError(
                "WORKER_BROWSER_CRASH", "本机浏览器执行失败，请稍后重试。"
            ) from exc

        access_state = getattr(result, "access_state", None)
        status_value = getattr(result, "status", None)
        if access_state in {"login_required", "risk_controlled", "captcha_required"}:
            messages = {
                "login_required": "本机账号需要重新登录。",
                "risk_controlled": "商品页面触发安全验证，请人工处理后重试。",
                "captcha_required": "商品页面需要人工完成验证码验证。",
            }
            raise LocalWorkerTaskError(access_state.upper(), messages[access_state])
        if status_value is not None and status_value != "product":
            status_code = {
                "login_required": "LOGIN_REQUIRED",
                "risk_controlled": "RISK_CONTROL_PAGE",
                "captcha_required": "CAPTCHA_REQUIRED",
                "product_not_found": "PRODUCT_NOT_FOUND",
            }.get(str(status_value), "WORKER_FAILED")
            raise LocalWorkerTaskError(status_code, "本机商品页面未返回可用商品结果。")
        normalized = _normalise(result, url.strip(), include_desc)
        normalized["platform"] = platform
        if not normalized.get("title") and not normalized.get("numIid"):
            raise LocalWorkerTaskError(
                "RESULT_INCOMPLETE", "本机未读取到完整商品字段。"
            )
        return normalized

    return crawl


class LocalWorkerLoop:
    """Poll the control plane while keeping task leases alive."""

    def __init__(
        self,
        api: WorkerApiClient,
        runtime: LocalWorkerRuntime,
        *,
        protocol_version: str = "worker.v1",
        agent_version: str = "local-runtime.v1",
        capabilities: list[str] | None = None,
        heartbeat_interval_seconds: float = 20.0,
        poll_interval_seconds: float = 2.0,
        lease_renew_interval_seconds: float = 30.0,
    ) -> None:
        if heartbeat_interval_seconds <= 0 or poll_interval_seconds <= 0:
            raise LocalWorkerError("WORKER_INTERVAL_INVALID")
        if lease_renew_interval_seconds <= 0:
            raise LocalWorkerError("WORKER_LEASE_INTERVAL_INVALID")
        self.api = api
        self.runtime = runtime
        self.protocol_version = protocol_version
        self.agent_version = agent_version
        self.capabilities = list(capabilities or [])
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_renew_interval_seconds = lease_renew_interval_seconds

    def _heartbeat(self, ready: bool) -> dict[str, Any]:
        return self.api.heartbeat(
            self.runtime.worker_id,
            {
                "protocol_version": self.protocol_version,
                "agent_version": self.agent_version,
                "capabilities": self.capabilities,
                "ready": ready,
            },
        )

    def run_once(
        self, crawl: Callable[[Path, Mapping[str, Any]], Mapping[str, Any]]
    ) -> bool:
        """Claim and execute at most one task; return whether work was done."""

        response = self.api.claim(self.runtime.worker_id, self._platforms())
        task = response.get("data")
        if task is None:
            return False
        if not isinstance(task, Mapping):
            raise LocalWorkerError("WORKER_TASK_INVALID")
        task_id = _validate_id(str(task.get("id", "")), "task_id")
        lease = task.get("lease")
        if not isinstance(lease, Mapping) or not isinstance(
            lease.get("fencing_token"), int
        ):
            raise LocalWorkerError("TASK_LEASE_REQUIRED")
        fencing_token = int(lease["fencing_token"])
        stop_renew = threading.Event()

        def renew() -> None:
            while not stop_renew.wait(self.lease_renew_interval_seconds):
                try:
                    self.api.renew_lease(self.runtime.worker_id, task_id, fencing_token)
                except LocalWorkerError:
                    return

        renewer = threading.Thread(
            target=renew, name="polaris-lease-renew", daemon=True
        )
        renewer.start()
        try:
            self.runtime.execute_claimed(task, crawl)
        finally:
            stop_renew.set()
            renewer.join(timeout=max(1.0, self.lease_renew_interval_seconds))
        return True

    def run(
        self,
        crawl: Callable[[Path, Mapping[str, Any]], Mapping[str, Any]],
        stop_event: threading.Event | None = None,
    ) -> None:
        """Run until ``stop_event`` is set, tolerating transient API outages."""

        stop = stop_event or threading.Event()
        last_heartbeat = 0.0
        try:
            while not stop.is_set():
                now = time.monotonic()
                if now - last_heartbeat >= self.heartbeat_interval_seconds:
                    try:
                        self._heartbeat(True)
                        last_heartbeat = now
                    except LocalWorkerError:
                        stop.wait(self.poll_interval_seconds)
                        continue
                try:
                    did_work = self.run_once(crawl)
                except LocalWorkerError:
                    did_work = False
                if not did_work:
                    stop.wait(self.poll_interval_seconds)
        finally:
            with suppress(LocalWorkerError):
                self._heartbeat(False)

    def _platforms(self) -> list[str] | None:
        platforms = [
            value.rsplit(".", 1)[-1]
            for value in self.capabilities
            if value.startswith("browser.")
        ]
        return list(dict.fromkeys(platforms)) or None
