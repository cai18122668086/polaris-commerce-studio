"""Provider adapter for reference-image remix generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.new_image_skill_provider import (
    NewImageSkillProvider,
    require_asset_ids,
    require_image_count,
)


class ReferenceRemixProvider(NewImageSkillProvider):
    """Require both product facts and style-reference clues before delegation."""

    operation = "reference_remix"
    skill_id = "xinghe-reference-image-remix-3"

    def validate_configuration(
        self,
        input_config: Mapping[str, Any],
        settings: Mapping[str, Any],
        item_config: Mapping[str, Any],
    ) -> None:
        del item_config
        require_asset_ids(input_config, "product_asset_ids")
        require_asset_ids(input_config, "reference_asset_ids")
        require_image_count(settings)
