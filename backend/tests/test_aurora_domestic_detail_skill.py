# ruff: noqa: E501
from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from PIL import Image

from app.domestic_detail_provider import (
    DOMESTIC_DETAIL_SKILL_ID,
    domestic_detail_prompt_configuration,
)
from app.provider import ProviderArtifact
from app.xinghe_agent import (
    XingheImageProvider,
    _split_aurora_pair_artifact,
    _validated_image_size,
)


def test_aurora_domestic_contract_is_pair_first_and_serial() -> None:
    contract = domestic_detail_prompt_configuration(
        {"page_count": 8, "platform_code": "tmall"}
    )
    assert DOMESTIC_DETAIL_SKILL_ID == "aurora-domestic-ecommerce-detail-page"
    assert contract["pair_count"] == 4
    assert contract["pair_aspect_ratio"] == "3:8"
    assert contract["screen_aspect_ratio"] == "3:4"
    assert contract["pair_generation"] == "one_3_8_canvas_then_deterministic_two_3_4_slices"
    assert contract["reference_edit_concurrency"] == 1
    assert contract["approval_gate"]["auto_confirm_after_validation"] is False
    assert contract["pixel_audit"]["max_automatic_repairs"] == 1


@pytest.mark.parametrize("count", [1, 6, 9, 11, 13])
def test_aurora_rejects_non_canonical_module_count(count: int) -> None:
    with pytest.raises(ValueError, match="8, 10, or 12"):
        domestic_detail_prompt_configuration(
            {"page_count": count, "platform_code": "tmall"}
        )


def test_pair_canvas_is_deterministically_split_and_hash_bound() -> None:
    source = BytesIO()
    image = Image.new("RGB", (1200, 3200), (30, 90, 180))
    image.save(source, format="PNG")
    payload = source.getvalue()
    pair = ProviderArtifact(
        payload=payload,
        filename="pair.png",
        content_type="image/png",
        width=1200,
        height=3200,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    first, second = _split_aurora_pair_artifact(
        pair,
        screen_size="1200x1600",
        pair_id="P01",
        group_key="primary-product",
    )
    assert (first.width, first.height) == (1200, 1600)
    assert (second.width, second.height) == (1200, 1600)
    assert first.content_type == second.content_type == "image/png"
    assert first.sha256 == hashlib.sha256(first.payload).hexdigest()
    assert second.sha256 == hashlib.sha256(second.payload).hexdigest()


def test_pair_canvas_storage_key_is_stable_and_workspace_scoped() -> None:
    key = XingheImageProvider._aurora_pair_canvas_object_key(
        "ws_demo", "job_demo", "primary-product", "P01"
    )
    assert key.startswith("ws_demo/generated/aurora-pairs/")
    assert key.endswith(".png")
    assert key == XingheImageProvider._aurora_pair_canvas_object_key(
        "ws_demo", "job_demo", "primary-product", "P01"
    )
    assert key != XingheImageProvider._aurora_pair_canvas_object_key(
        "ws_other", "job_demo", "primary-product", "P01"
    )


def test_aurora_1440_screen_and_pair_sizes_are_supported() -> None:
    """The domestic UI's 1440x1920 slice must pass the shared request gate."""

    assert _validated_image_size("1440x1920") == "1440x1920"
    assert _validated_image_size("1440x3840") == "1440x3840"

