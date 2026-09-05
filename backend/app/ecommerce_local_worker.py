"""Local-only runtime primitives for the outbound ecommerce worker.

This module is intentionally transport- and browser-client-agnostic.  It owns
local profile paths and locks, while :class:`WorkerApiClient` sends only the
structured worker protocol messages.  No profile contents, cookies, local
storage, or CDP endpoint are ever serialized by this module.
"""

from __future__ import annotations

import argparse
import base64
import errno
import json
import os
import re
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
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
_DEFAULT_CAPABILITIES = (
    "browser.taobao",
    "browser.tmall",
    "browser.1688",
    "browser.jd",
    "browser.pinduoduo",
)


class LocalWorkerError(RuntimeError):
    """A safe, non-secret local worker error."""


class LocalWorkerTaskError(LocalWorkerError):
    """A safe task outcome that can be reported to the control plane."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


@dataclass(frozen=True)
class LocalWorkerConfig:
    """Non-secret runtime configuration loaded from the local environment."""

    api_url: str
    session_token: str
    enrollment_token: str
    session_token_file: Path
    worker_id: str
    profile_root: Path
    capabilities: tuple[str, ...] = _DEFAULT_CAPABILITIES
    request_timeout_seconds: float = 20.0
    heartbeat_interval_seconds: float = 20.0
    poll_interval_seconds: float = 2.0
    lease_renew_interval_seconds: float = 30.0
    browser_timeout_ms: int = 30_000
    # Keep this below the server's minimum 60-second token TTL so a deployment
    # using the shortest allowed lifetime still refreshes before expiry.
    token_refresh_interval_seconds: float = 30.0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LocalWorkerConfig:
        values = os.environ if environ is None else environ
        api_url = values.get("POLARIS_WORKER_API_URL", "").strip()
        session_token = values.get("POLARIS_WORKER_SESSION_TOKEN", "").strip()
        enrollment_token = values.get("POLARIS_WORKER_ENROLLMENT_TOKEN", "").strip()
        worker_id = values.get("POLARIS_WORKER_ID", "").strip()
        profile_root = values.get("POLARIS_WORKER_PROFILE_ROOT", "").strip()
        if not api_url or not worker_id or not profile_root:
            raise LocalWorkerError("WORKER_CONFIG_REQUIRED")
        token_file_value = values.get("POLARIS_WORKER_SESSION_TOKEN_FILE", "").strip()
        token_file = (
            Path(token_file_value).expanduser()
            if token_file_value
            else Path(profile_root).expanduser() / ".worker-session-token"
        )
        # Once a refresh has been persisted, the file is authoritative over
        # the bootstrap value in the env script. This lets a reboot continue
        # with the rotated token instead of replaying an expired token.
        if token_file.is_file():
            try:
                persisted_token = token_file.read_text(encoding="utf-8").strip()
            except OSError as exc:
                if not enrollment_token:
                    raise LocalWorkerError("WORKER_TOKEN_FILE_UNREADABLE") from exc
                persisted_token = ""
            if persisted_token:
                session_token = persisted_token
        if not session_token and not enrollment_token:
            raise LocalWorkerError("WORKER_CONFIG_REQUIRED")
        raw_capabilities = values.get("POLARIS_WORKER_CAPABILITIES", "")
        capabilities = (
            tuple(
                item.strip().casefold()
                for item in raw_capabilities.split(",")
                if item.strip()
            )
            or _DEFAULT_CAPABILITIES
        )
        if any(
            len(item) > 64 or any(char.isspace() for char in item)
            for item in capabilities
        ):
            raise LocalWorkerError("WORKER_CAPABILITIES_INVALID")
        try:
            request_timeout_seconds = float(
                values.get("POLARIS_WORKER_REQUEST_TIMEOUT", "20")
            )
            heartbeat_interval_seconds = float(
                values.get("POLARIS_WORKER_HEARTBEAT_INTERVAL", "20")
            )
            poll_interval_seconds = float(
                values.get("POLARIS_WORKER_POLL_INTERVAL", "2")
            )
            lease_renew_interval_seconds = float(
                values.get("POLARIS_WORKER_LEASE_INTERVAL", "30")
            )
            browser_timeout_ms = int(
                values.get("POLARIS_WORKER_BROWSER_TIMEOUT_MS", "30000")
            )
            token_refresh_interval_seconds = float(
                values.get("POLARIS_WORKER_TOKEN_REFRESH_INTERVAL", "30")
            )
        except ValueError as exc:
            raise LocalWorkerError("WORKER_CONFIG_INVALID") from exc
        if any(
            value <= 0
            for value in (
                request_timeout_seconds,
                heartbeat_interval_seconds,
                poll_interval_seconds,
                lease_renew_interval_seconds,
                browser_timeout_ms,
                token_refresh_interval_seconds,
            )
        ):
            raise LocalWorkerError("WORKER_CONFIG_INVALID")
        return cls(
            api_url=api_url,
            session_token=session_token,
            enrollment_token=enrollment_token,
            session_token_file=token_file.resolve(),
            worker_id=worker_id,
            profile_root=Path(profile_root).expanduser(),
            capabilities=capabilities,
            request_timeout_seconds=request_timeout_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            poll_interval_seconds=poll_interval_seconds,
            lease_renew_interval_seconds=lease_renew_interval_seconds,
            browser_timeout_ms=browser_timeout_ms,
            token_refresh_interval_seconds=token_refresh_interval_seconds,
        )

    def persist_session_token(self, token: str) -> None:
        """Persist a rotated token atomically, best-effort with restrictive mode."""

        token = token.strip()
        if not token:
            raise LocalWorkerError("WORKER_TOKEN_REQUIRED")
        path = self.session_token_file
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(token + "\n", encoding="utf-8")
            with suppress(OSError):
                os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            with suppress(OSError):
                os.chmod(path, 0o600)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink()
            raise LocalWorkerError("WORKER_TOKEN_FILE_UNWRITABLE") from exc


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
            session_token = "enrollment-bootstrap"
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
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                code = error_payload.get("error", {}).get("code")
            except Exception:
                code = None
            raise LocalWorkerError(str(code or "WORKER_API_UNAVAILABLE")) from exc
        except (URLError, TimeoutError) as exc:
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

    def register_worker(
        self,
        enrollment_token: str,
        device_id: str,
        *,
        protocol_version: str,
        agent_version: str,
        capabilities: list[str],
    ) -> dict[str, Any]:
        token = enrollment_token.strip()
        if not token:
            raise LocalWorkerError("WORKER_ENROLLMENT_REQUIRED")
        device = _validate_id(device_id, "device_id")
        return self._post(
            "/api/ecommerce/workers/register",
            {
                "enrollment_token": token,
                "device_id": device,
                "protocol_version": protocol_version,
                "agent_version": agent_version,
                "capabilities": capabilities,
            },
        )

    def refresh_token(self, worker_id: str) -> dict[str, Any]:
        """Rotate the current session token and update this client in-place."""

        worker = _validate_id(worker_id, "worker_id")
        response = self._post(f"/api/ecommerce/workers/{worker}/token/refresh", {})
        data = response.get("data")
        if not isinstance(data, Mapping):
            raise LocalWorkerError("WORKER_API_INVALID_RESPONSE")
        replacement = data.get("session_token")
        if not isinstance(replacement, str) or not replacement.strip():
            raise LocalWorkerError("WORKER_API_INVALID_RESPONSE")
        self.session_token = replacement.strip()
        return response

    def update_account_session(
        self, worker_id: str, account_id: str, login_state: str
    ) -> dict[str, Any]:
        worker = _validate_id(worker_id, "worker_id")
        account = _validate_id(account_id, "account_id")
        if login_state not in {"ready", "needs_login"}:
            raise LocalWorkerError("LOGIN_STATE_INVALID")
        return self._post(
            f"/api/ecommerce/workers/{worker}/accounts/{account}/session",
            {"login_state": login_state},
        )

    def claim_login(
        self, worker_id: str, platforms: list[str] | None = None
    ) -> dict[str, Any]:
        worker = _validate_id(worker_id, "worker_id")
        payload: dict[str, Any] = {}
        if platforms is not None:
            payload["platforms"] = platforms
        return self._post(f"/api/ecommerce/workers/{worker}/login-jobs/claim", payload)

    def update_login(
        self, worker_id: str, session_id: str, state: str, message: str = ""
    ) -> dict[str, Any]:
        worker = _validate_id(worker_id, "worker_id")
        session = _validate_id(session_id, "login_session_id")
        return self._post(
            f"/api/ecommerce/workers/{worker}/login-jobs/{session}/state",
            {"state": state, "message": message},
        )

    def login_control(self, worker_id: str, session_id: str) -> dict[str, Any]:
        worker = _validate_id(worker_id, "worker_id")
        session = _validate_id(session_id, "login_session_id")
        return self._get(
            f"/api/ecommerce/workers/{worker}/login-jobs/{session}/control"
        )

    def upload_login_frame(
        self,
        worker_id: str,
        session_id: str,
        data: bytes,
        *,
        content_type: str = "image/jpeg",
        width: int = 0,
        height: int = 0,
        sequence: int = 0,
    ) -> dict[str, Any]:
        worker = _validate_id(worker_id, "worker_id")
        session = _validate_id(session_id, "login_session_id")
        if len(data) > 512 * 1024:
            raise LocalWorkerError("LOGIN_FRAME_TOO_LARGE")
        return self._post(
            f"/api/ecommerce/workers/{worker}/login-jobs/{session}/frames",
            {
                "data": base64.b64encode(data).decode("ascii"),
                "content_type": content_type,
                "width": width,
                "height": height,
                "sequence": sequence,
            },
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
        account_id = task.get("account_id") or task.get("profile_id")
        if not isinstance(account_id, str):
            raise LocalWorkerError("TASK_PROFILE_REQUIRED")
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
        token_refresh_interval_seconds: float = 30.0,
        on_token_refreshed: Callable[[str], None] | None = None,
        enrollment_token: str = "",
        device_id: str = "",
    ) -> None:
        if heartbeat_interval_seconds <= 0 or poll_interval_seconds <= 0:
            raise LocalWorkerError("WORKER_INTERVAL_INVALID")
        if lease_renew_interval_seconds <= 0:
            raise LocalWorkerError("WORKER_LEASE_INTERVAL_INVALID")
        if token_refresh_interval_seconds <= 0:
            raise LocalWorkerError("WORKER_TOKEN_REFRESH_INTERVAL_INVALID")
        self.api = api
        self.runtime = runtime
        self.protocol_version = protocol_version
        self.agent_version = agent_version
        self.capabilities = list(capabilities or [])
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_renew_interval_seconds = lease_renew_interval_seconds
        self.token_refresh_interval_seconds = token_refresh_interval_seconds
        self.on_token_refreshed = on_token_refreshed
        self.enrollment_token = enrollment_token.strip()
        self.device_id = (device_id or runtime.worker_id).strip()

    def _recover_registration(self) -> bool:
        if not self.enrollment_token:
            return False
        try:
            response = self.api.register_worker(
                self.enrollment_token,
                self.device_id,
                protocol_version=self.protocol_version,
                agent_version=self.agent_version,
                capabilities=self.capabilities,
            )
            data = response.get("data") if isinstance(response, Mapping) else None
            token = data.get("session_token") if isinstance(data, Mapping) else None
            worker = data.get("worker") if isinstance(data, Mapping) else None
            worker_id = worker.get("id") if isinstance(worker, Mapping) else None
            if (
                not isinstance(token, str)
                or not token.strip()
                or not isinstance(worker_id, str)
            ):
                return False
            self.api.session_token = token.strip()
            self.runtime.worker_id = _validate_id(worker_id, "worker_id")
            self.enrollment_token = ""
            if self.on_token_refreshed is not None:
                self.on_token_refreshed(token)
            return True
        except LocalWorkerError:
            return False

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

        claim_login = getattr(self.api, "claim_login", None)
        if callable(claim_login):
            login_response = claim_login(self.runtime.worker_id, self._platforms())
            login_job = login_response.get("data")
            if login_job is not None:
                if not isinstance(login_job, Mapping):
                    raise LocalWorkerError("WORKER_LOGIN_INVALID")
                run_remote_login(
                    self.api,
                    self.runtime.worker_id,
                    self.runtime.profiles,
                    login_job,
                )
                return True

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
        refresh_stop = threading.Event()

        def refresh_token_loop() -> None:
            # Keep the token alive independently of crawl/login work.  A
            # transient outage is harmless; the next interval retries.  If the
            # server rejects an expired token, normal heartbeat handling will
            # continue and the process can be re-enrolled explicitly.
            while not refresh_stop.wait(self.token_refresh_interval_seconds):
                refresh = getattr(self.api, "refresh_token", None)
                if not callable(refresh):
                    return
                try:
                    response = refresh(self.runtime.worker_id)
                    data = (
                        response.get("data") if isinstance(response, Mapping) else None
                    )
                    token = (
                        data.get("session_token") if isinstance(data, Mapping) else None
                    )
                    if isinstance(token, str) and self.on_token_refreshed is not None:
                        self.on_token_refreshed(token)
                except Exception:
                    continue

        refresher = threading.Thread(
            target=refresh_token_loop, name="polaris-token-refresh", daemon=True
        )
        refresher.start()
        try:
            while not stop.is_set():
                now = time.monotonic()
                if now - last_heartbeat >= self.heartbeat_interval_seconds:
                    try:
                        self._heartbeat(True)
                        last_heartbeat = now
                    except LocalWorkerError as exc:
                        if exc.args and str(exc.args[0]) in {
                            "WORKER_AUTH_INVALID",
                            "WORKER_TOKEN_EXPIRED",
                            "WORKER_TOKEN_ROTATED",
                        }:
                            self._recover_registration()
                        stop.wait(self.poll_interval_seconds)
                        continue
                try:
                    did_work = self.run_once(crawl)
                except LocalWorkerError:
                    did_work = False
                if not did_work:
                    stop.wait(self.poll_interval_seconds)
        finally:
            refresh_stop.set()
            refresher.join(timeout=max(1.0, self.token_refresh_interval_seconds))
            with suppress(LocalWorkerError):
                self._heartbeat(False)

    def _platforms(self) -> list[str] | None:
        platforms = [
            value.rsplit(".", 1)[-1]
            for value in self.capabilities
            if value.startswith("browser.")
        ]
        return list(dict.fromkeys(platforms)) or None


def run_local_worker(config: LocalWorkerConfig) -> None:
    """Start the local loop from already validated, non-secret config."""

    api = WorkerApiClient(
        config.api_url,
        config.session_token,
        timeout=config.request_timeout_seconds,
    )
    profiles = LocalProfileStore(config.profile_root)
    runtime = LocalWorkerRuntime(api, config.worker_id, profiles)
    loop = LocalWorkerLoop(
        api,
        runtime,
        capabilities=list(config.capabilities),
        heartbeat_interval_seconds=config.heartbeat_interval_seconds,
        poll_interval_seconds=config.poll_interval_seconds,
        lease_renew_interval_seconds=config.lease_renew_interval_seconds,
        token_refresh_interval_seconds=config.token_refresh_interval_seconds,
        on_token_refreshed=config.persist_session_token,
        enrollment_token=config.enrollment_token,
        device_id=os.environ.get("POLARIS_WORKER_DEVICE_ID", config.worker_id),
    )
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is not None:
            with suppress(ValueError):
                signal.signal(signal_value, request_stop)
    loop.run(
        build_local_product_crawler(timeout_ms=config.browser_timeout_ms), stop_event
    )


def run_local_login(
    profile_root: str | Path,
    account_id: str,
    platform: str,
    *,
    target_url: str | None = None,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """Open a visible local login browser for one account profile."""

    from .ecommerce_session import EcommerceSessionManager

    if timeout_seconds <= 0:
        raise LocalWorkerError("LOGIN_TIMEOUT_INVALID")
    normalized_platform = platform.strip().casefold()
    platform_map = {"tmall": "taobao", "alibaba1688": "1688"}
    normalized_platform = platform_map.get(normalized_platform, normalized_platform)
    if normalized_platform not in {"taobao", "1688", "jd", "pinduoduo"}:
        raise LocalWorkerError("LOGIN_PLATFORM_INVALID")
    profile_path = LocalProfileStore(profile_root).profile_path(account_id)
    manager = EcommerceSessionManager(
        profile_path,
        platform="alibaba1688"
        if normalized_platform == "1688"
        else normalized_platform,
        session_profile=f"domestic-{normalized_platform}",
        state_style="legacy" if normalized_platform == "taobao" else "canonical",
    )
    manager.start_login(target_url, headless=False, timeout_seconds=timeout_seconds)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = manager.status()
        if status.get("state") not in {"login_pending", "risk_controlled"}:
            return status
        # Keep remote browser input responsive while retaining a bounded
        # control-plane request rate. The browser helper itself drains the
        # local action queue on its 200ms loop.
        time.sleep(0.1)
    with suppress(Exception):
        manager.cancel_login()
    raise LocalWorkerError("LOGIN_TIMEOUT")


def run_remote_login(
    api: WorkerApiClient,
    worker_id: str,
    profiles: LocalProfileStore,
    job: Mapping[str, Any],
    *,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """Execute a queued login job locally and publish only transient frames."""

    account_id = _validate_id(str(job.get("account_id", "")), "account_id")
    session_id = _validate_id(str(job.get("id", "")), "login_session_id")
    platform = str(job.get("platform") or "taobao").casefold()
    url = str(job.get("login_url") or "").strip() or None
    profile_path = profiles.profile_path(account_id)
    from .ecommerce_session import EcommerceSessionManager

    manager = EcommerceSessionManager(
        profile_path,
        platform="alibaba1688" if platform == "1688" else platform,
        session_profile=f"domestic-{platform}",
        state_style="legacy" if platform == "taobao" else "canonical",
    )
    try:
        manager.start_login(url, headless=True, timeout_seconds=timeout_seconds)
    except Exception as exc:
        # Keep the control plane from leaving a claimed login job waiting
        # forever when the local browser/profile cannot be started. The
        # exception type is useful in the local supervisor log and contains
        # no profile, cookie, or credential material.
        print(
            f"local login browser startup failed: {type(exc).__name__}",
            file=sys.stderr,
            flush=True,
        )
        with suppress(Exception):
            api.update_login(
                worker_id,
                session_id,
                "failed",
                "本机浏览器启动失败，请检查本机浏览器和 Profile 权限。",
            )
        raise LocalWorkerError("WORKER_LOGIN_BROWSER_START_FAILED") from exc
    api.update_login(worker_id, session_id, "waiting_qr", "目标本机登录页已打开。")
    deadline = time.monotonic() + timeout_seconds
    sequence = 0
    last_mtime_ns = 0
    while time.monotonic() < deadline:
        try:
            control = api.login_control(worker_id, session_id).get("data") or {}
            actions = control.get("actions") or []
            if isinstance(actions, list):
                for action in actions:
                    if isinstance(action, Mapping):
                        manager.enqueue_input(dict(action))
            if control.get("cancel_requested") or control.get("expired"):
                with suppress(Exception):
                    manager.cancel_login()
                api.update_login(
                    worker_id,
                    session_id,
                    "cancelled" if control.get("cancel_requested") else "expired",
                )
                return {
                    "state": "cancelled"
                    if control.get("cancel_requested")
                    else "expired"
                }
        except LocalWorkerError:
            pass
        current = manager.status()
        state = str(current.get("state") or "waiting_user")
        mapped = {
            "login_pending": "waiting_user",
            "risk_controlled": "risk_controlled",
            "ready": "ready",
            "error": "failed",
            "needs_relogin": "needs_login",
        }.get(state, "waiting_user")
        frame_path = (
            manager.stream_path
            if manager.stream_path.is_file()
            else manager.preview_path
        )
        if frame_path.is_file():
            try:
                stat = frame_path.stat()
                if stat.st_mtime_ns != last_mtime_ns:
                    frame = frame_path.read_bytes()
                    if len(frame) <= 512 * 1024:
                        sequence += 1
                        api.upload_login_frame(
                            worker_id,
                            session_id,
                            frame,
                            content_type="image/jpeg"
                            if frame_path == manager.stream_path
                            else "image/png",
                            sequence=sequence,
                        )
                        last_mtime_ns = stat.st_mtime_ns
            except OSError:
                pass
            except LocalWorkerError as exc:
                print(
                    f"local login frame upload failed: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
        if mapped in {"ready", "needs_login", "risk_controlled", "failed"}:
            api.update_login(
                worker_id, session_id, mapped, str(current.get("message") or "")
            )
            return current
        api.update_login(worker_id, session_id, mapped)
        time.sleep(0.5)
    with suppress(Exception):
        manager.cancel_login()
    api.update_login(worker_id, session_id, "expired", "本机登录任务已超时。")
    raise LocalWorkerError("LOGIN_TIMEOUT")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; secrets are accepted only through environment vars."""

    parser = argparse.ArgumentParser(
        description="Run the outbound-only Polaris local ecommerce worker."
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate environment configuration without connecting to the API",
    )
    parser.add_argument(
        "--login-account-id",
        help="open a visible local login browser for one account ID",
    )
    parser.add_argument(
        "--login-platform",
        choices=("taobao", "tmall", "1688", "jd", "pinduoduo"),
        default="taobao",
    )
    parser.add_argument("--login-url", help="optional official platform URL to open")
    parser.add_argument("--login-timeout", type=int, default=600)
    args = parser.parse_args(argv)
    try:
        if args.login_account_id:
            profile_root = os.environ.get("POLARIS_WORKER_PROFILE_ROOT", "").strip()
            if not profile_root:
                raise LocalWorkerError("WORKER_PROFILE_ROOT_REQUIRED")
            login_status = run_local_login(
                profile_root,
                args.login_account_id,
                args.login_platform,
                target_url=args.login_url,
                timeout_seconds=args.login_timeout,
            )
            # When the worker credentials are present, publish only the
            # coarse login state.  Cookies, profile paths and browser data
            # never leave the local machine.  Keep login usable in standalone
            # mode when the worker has not yet been registered.
            login_state = (
                login_status.get("state") if isinstance(login_status, dict) else None
            )
            if login_state in {"ready", "needs_login"}:
                try:
                    config = LocalWorkerConfig.from_env()
                    WorkerApiClient(
                        config.api_url,
                        config.session_token,
                        timeout=config.request_timeout_seconds,
                    ).update_account_session(
                        config.worker_id,
                        args.login_account_id,
                        login_state,
                    )
                except LocalWorkerError:
                    # The browser login itself succeeded; status sync can be
                    # retried by the worker after registration.
                    pass
            return 0
        config = LocalWorkerConfig.from_env()
        if args.check_config:
            return 0
        run_local_worker(config)
    except LocalWorkerError as exc:
        print(f"local worker stopped: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by deployment tooling
    raise SystemExit(main())
