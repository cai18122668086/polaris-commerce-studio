from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.ecommerce_local_worker as local_worker
from app.ecommerce_local_worker import (
    LocalProfileStore,
    LocalWorkerError,
    LocalWorkerRuntime,
    WorkerApiClient,
)


def test_profile_store_rejects_traversal_and_serializes_account_access(tmp_path: Path):
    store = LocalProfileStore(tmp_path / "profiles")
    profile = store.profile_path("account_1")
    assert profile.is_relative_to(store.root)

    with pytest.raises(LocalWorkerError, match="INVALID_ACCOUNT_ID"):
        store.profile_path("../outside")

    with store.lock("account_1") as held:
        assert held == profile
        with (
            pytest.raises(LocalWorkerError, match="PROFILE_BUSY"),
            store.lock("account_1"),
        ):
            pass
    with store.lock("account_1"):
        pass


def test_profile_store_reclaims_expired_lock_from_dead_process(tmp_path: Path):
    store = LocalProfileStore(tmp_path / "profiles")
    lock_path = store._locks / "account_1.lock"
    lock_path.write_text(str(os.getpid() + 999_999), encoding="ascii")
    old = time.time() - 10
    os.utime(lock_path, (old, old))

    with store.lock("account_1", stale_after_seconds=1):
        assert lock_path.exists()


def test_worker_api_requires_tls_and_rejects_sensitive_or_invalid_payloads(monkeypatch):
    with pytest.raises(LocalWorkerError, match="WORKER_API_REQUIRES_HTTPS"):
        WorkerApiClient("http://api.example.test", "worker-session")

    client = WorkerApiClient("http://127.0.0.1:8000", "worker-session")
    with pytest.raises(LocalWorkerError, match="SENSITIVE_FIELD_BLOCKED"):
        client._post("/api/test", {"cookies": "must-not-leave-machine"})

    class _InvalidResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"[]"

    monkeypatch.setattr(
        local_worker, "urlopen", lambda *_args, **_kwargs: _InvalidResponse()
    )
    with pytest.raises(LocalWorkerError, match="WORKER_API_INVALID_RESPONSE"):
        client._post("/api/test", {"items": ("safe",)})


class _FakeApi:
    def __init__(self):
        self.uploads: list[tuple[str, str, dict]] = []
        self.completions: list[tuple[str, str, dict]] = []
        self.heartbeats: list[dict] = []
        self.claims = 0
        self.renewals = 0

    def upload_result(self, worker_id: str, task_id: str, payload: dict) -> dict:
        self.uploads.append((worker_id, task_id, payload))
        return {"accepted": True}

    def complete(self, worker_id: str, task_id: str, payload: dict) -> dict:
        self.completions.append((worker_id, task_id, payload))
        return {"accepted": True}

    def heartbeat(self, _worker_id: str, payload: dict) -> dict:
        self.heartbeats.append(payload)
        return {"accepted": True}

    def claim(self, _worker_id: str, _platforms: list[str] | None = None) -> dict:
        self.claims += 1
        return {"data": _task()} if self.claims == 1 else {"data": None}

    def renew_lease(self, _worker_id: str, _task_id: str, _fencing_token: int) -> dict:
        self.renewals += 1
        return {"accepted": True}


def _task() -> dict:
    return {
        "id": "task_1",
        "account_id": "account_1",
        "lease": {"fencing_token": 7},
        "request_payload": {"platform": "taobao"},
    }


def test_runtime_keeps_profile_local_and_uploads_structured_result(tmp_path: Path):
    api = _FakeApi()
    runtime = LocalWorkerRuntime(api, "worker_1", LocalProfileStore(tmp_path))
    observed: dict[str, Path] = {}

    def crawl(profile_path: Path, task: dict) -> dict:
        observed["profile"] = profile_path
        assert profile_path.is_relative_to(tmp_path.resolve())
        assert task["id"] == "task_1"
        return {"platform": "taobao", "title": "本地结果"}

    assert runtime.execute_claimed(_task(), crawl) == {"accepted": True}
    assert observed["profile"].is_relative_to(tmp_path.resolve())
    assert api.uploads == [
        (
            "worker_1",
            "task_1",
            {
                "fencing_token": 7,
                "result": {"platform": "taobao", "title": "本地结果"},
            },
        )
    ]


def test_runtime_reports_browser_crash_without_exposing_exception(tmp_path: Path):
    api = _FakeApi()
    runtime = LocalWorkerRuntime(api, "worker_1", LocalProfileStore(tmp_path))

    def crash(_profile_path: Path, _task: dict) -> dict:
        raise RuntimeError("cookie=secret should not be sent")

    with pytest.raises(LocalWorkerError, match="WORKER_BROWSER_CRASH"):
        runtime.execute_claimed(_task(), crash)
    assert api.completions[0][2] == {
        "fencing_token": 7,
        "outcome": "failed",
        "error_code": "WORKER_BROWSER_CRASH",
        "error_message_safe": "本机浏览器执行失败。",
    }


def test_worker_loop_claims_renews_and_stops_cleanly(tmp_path: Path):
    api = _FakeApi()
    runtime = LocalWorkerRuntime(api, "worker_1", LocalProfileStore(tmp_path))
    loop = local_worker.LocalWorkerLoop(
        api,
        runtime,
        capabilities=["browser.taobao"],
        lease_renew_interval_seconds=0.01,
    )

    def crawl(_profile_path: Path, _task: dict) -> dict:
        time.sleep(0.03)
        return {"platform": "taobao", "title": "结果"}

    assert loop.run_once(crawl) is True
    assert api.claims == 1
    assert api.renewals >= 1

    stop = threading.Event()
    stop.set()
    loop.run(crawl, stop)
    assert api.heartbeats[-1]["ready"] is False


def test_local_product_crawler_uses_only_claimed_profile(monkeypatch, tmp_path: Path):
    fake_product = SimpleNamespace(
        platform="taobao",
        product_id="123",
        title="本机商品",
        price="19.9",
        shop_name="店铺",
        sales=None,
        images=[SimpleNamespace(url="https://img.example/1.jpg", role="main")],
        sku_prop_groups=[],
        skus=[],
        props_text="",
        services=[],
        image_diagnostics={},
        warnings=[],
        access_state=None,
    )
    observed: dict[str, object] = {}

    def fake_browser(url: str, timeout_ms: int, profile_dir: str):
        observed.update(url=url, timeout_ms=timeout_ms, profile_dir=profile_dir)
        return fake_product

    monkeypatch.setattr("app.ecommerce_fetcher.crawl_one_browser", fake_browser)
    callback = local_worker.build_local_product_crawler(timeout_ms=1234)
    result = callback(
        tmp_path / "accounts" / "account_1",
        {
            "platform": "taobao",
            "canonical_url": "https://item.taobao.com/item.htm?id=123",
            "request_payload": {"includeDescImages": False},
        },
    )
    assert result["platform"] == "taobao"
    assert result["title"] == "本机商品"
    assert result["descImageUrls"] == []
    assert observed == {
        "url": "https://item.taobao.com/item.htm?id=123",
        "timeout_ms": 1234,
        "profile_dir": str(tmp_path / "accounts" / "account_1"),
    }
