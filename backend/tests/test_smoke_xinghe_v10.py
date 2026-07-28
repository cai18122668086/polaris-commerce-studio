from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_harness() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "smoke_xinghe_v10.py"
    spec = importlib.util.spec_from_file_location("smoke_xinghe_v10", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load the v10 smoke harness")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke_v10 = _load_harness()
HarnessConfig = smoke_v10.HarnessConfig
HarnessError = smoke_v10.HarnessError
TimeoutPolicy = smoke_v10.TimeoutPolicy
main = smoke_v10.main
run_harness = smoke_v10.run_harness
source_audit = smoke_v10.source_audit
consume_live_approval = smoke_v10.consume_live_approval


def _config(
    *,
    mode: str = "calibrate-blocked",
    product_name: str = "offline calibration product",
    selling_points: tuple[str, ...] = ("bounded",),
) -> Any:
    return HarnessConfig(
        mode=mode,
        base_url="http://127.0.0.1:9",
        workspace_id="ws_test",
        asset_ids=(
            ("asset_calibration_blocked",)
            if mode == "calibrate-blocked"
            else ("asset_live",)
        ),
        product_name=product_name,
        selling_points=selling_points,
        platform_code="amazon",
        language="en",
        page_count=1,
        timeouts=TimeoutPolicy(
            transport_seconds=2,
            poll_seconds=10,
            total_deadline_seconds=10,
            cleanup_margin_seconds=3,
            poll_interval_seconds=0.5,
        ),
    )


def test_calibrate_blocked_covers_formal_path_for_ten_seconds() -> None:
    result = run_harness(_config())

    assert result["status"] == "pass"
    assert result["outcome"] == "deadline_calibrated"
    assert result["timeout_layer"] == "harness_total_deadline"
    assert result["calibration"]["logical_elapsed_seconds"] >= 10
    assert result["calibration"]["formal_path_covered"] == [
        "job_create",
        "initial_dispatch",
        "plan_poll",
        "plan_confirm",
        "confirmed_dispatch",
        "result_poll",
        "harness_total_deadline_timeout",
    ]
    assert result["safety"] == {
        "network_attempts": 0,
        "provider_calls": 0,
        "secret_reads": 0,
        "real_jobs": 0,
    }


def test_live_refuses_before_secret_network_or_real_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("must-not-be-read", encoding="utf-8")
    config = _config(mode="live")
    config = replace(config, auth_token_file=token_file)
    live_factory_calls: list[tuple[Any, ...]] = []

    def forbidden_live_factory(*args: Any) -> Any:
        live_factory_calls.append(args)
        raise AssertionError("live transport must not be constructed")

    def forbidden_secret_read(*args: Any) -> Any:
        raise AssertionError("secret reader must not be called")

    monkeypatch.setattr(smoke_v10, "read_authorization", forbidden_secret_read)
    with pytest.raises(HarnessError, match="LIVE_APPROVAL_REQUIRED"):
        run_harness(config, live_factory=forbidden_live_factory)

    assert live_factory_calls == []


def test_live_approval_is_explicit_and_consumed_once(tmp_path: Path) -> None:
    approval_id = "9eeb2d5b-d6be-4ae7-a25b-875381f6b725"
    approval_file = tmp_path / "approval.json"
    candidate = source_audit()["candidate"]
    approval_file.write_text(
        json.dumps(
            {
                "schema": "polaris-xinghe-v10-live-approval-v1",
                "mode": "live",
                "approval_id": approval_id,
                "candidate_sha256": candidate,
                "acknowledge_real_job": True,
                "expires_at": (
                    datetime.now(UTC) + timedelta(minutes=5)
                ).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    consume_live_approval(approval_file, approval_id, candidate)

    assert not approval_file.exists()
    assert approval_file.with_name("approval.json.consumed").exists()
    with pytest.raises(HarnessError, match="LIVE_APPROVAL_ALREADY_CONSUMED"):
        consume_live_approval(approval_file, approval_id, candidate)


@pytest.mark.parametrize(
    ("timeouts", "error_code"),
    [
        (
            TimeoutPolicy(11, 10, 10, 3, 0.5),
            "TRANSPORT_EXCEEDS_TOTAL_DEADLINE",
        ),
        (
            TimeoutPolicy(2, 11, 10, 3, 0.5),
            "POLL_EXCEEDS_TOTAL_DEADLINE",
        ),
        (
            TimeoutPolicy(2, 10, 10, 3, 11),
            "POLL_INTERVAL_EXCEEDS_POLL_TIMEOUT",
        ),
    ],
)
def test_timeout_relationships_fail_closed(
    timeouts: Any,
    error_code: str,
) -> None:
    config = _config()
    config = replace(config, timeouts=timeouts)

    with pytest.raises(HarnessError, match=error_code):
        run_harness(config)


def test_machine_result_has_outer_timeout_floor_and_no_sensitive_content() -> None:
    product_name = "PRIVATE-PRODUCT-NAME"
    selling_point = "PRIVATE-PROMPT-LIKE-SELLING-POINT"
    result = run_harness(
        _config(
            product_name=product_name,
            selling_points=(selling_point,),
        )
    )
    serialized = json.dumps(result, sort_keys=True)

    assert result["timeouts"]["outer_tool_minimum_seconds"] == 13
    assert result["timeouts"]["outer_tool_minimum_seconds"] == (
        result["timeouts"]["harness_total_deadline_seconds"]
        + result["timeouts"]["cleanup_margin_seconds"]
    )
    assert product_name not in serialized
    assert selling_point not in serialized
    assert "asset_calibration_blocked" not in serialized
    assert "http://127.0.0.1:9" not in serialized


def test_source_audit_hashes_and_offline_compiles_candidate_boundary() -> None:
    hashes = source_audit()

    assert set(hashes) == {"candidate", "runner", "adapter", "harness"}
    assert all(
        len(value) == 64
        and value == value.lower()
        and set(value) <= set("0123456789abcdef")
        for value in hashes.values()
    )


def test_cli_emits_machine_readable_calibration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "calibrate-blocked",
            "--workspace-id",
            "ws_test",
            "--asset-id",
            "asset_calibration_blocked",
            "--transport-timeout-seconds",
            "2",
            "--poll-timeout-seconds",
            "10",
            "--harness-total-deadline-seconds",
            "10",
            "--cleanup-margin-seconds",
            "3",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["schema"] == "polaris-xinghe-v10-smoke-result-v1"
    assert payload["status"] == "pass"
    assert payload["safety"]["network_attempts"] == 0
