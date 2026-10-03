"""L2 shadow channel: original Skill references reach image generation."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

from app.aurora_l2_references import L2_PLANNING_REFERENCE_FILES, L2_REFERENCE_MARKER
from app.aurora_main_image_l1_provider import AuroraMainImageL1Provider
from app.aurora_main_image_l2_provider import (
    AuroraMainImageL2Provider,
)
from app.aurora_main_image_planner import AuroraMainImagePlanner
from app.aurora_main_image_provider import AuroraMainImageProvider
from app.domain import JobType
from app.execution import build_fake_coordinator
from app.provider import ProviderRequest
from app.provider_registry import RegisteredOperationRoutingProvider
from app.xinghe_agent import FakeXingheGateway


def _provider(tmp_path: Path) -> AuroraMainImageL2Provider:
    return AuroraMainImageL2Provider(
        session_factory=None,  # type: ignore[arg-type]
        gateway=FakeXingheGateway(),
        storage=None,  # type: ignore[arg-type]
        work_root=tmp_path / "work",
        execution_mode="parallel_v20",
    )


def _request(origin: str = "INITIAL") -> dict[str, object]:
    return {
        "page_index": 2,
        "generation_origin": origin,
        "generation_token": "token",
        "prompt": "page-specific compiled prompt",
        "imagegen_reference_paths": ["/product/source-01.jpg"],
        "page_contract": {"composition_archetype": "DOUBLE_SCALE_PROOF"},
    }


def test_shipped_provider_generation_hook_is_a_noop(tmp_path: Path) -> None:
    provider = AuroraMainImageProvider(
        session_factory=None,  # type: ignore[arg-type]
        gateway=FakeXingheGateway(),
        storage=None,  # type: ignore[arg-type]
        work_root=tmp_path / "work",
        execution_mode="parallel_v20",
    )
    original = _request()
    augmented = provider._augment_generation_request(
        ProviderRequest(
            workspace_id="workspace",
            job_id="job_l2",
            job_item_id="item",
            attempt_id="attempt",
            operation=JobType.DOMESTIC_MAIN_IMAGE.value,
            idempotency_key="key",
            configuration={},
        ),
        original,
    )
    assert augmented == original


def test_l2_injects_original_generation_references(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    original = _request()
    augmented = provider._augment_generation_request(
        ProviderRequest(
            workspace_id="workspace",
            job_id="job_l2",
            job_item_id="item",
            attempt_id="attempt",
            operation=JobType.DOMESTIC_MAIN_IMAGE.value,
            idempotency_key="key",
            configuration={},
        ),
        original,
    )

    assert original["prompt"] == "page-specific compiled prompt"
    assert L2_REFERENCE_MARKER in str(augmented["prompt"])
    for name in (
        "visual-strategy.md",
        "commercial-performance.md",
    ):
        assert name in str(augmented["prompt"])
    assert augmented["generation_token"] == original["generation_token"]
    assert augmented["imagegen_reference_paths"] == original[
        "imagegen_reference_paths"
    ]
    assert augmented["aurora_l2_reference_stage"] == "generation"


def test_l2_repair_adds_only_original_repair_section(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    augmented = provider._augment_generation_request(
        ProviderRequest(
            workspace_id="workspace",
            job_id="job_l2",
            job_item_id="item",
            attempt_id="attempt",
            operation=JobType.DOMESTIC_MAIN_IMAGE.value,
            idempotency_key="key",
            configuration={},
        ),
        _request("AUTOMATIC_REPAIR"),
    )
    prompt = str(augmented["prompt"])
    assert "visual-audit.md" in prompt
    assert "Ordinary repair edits" in prompt
    assert augmented["aurora_l2_reference_stage"] == "repair"

    repeated = provider._augment_generation_request(
        ProviderRequest(
            workspace_id="workspace",
            job_id="job_l2",
            job_item_id="item",
            attempt_id="attempt",
            operation=JobType.DOMESTIC_MAIN_IMAGE.value,
            idempotency_key="key",
            configuration={},
        ),
        augmented,
    )
    assert repeated["prompt"] == augmented["prompt"]


def test_l2_planning_injects_only_planning_references(tmp_path: Path) -> None:
    planner = AuroraMainImagePlanner(
        session_factory=None,  # type: ignore[arg-type]
        work_root=tmp_path / "work",
        l2_reference_enabled=True,
    )
    prompt = planner._identity_system_prompt()
    assert L2_REFERENCE_MARKER in prompt
    for relative in L2_PLANNING_REFERENCE_FILES:
        assert relative.name in prompt
    assert "visual-strategy.md" not in prompt
    assert "commercial-performance.md" not in prompt


def test_l2_switch_selects_only_the_shadow_route(client: TestClient) -> None:
    coordinator = build_fake_coordinator(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=FakeXingheGateway(),
        domestic_main_image_provider_enabled=True,
        aurora_l2_reference_enabled=True,
    )
    router = cast(RegisteredOperationRoutingProvider, coordinator.provider)
    route = router.routes[JobType.DOMESTIC_MAIN_IMAGE.value]
    assert type(route) is AuroraMainImageL2Provider
    assert isinstance(route, AuroraMainImageL1Provider)
