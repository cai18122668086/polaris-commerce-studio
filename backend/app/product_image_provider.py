"""Provider adapter for the eight product-image presets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.new_image_skill_provider import (
    NewImageSkillContractError,
    NewImageSkillProvider,
    compact_prompt_input,
    controlled_target,
    optional_string,
    require_asset_ids,
    require_image_count,
    require_non_empty_string,
    role_labelled_assets,
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
        product_asset_ids = require_asset_ids(input_config, "product_asset_ids")
        reference_asset_ids = validate_optional_asset_ids(
            input_config, "reference_asset_ids"
        )
        role_labelled_assets(
            ("product_reference", product_asset_ids),
            ("style_reference", reference_asset_ids),
        )
        require_image_count(settings)
        controlled_target(settings)
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
        optional_string(settings, "platform_code", default="tmall")
        optional_string(settings, "instruction")
        if task_type == "change_color":
            require_non_empty_string(
                settings,
                "target_color",
                code="TARGET_COLOR_REQUIRED",
            )
        elif "target_color" in settings and settings["target_color"] is not None:
            optional_string(settings, "target_color")

    def source_assets(
        self,
        input_config: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        return role_labelled_assets(
            (
                "product_reference",
                require_asset_ids(input_config, "product_asset_ids"),
            ),
            (
                "style_reference",
                validate_optional_asset_ids(input_config, "reference_asset_ids"),
            ),
        )

    def prompt_input(
        self,
        settings: Mapping[str, Any],
        item_config: Mapping[str, Any],
    ) -> dict[str, Any]:
        del item_config
        task_type = require_non_empty_string(
            settings,
            "task_type",
            code="PRODUCT_IMAGE_PRESET_REQUIRED",
        )
        prompt: dict[str, Any] = {
            "task_type": task_type,
            "platform_code": optional_string(
                settings, "platform_code", default="tmall"
            ),
            "reference_guidance": optional_string(settings, "instruction"),
        }
        target_color = settings.get("target_color")
        if target_color is not None:
            prompt["target_color"] = optional_string(settings, "target_color")
        return compact_prompt_input(prompt)
