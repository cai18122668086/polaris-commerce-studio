"""Independent adapter for the newly installed cross-border detail skill."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.new_detail_skill_provider import (
    AdapterValidationError,
    DetailSkillRoute,
    ManifestValidator,
    NewDetailSkillProvider,
    normalized_text,
    requested_language,
    requested_page_count,
)
from app.provider import Provider

CROSSBORDER_DETAIL_SKILL_ID = "xinghe-crossborder-detail-3"
INTERNATIONAL_MARKET_REGION = "international"
CROSSBORDER_DEFAULT_PLATFORM = "generic_crossborder_pdp"

_CROSSBORDER_PLATFORM_ALIASES = {
    "amazon": "amazon",
    "shopify": "shopify",
    "temu": "temu",
    "aliexpress": "aliexpress",
    "ali_express": "aliexpress",
    "tiktok_shop": "tiktok_shop",
    "tiktokshop": "tiktok_shop",
    "ozon": "ozon",
    "wildberries": "wildberries",
    "wb": "wildberries",
    "generic": "generic_crossborder_pdp",
    "generic_crossborder_pdp": "generic_crossborder_pdp",
    "\u901a\u7528\u8de8\u5883_pdp": "generic_crossborder_pdp",
    "\u901a\u7528\u8de8\u5883pdp": "generic_crossborder_pdp",
}
_RUSSIAN_VERTICAL_PLATFORMS = {"ozon", "wildberries"}


def crossborder_detail_prompt_configuration(
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Build platform-aware cross-border planner defaults."""

    requested_platform = normalized_text(
        configuration.get("platform_code", CROSSBORDER_DEFAULT_PLATFORM)
    )
    platform_code = _CROSSBORDER_PLATFORM_ALIASES.get(requested_platform)
    if platform_code is None:
        raise AdapterValidationError(
            "DETAIL_PLATFORM_UNSUPPORTED",
            f"Unsupported cross-border platform: {requested_platform}.",
        )
    is_russian_vertical = platform_code in _RUSSIAN_VERTICAL_PLATFORMS
    default_language = "ru" if is_russian_vertical else "en"
    target_size: dict[str, Any]
    if is_russian_vertical:
        target_size = {
            "mode": "exact",
            "width": 900,
            "height": 1200,
            "aspect_ratio": "3:4",
        }
    else:
        target_size = {
            "mode": "quality_tier",
            "quality": "2K",
            "aspect_ratio": "16:9",
        }
    return {
        "profile_id": f"crossborder_{platform_code}_v1",
        "platform_code": platform_code,
        "language": requested_language(configuration, default_language),
        "requested_page_count": requested_page_count(configuration),
        "default_page_count": 8,
        "aspect_ratio": "3:4" if is_russian_vertical else "16:9",
        "target_size": target_size,
        "module_rule": "one_buyer_demand_per_page",
        "independent_page_generation": True,
        "continue_after_single_page_failure": True,
        "successful_page_auto_redraw_allowed": False,
    }


class CrossborderDetailProvider(NewDetailSkillProvider):
    """Manifest-gated provider selected for the new international gray path."""

    def __init__(
        self,
        delegate: Provider,
        *,
        manifest_validator: ManifestValidator | None = None,
    ) -> None:
        super().__init__(
            delegate,
            DetailSkillRoute(
                skill_id=CROSSBORDER_DETAIL_SKILL_ID,
                market_region=INTERNATIONAL_MARKET_REGION,
                configure_prompt=crossborder_detail_prompt_configuration,
            ),
            manifest_validator=manifest_validator,
        )
