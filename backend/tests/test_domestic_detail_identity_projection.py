"""One original observation list feeds the native identity."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator

from app.domestic_detail.facts import DetailIntakeError, validate_intake
from app.domestic_detail.intake import (
    IDENTITY_PROJECTION,
    intake_response_schema,
    project_identity_observations,
)
from app.domestic_detail.plans import canonical_hash
from tests.test_domestic_detail_execution import _gateway
from tests.test_domestic_detail_intake import CONFIRMATION, SETTINGS, SOURCES, intake
from tests.test_domestic_detail_plans import planned_job


def wire():
    value = intake()
    value["brand_confirmation_required"] = False
    value["identity_features_source"] = IDENTITY_PROJECTION
    value["identity"].pop("invariant_features")
    return value


def test_wire_projection_preserves_original_bytes_and_actual_observations():
    original = wire()
    before = deepcopy(original)
    refs = original["conflict_scan"]["scanned_source_refs"]
    schema = intake_response_schema(
        ["product-1"], [r for r in refs if r != "product-1"], wire_settings=SETTINGS
    )
    assert Draft202012Validator(schema).is_valid(original)
    native, receipt = project_identity_observations(original)
    result = validate_intake(
        native, settings=SETTINGS, sources=SOURCES, brandless_confirmation=CONFIRMATION
    )
    assert original == before
    assert result["identity"]["invariant_features"] == [
        row["text"].strip() for row in before["identity_observations"]
    ]
    assert receipt["source_payload_sha256"] == canonical_hash(before)
    assert receipt["observations_sha256"] == canonical_hash(
        before["identity_observations"]
    )


def test_legacy_disagreement_is_still_rejected_instead_of_silently_repaired():
    original = intake()
    original["identity"]["invariant_features"][0] = (
        "Different legacy product silhouette"
    )
    native, receipt = project_identity_observations(original)
    assert native == original and receipt is None
    with pytest.raises(DetailIntakeError) as error:
        validate_intake(
            native,
            settings=SETTINGS,
            sources=SOURCES,
            brandless_confirmation=CONFIRMATION,
        )
    assert error.value.code == "INTAKE_IDENTITY_OBSERVATION_MISMATCH"


@pytest.mark.parametrize(
    "tamper",
    ["source", "generic", "kind", "missing", "duplicated_identity", "unknown_protocol"],
)
def test_projection_never_supplies_missing_product_geometry_or_sources(tamper):
    original = wire()
    if tamper == "source":
        original["identity_observations"][0]["source_asset_id"] = "another-product"
    elif tamper == "generic":
        original["identity_observations"][0]["text"] = (
            "所有结构严格以用户商品参考图为准"
        )
    elif tamper == "kind":
        original["identity_observations"][0]["kind"] = "parts"
    elif tamper == "missing":
        original["identity_observations"].pop()
    elif tamper == "duplicated_identity":
        original["identity"]["invariant_features"] = ["guessed product"]
    else:
        original["identity_features_source"] = "UNKNOWN"
    with pytest.raises(DetailIntakeError):
        native, _ = project_identity_observations(original)
        validate_intake(
            native,
            settings=SETTINGS,
            sources=SOURCES,
            brandless_confirmation=CONFIRMATION,
        )


def test_public_planning_binds_the_original_wire_reply_to_native_identity(
    client, monkeypatch
):
    gateway = _gateway(client)
    original = gateway.plan
    replies = []

    async def reply(request):
        result = await original(request)
        if request.planning_profile == "aurora_domestic_intake":
            payload = deepcopy(result.payload)
            payload["identity_features_source"] = IDENTITY_PROJECTION
            payload["identity"].pop("invariant_features")
            replies.append(deepcopy(payload))
            return replace(
                result,
                payload=payload,
                audit_raw_content=json.dumps(payload, ensure_ascii=False),
            )
        return result

    monkeypatch.setattr(gateway, "plan", reply)
    planned = planned_job(client)
    assert planned["status"] == "awaiting_confirmation"
    value = planned["plan"]["payload"]["product_intake"]
    assert len(replies) == 1 and "invariant_features" not in replies[0]["identity"]
    assert value["identity_projection_receipt"][
        "source_payload_sha256"
    ] == canonical_hash(replies[0])
    assert value["identity"]["invariant_features"] == [
        row["text"].strip() for row in replies[0]["identity_observations"]
    ]
    assert gateway.image_calls == []
