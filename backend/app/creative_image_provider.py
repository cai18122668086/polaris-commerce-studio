"""Provider adapter for ecommerce creative-image generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.new_image_skill_provider import (
    NewImageSkillProvider,
    require_asset_ids,
    require_image_count,
    validate_optional_asset_ids,
)


class CreativeImageProvider(NewImageSkillProvider):
    """Authorize and delegate one independent ecommerce creative image."""

    operation = "creative_image"
    skill_id = "xinghe-ecommerce-creative-image"

    def validate_configuration(
        self,
        input_config: Mapping[str, Any],
        settings: Mapping[str, Any],
        item_config: Mapping[str, Any],
    ) -> None:
        del item_config
        require_asset_ids(input_config, "product_asset_ids")
        validate_optional_asset_ids(input_config, "competitor_asset_ids")
        require_image_count(settings)
