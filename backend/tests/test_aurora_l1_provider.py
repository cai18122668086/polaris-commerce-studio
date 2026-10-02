"""L1 rubric channel: behavior preservation and shadow-channel activation.

Two contracts are asserted here:

1. With ``aurora_l1_rubric_enabled`` off, the shipped provider produces exactly
   the prompt and audit contract it produced before the hooks existed.  Any
   drift in the default path is a regression, not a feature.
2. With the switch on, the shadow provider is selected, the reviewer receives
   the Skill rubric, and the audit contract carries the user fact pool — while
   every other contract field stays identical to the shipped one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.aurora_main_image_l1_provider import (
    AUDIT_CHANNEL,
    AuroraMainImageL1Provider,
    _REFERENCE_CLAUSE_L1,
    _REFERENCE_CLAUSE_SHIPPED,
    _flatten_whitespace,
)
from app.aurora_main_image_provider import (
    _AUDIT_SYSTEM_PROMPT,
    AuroraMainImageProvider,
)
from app.domain import JobType
from app.execution import build_fake_coordinator
from app.provider import ProviderArtifact, ProviderRequest
from app.provider_registry import (
    RegisteredOperationRoutingProvider,
    UnavailableProvider,
)
from app.xinghe_agent import FakeXingheGateway

_JOB_ID = "job_l1_rubric_fixture"

_LAYOUT_CONTRACT = {
    "composition_archetype": "PRODUCT_HERO_ARCHETYPE",
    "product_zone": "LOWER_TWO_THIRDS",
    "copy_zone": "UPPER_LEFT",
    "dominant_view": "FRONT_THREE_QUARTER",
    "evidence_topology": "MATERIAL_CUTAWAY",
}

_FACT_POOL = {
    "verified_selling_points": ["透气", "7A抑菌底裆", "亲肤"],
    "verified_attributes": [],
    "verified_scenes": [],
    "verified_offers": [],
    "verified_service_or_trust_facts": [],
    "user_provided_display_facts": [],
}


def _generation_request(
    page_index: int = 0, reference_path: Path | None = None
) -> dict[str, Any]:
    return {
        "page_index": page_index,
        "page_role": "SEARCH_COVER",
        "revision": 0,
        "campaign_constitution": {"campaign_style": "CLEAN_COMMERCE"},
        "imagegen_reference_paths": (
            [str(reference_path)] if reference_path is not None else []
        ),
        "page_contract": {
            "layout_contract": dict(_LAYOUT_CONTRACT),
            "display_copy_contract": {
                "source_claim": "7A抑菌底裆",
                "support_source_segments": ["全棉100%底裆", "透气"],
                "headline_seed_source_segment": "7A抑菌底裆",
                "headline_hard_max_chars": 12,
                "headline_max_lines": 2,
            },
        },
    }


def _write_session(work_root: Path, job_id: str) -> None:
    workspace = work_root / job_id
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "session.json").write_text(
        json.dumps({"raw_input": {"product": dict(_FACT_POOL)}}),
        encoding="utf-8",
    )


def _build_provider(
    provider_cls: type[AuroraMainImageProvider],
    tmp_path: Path,
    *,
    with_session: bool,
) -> tuple[AuroraMainImageProvider, FakeXingheGateway]:
    work_root = tmp_path / "work"
    if with_session:
        _write_session(work_root, _JOB_ID)
    gateway = FakeXingheGateway()
    provider = provider_cls(
        session_factory=None,  # type: ignore[arg-type]
        gateway=gateway,
        storage=None,  # type: ignore[arg-type]
        work_root=work_root,
        execution_mode="parallel_v20",
    )
    return provider, gateway


def _audit_once(
    provider: AuroraMainImageProvider,
    gateway: FakeXingheGateway,
    tmp_path: Path,
    *,
    page_index: int = 0,
) -> dict[str, Any]:
    generated = tmp_path / f"candidate-{page_index}.png"
    payload = b"candidate-pixels"
    generated.write_bytes(payload)
    reference = tmp_path / "product-reference.png"
    reference.write_bytes(b"reference-pixels")
    artifact = ProviderArtifact(
        payload=payload,
        filename=generated.name,
        content_type="image/png",
        width=1024,
        height=1024,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    request = ProviderRequest(
        workspace_id="workspace_one",
        job_id=_JOB_ID,
        job_item_id="item_0",
        attempt_id="attempt_0",
        operation=JobType.DOMESTIC_MAIN_IMAGE.value,
        idempotency_key=f"{_JOB_ID}:audit:{page_index}",
        configuration={},
    )
    asyncio.run(
        provider._audit_v20_candidate(
            request,
            _generation_request(page_index, reference),
            generated,
            artifact,
        )
    )
    assert gateway.planner_calls, "the audit must issue exactly one planner call"
    return {
        "system_prompt": gateway.planner_calls[0].system_prompt,
        "contract": json.loads(gateway.planner_calls[0].product_information[0]),
    }


def test_shipped_provider_audit_hooks_are_behavior_preserving(tmp_path: Path) -> None:
    provider, _ = _build_provider(
        AuroraMainImageProvider, tmp_path, with_session=False
    )

    assert provider._audit_system_prompt() == _AUDIT_SYSTEM_PROMPT
    request = ProviderRequest(
        workspace_id="workspace_one",
        job_id=_JOB_ID,
        job_item_id="item_0",
        attempt_id="attempt_0",
        operation=JobType.DOMESTIC_MAIN_IMAGE.value,
        idempotency_key="key",
        configuration={},
    )
    assert provider._audit_contract_extras(request, _generation_request()) == {}


def test_shipped_audit_call_has_no_l1_fields(tmp_path: Path) -> None:
    provider, gateway = _build_provider(
        AuroraMainImageProvider, tmp_path, with_session=False
    )

    call = _audit_once(provider, gateway, tmp_path)

    assert call["system_prompt"] == _AUDIT_SYSTEM_PROMPT
    assert "authorized_claims" not in call["contract"]
    assert "audit_channel" not in call["contract"]


def test_l1_audit_call_injects_rubric_and_fact_pool(tmp_path: Path) -> None:
    provider, gateway = _build_provider(
        AuroraMainImageL1Provider, tmp_path, with_session=True
    )

    call = _audit_once(provider, gateway, tmp_path)
    contract = call["contract"]
    prompt = call["system_prompt"]

    # Hook 1: the Skill rubric is present and the contradictory clause is fixed.
    assert "Judge pixels, not contracts." in prompt
    assert _REFERENCE_CLAUSE_L1 in prompt
    assert _REFERENCE_CLAUSE_SHIPPED not in prompt
    assert prompt.startswith(
        _flatten_whitespace(_AUDIT_SYSTEM_PROMPT).replace(
            _REFERENCE_CLAUSE_SHIPPED, _REFERENCE_CLAUSE_L1
        )
    )
    # The response-shape contract the runtime validates must survive intact.
    assert "decision_summary" in prompt
    assert "layout_observation_contract" in prompt

    # Hook 2: the reviewer learns which claims the user actually supplied.
    assert contract["audit_channel"] == AUDIT_CHANNEL
    claims = contract["authorized_claims"]
    assert claims["page_source_claim"] == "7A抑菌底裆"
    assert claims["page_support_segments"] == ["全棉100%底裆", "透气"]
    assert claims["campaign_fact_pool"]["verified_selling_points"] == [
        "透气",
        "7A抑菌底裆",
        "亲肤",
    ]
    assert claims["campaign_fact_pool"]["verified_offers"] == []
    assert "no_unsupported_claim" in claims["authority_rule"]


def test_l1_contract_is_shipped_contract_plus_extras(tmp_path: Path) -> None:
    """Everything except the two injected keys must be byte-identical."""

    shipped, shipped_gateway = _build_provider(
        AuroraMainImageProvider, tmp_path, with_session=False
    )
    l1, l1_gateway = _build_provider(
        AuroraMainImageL1Provider, tmp_path, with_session=True
    )

    base = _audit_once(shipped, shipped_gateway, tmp_path)["contract"]
    extended = _audit_once(l1, l1_gateway, tmp_path)["contract"]

    assert set(extended) - set(base) == {"audit_channel", "authorized_claims"}
    for key, value in base.items():
        assert extended[key] == value, f"L1 changed the shipped contract field {key}"


def test_l1_fact_pool_degrades_to_empty_when_session_missing(tmp_path: Path) -> None:
    provider, gateway = _build_provider(
        AuroraMainImageL1Provider, tmp_path, with_session=False
    )

    contract = _audit_once(provider, gateway, tmp_path)["contract"]

    assert contract["authorized_claims"]["campaign_fact_pool"][
        "verified_selling_points"
    ] == []
    # The page's own compiled claim still authorizes the page copy.
    assert contract["authorized_claims"]["page_source_claim"] == "7A抑菌底裆"


def test_l1_missing_rubric_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, _ = _build_provider(
        AuroraMainImageL1Provider, tmp_path, with_session=True
    )
    monkeypatch.setattr(
        "app.aurora_main_image_l1_provider.default_aurora_v20_skill_root",
        lambda: tmp_path / "absent-skill-root",
    )

    with pytest.raises(RuntimeError, match="Aurora L1 rubric is unreadable"):
        provider._audit_system_prompt()


def test_l1_switch_selects_shadow_provider(client: TestClient) -> None:
    def coordinator(**flags: bool):
        return build_fake_coordinator(
            client.app.state.session_factory,
            0,
            storage=client.app.state.storage,
            xinghe_gateway=FakeXingheGateway(),
            xinghe_concurrency=2,
            **flags,
        )

    def domestic_route(coordinator_result) -> object:
        router = cast(
            RegisteredOperationRoutingProvider, coordinator_result.provider
        )
        return router.routes[JobType.DOMESTIC_MAIN_IMAGE.value]

    shipped = domestic_route(
        coordinator(domestic_main_image_provider_enabled=True)
    )
    shadow = domestic_route(
        coordinator(
            domestic_main_image_provider_enabled=True,
            aurora_l1_rubric_enabled=True,
        )
    )

    assert type(shipped) is AuroraMainImageProvider
    assert isinstance(shadow, AuroraMainImageL1Provider)
    assert type(shadow) is AuroraMainImageL1Provider


def test_l1_switch_does_not_open_the_domestic_route(client: TestClient) -> None:
    """Enabling the L1 channel must not bypass the provider enable switch."""

    coordinator = build_fake_coordinator(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=FakeXingheGateway(),
        aurora_l1_rubric_enabled=True,
    )
    router = cast(RegisteredOperationRoutingProvider, coordinator.provider)

    assert isinstance(
        router.routes[JobType.DOMESTIC_MAIN_IMAGE.value], UnavailableProvider
    )
