"""Provider adapter for reference-image remix generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.new_image_skill_provider import (
    NewImageSkillProvider,
    compact_prompt_input,
    controlled_target,
    optional_string,
    optional_string_list,
    require_asset_ids,
    require_image_count,
    role_labelled_assets,
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
        product_asset_ids = require_asset_ids(input_config, "product_asset_ids")
        reference_asset_ids = require_asset_ids(input_config, "reference_asset_ids")
        role_labelled_assets(
            ("product_reference", product_asset_ids),
            ("style_reference", reference_asset_ids),
        )
        require_image_count(settings)
        controlled_target(
            settings,
            default_aspect_ratio="follow-reference",
            allow_follow_reference=True,
        )
        optional_string(settings, "platform_code", default="tmall")
        optional_string(settings, "language", default="zh-CN")
        optional_string_list(settings, "selling_points")
        optional_string(settings, "instruction")

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
                require_asset_ids(input_config, "reference_asset_ids"),
            ),
        )

    def target(self, settings: Mapping[str, Any]) -> dict[str, Any]:
        return controlled_target(
            settings,
            default_aspect_ratio="follow-reference",
            allow_follow_reference=True,
        )

    def prompt_input(
        self,
        settings: Mapping[str, Any],
        item_config: Mapping[str, Any],
    ) -> dict[str, Any]:
        del item_config
        return compact_prompt_input(
            {
                "platform_code": optional_string(
                    settings, "platform_code", default="tmall"
                ),
                "language": optional_string(settings, "language", default="zh-CN"),
                "product_information": optional_string_list(
                    settings, "selling_points"
                ),
                "reference_guidance": optional_string(settings, "instruction"),
            }
        )
