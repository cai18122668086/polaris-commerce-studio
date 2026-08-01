"""Independent adapter for the newly installed domestic detail skill."""

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

DOMESTIC_DETAIL_SKILL_ID = "xinghe-ecommerce-detail-domestic-3"
DOMESTIC_MARKET_REGION = "domestic"
DOMESTIC_DEFAULT_PLATFORM = "taobao_tmall"

_DOMESTIC_PLATFORM_ALIASES = {
    "taobao": "taobao_tmall",
    "tmall": "taobao_tmall",
    "taobao_tmall": "taobao_tmall",
    "\u6dd8\u5b9d": "taobao_tmall",
    "\u5929\u732b": "taobao_tmall",
    "\u6dd8\u5b9d/\u5929\u732b": "taobao_tmall",
    "jd": "jd",
    "jingdong": "jd",
    "\u4eac\u4e1c": "jd",
    "pdd": "pinduoduo",
    "pinduoduo": "pinduoduo",
    "\u62fc\u591a\u591a": "pinduoduo",
    "douyin": "douyin",
    "douyin_ecommerce": "douyin",
    "\u6296\u97f3": "douyin",
    "\u6296\u97f3\u7535\u5546": "douyin",
    "xiaohongshu": "xiaohongshu",
    "\u5c0f\u7ea2\u4e66": "xiaohongshu",
    "other": "other_domestic",
    "other_domestic": "other_domestic",
    "\u5176\u4ed6\u56fd\u5185\u5e73\u53f0": "other_domestic",
}


def domestic_detail_prompt_configuration(
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Build canonical domestic planner defaults without mutating user input."""

    requested_platform = normalized_text(
        configuration.get("platform_code", DOMESTIC_DEFAULT_PLATFORM)
    )
    platform_code = _DOMESTIC_PLATFORM_ALIASES.get(requested_platform)
    if platform_code is None:
        raise AdapterValidationError(
            "DETAIL_PLATFORM_UNSUPPORTED",
            f"Unsupported domestic platform: {requested_platform}.",
        )
    return {
        "profile_id": f"domestic_{platform_code}_v1",
        "platform_code": platform_code,
        "language": requested_language(configuration, "zh-CN"),
        "requested_page_count": requested_page_count(configuration),
        "default_page_count": 8,
        "aspect_ratio": "3:4",
        "target_size": {
            "mode": "aspect_ratio",
            "aspect_ratio": "3:4",
        },
        "module_rule": "one_buyer_demand_per_page",
        "independent_page_generation": True,
        "successful_page_auto_redraw_allowed": False,
    }


class DomesticDetailProvider(NewDetailSkillProvider):
    """Manifest-gated provider selected only for ``market_region=domestic``."""

    def __init__(
        self,
        delegate: Provider,
        *,
        manifest_validator: ManifestValidator | None = None,
    ) -> None:
        super().__init__(
            delegate,
            DetailSkillRoute(
                skill_id=DOMESTIC_DETAIL_SKILL_ID,
                market_region=DOMESTIC_MARKET_REGION,
                configure_prompt=domestic_detail_prompt_configuration,
            ),
            manifest_validator=manifest_validator,
        )
