from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.errors import ApiError
from app.routes_v1 import _validate_inspiration_case_job
from app.schemas_v1 import CreativeImageJobCreate, ReferenceRemixJobCreate


def _session_for(case):
    session = Mock()
    session.scalar.return_value = case
    return session


def _case(workflow_type: str, *, reference_source: str = "none", status: str = "published", configuration_status: str = "ready"):
    return SimpleNamespace(
        id="ins_test",
        title="test",
        workflow_type=workflow_type,
        reference_source=reference_source,
        status=status,
        configuration_status=configuration_status,
        prompt="case prompt",
    )


def _creative(**kwargs):
    return CreativeImageJobCreate(
        inspiration_case_id="ins_test",
        type="creative_image",
        input={"product_asset_ids": ["product"], **kwargs.pop("input", {})},
        configuration={
            "inspiration_planning": True,
            "instruction": "case prompt",
            **kwargs.pop("configuration", {}),
        },
    )


def test_product_prompt_accepts_product_only_without_reference() -> None:
    case = _case("product_prompt")
    result = _validate_inspiration_case_job(_session_for(case), _creative())
    assert result is case


def test_product_prompt_rejects_reference_assets() -> None:
    case = _case("product_prompt")
    with pytest.raises(ApiError) as raised:
        _validate_inspiration_case_job(
            _session_for(case),
            _creative(input={"competitor_asset_ids": ["reference"]}),
        )
    assert raised.value.code == "INSPIRATION_REFERENCE_NOT_ALLOWED"


def test_reference_remix_requires_reference_asset() -> None:
    case = _case("reference_remix", reference_source="admin_reference")
    # Pydantic rejects this before the routing helper, which is the desired
    # fail-closed contract for a missing reference.
    with pytest.raises(ValueError):
        ReferenceRemixJobCreate(
            inspiration_case_id="ins_test",
            type="reference_remix",
            input={"product_asset_ids": ["product"], "reference_asset_ids": []},
            configuration={},
        )


def test_product_prompt_cannot_be_called_as_reference_remix() -> None:
    case = _case("product_prompt")
    payload = ReferenceRemixJobCreate(
        inspiration_case_id="ins_test",
        type="reference_remix",
        input={"product_asset_ids": ["product"], "reference_asset_ids": ["reference"]},
        configuration={},
    )
    with pytest.raises(ApiError) as raised:
        _validate_inspiration_case_job(_session_for(case), payload)
    assert raised.value.code == "INSPIRATION_WORKFLOW_MISMATCH"


def test_unclassified_case_is_rejected_before_job_creation() -> None:
    case = _case("legacy_unclassified")
    with pytest.raises(ApiError) as raised:
        _validate_inspiration_case_job(_session_for(case), _creative())
    assert raised.value.code == "INSPIRATION_CASE_WORKFLOW_UNSUPPORTED"

