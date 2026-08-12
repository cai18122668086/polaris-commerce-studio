from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.aurora_main_image_runtime import AuroraHarnessError, AuroraHarnessRunner
from app.routes_v1 import _new_job_from_payload, runtime_status_response
from app.schemas_v1 import DomesticMainImageJobCreate


def test_domestic_main_image_contract_is_exactly_six_page_input() -> None:
    payload = DomesticMainImageJobCreate.model_validate(
        {
            "type": "domestic_main_image",
            "input": {"product_asset_ids": ["asset_one", "asset_two"]},
            "configuration": {
                "product_name": "轻量随行杯",
                "category": "保温杯",
                "selling_points": ["杯盖防误开"],
            },
        }
    )
    assert payload.configuration.language == "zh-CN"
    assert payload.input.product_asset_ids == ["asset_one", "asset_two"]

    job, roles = _new_job_from_payload("workspace_one", payload)
    assert job.expected_item_count == 6
    assert roles == [
        ("asset_one", "product_identity_authority", 0),
        ("asset_two", "product_identity_authority", 1),
    ]


def test_harness_runner_rejects_unknown_commands(tmp_path: Path) -> None:
    with pytest.raises(AuroraHarnessError) as captured:
        AuroraHarnessRunner().run("python", tmp_path, {})
    assert captured.value.code == "HARNESS_COMMAND_NOT_ALLOWED"


def test_real_runtime_stays_fail_closed_until_provider_adapter_is_registered() -> None:
    runtime = runtime_status_response(
        environment="test",
        authentication_mode="development",
        task_runner="tengli",
        domestic_main_image_provider_enabled=True,
    )
    capability = runtime.capabilities.features["domestic_main_image"]
    assert capability.availability == "unavailable"
    assert capability.reason_code == "REAL_PROVIDER_NOT_REGISTERED"


def test_harness_runner_rejects_paths_outside_job_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.json"
    with pytest.raises(AuroraHarnessError) as captured:
        AuroraHarnessRunner().run(
            "start",
            tmp_path,
            {"input": outside, "session": tmp_path / "session.json"},
        )
    assert captured.value.code == "HARNESS_PATH_OUTSIDE_WORKSPACE"


def test_harness_start_runs_through_bundled_entrypoint(tmp_path: Path) -> None:
    raw = {
        "request_id": "job_test",
        "profile01_semantics_read": False,
        "product": {
            "name": "轻量随行杯",
            "category": "保温杯",
            "original_references": ["asset_one"],
            "verified_selling_points": ["杯盖防误开"],
        },
    }
    input_path = tmp_path / "input.json"
    session_path = tmp_path / "session.json"
    input_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    result = AuroraHarnessRunner().run(
        "start",
        tmp_path,
        {"input": input_path, "session": session_path},
    )
    assert result["status"] == "AWAITING_IDENTITY"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    assert session["request_id"] == "job_test"
