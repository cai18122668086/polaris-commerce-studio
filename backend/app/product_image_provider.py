"""Provider adapter for the eight product-image presets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.new_image_skill_provider import (
    NewImageSkillContractError,
    NewImageSkillProvider,
    require_asset_ids,
    require_image_count,
    require_non_empty_string,
    validate_optional_asset_ids,
)

PRODUCT_IMAGE_PRESETS = frozenset(
    {
        "scene_main",
        "white_background",
        "model_image",
        "change_model",
        "try_on",
        "change_scene",
        "change_background",
        "change_color",
    }
)


class ProductImageProvider(NewImageSkillProvider):
    """Authorize and delegate one product-image JobItem."""

    operation = "product_image"
    skill_id = "xinghe-wanneng-shengtu-3-0"

    def validate_configuration(
        self,
        input_config: Mapping[str, Any],
        settings: Mapping[str, Any],
        item_config: Mapping[str, Any],
    ) -> None:
        del item_config
        require_asset_ids(input_config, "product_asset_ids")
        validate_optional_asset_ids(input_config, "reference_asset_ids")
        require_image_count(settings)
        task_type = require_non_empty_string(
            settings,
            "task_type",
            code="PRODUCT_IMAGE_PRESET_REQUIRED",
        )
        if task_type not in PRODUCT_IMAGE_PRESETS:
            raise NewImageSkillContractError(
                "PRODUCT_IMAGE_PRESET_NOT_SUPPORTED",
                "The requested product-image preset is not supported.",
            )
        if task_type == "change_color":
            require_non_empty_string(
                settings,
                "target_color",
                code="TARGET_COLOR_REQUIRED",
            )
