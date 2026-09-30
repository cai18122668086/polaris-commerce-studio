"""Provider adapter for ecommerce creative-image generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.new_image_skill_provider import (
    NewImageSkillContractError,
    NewImageSkillProvider,
    compact_prompt_input,
    controlled_target,
    optional_string,
    optional_string_list,
    require_asset_ids,
    require_image_count,
    role_labelled_assets,
    validate_optional_asset_ids,
)

CREATIVE_DIRECTIONS = frozenset(
    {"selling_point", "pain_point", "scenario", "promotion", "premium", "social"}
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
        product_asset_ids = require_asset_ids(input_config, "product_asset_ids")
        competitor_asset_ids = validate_optional_asset_ids(
            input_config, "competitor_asset_ids"
        )
        role_labelled_assets(
            ("product_reference", product_asset_ids),
            ("competitor_reference", competitor_asset_ids),
        )
        require_image_count(settings)
        self.target(settings)
        creative_direction = optional_string(
            settings,
            "creative_direction",
            default="selling_point",
        )
        if creative_direction not in CREATIVE_DIRECTIONS:
            raise NewImageSkillContractError(
                "CREATIVE_DIRECTION_NOT_SUPPORTED",
                "The requested creative direction is not supported.",
            )
        optional_string(settings, "platform_code", default="tmall")
        optional_string(settings, "language", default="zh-CN")
        optional_string_list(settings, "selling_points")
        optional_string(settings, "instruction")
        optional_string(settings, "user_instruction")
        if (
            settings.get("inspiration_planning") is not None
            and type(settings["inspiration_planning"]) is not bool
        ):
            raise NewImageSkillContractError(
                "INSPIRATION_PLANNING_INVALID",
                "inspiration_planning must be a boolean.",
            )
        if settings.get("inspiration_reference_planning") not in {None, True, False}:
            raise NewImageSkillContractError(
                "INSPIRATION_REFERENCE_PLANNING_INVALID",
                "inspiration_reference_planning must be a boolean.",
            )

    def target(self, settings: Mapping[str, Any]) -> dict[str, Any]:
        # The Inspiration tab's automatic canvas follows the first reference
        # image and falls back to the first product image. The standalone
        # creative-image workspace remains fixed-canvas only.
        return controlled_target(
            settings,
            allow_follow_reference=settings.get("inspiration_planning") is True,
        )

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
                "competitor_reference",
                validate_optional_asset_ids(input_config, "competitor_asset_ids"),
            ),
        )

    def prompt_input(
        self,
        settings: Mapping[str, Any],
        item_config: Mapping[str, Any],
    ) -> dict[str, Any]:
        del item_config
        inspiration_mode = settings.get("inspiration_planning") is True
        instruction = optional_string(settings, "instruction")
        return compact_prompt_input(
            {
                "creative_direction": optional_string(
                    settings,
                    "creative_direction",
                    default="selling_point",
                ),
                "platform_code": optional_string(
                    settings, "platform_code", default="tmall"
                ),
                "language": optional_string(settings, "language", default="zh-CN"),
                "product_information": optional_string_list(settings, "selling_points"),
                "user_instruction": (
                    optional_string(settings, "user_instruction") or instruction
                )
                if inspiration_mode
                else "",
                # Preserve the established creative-image contract everywhere
                # outside the Inspiration tab. Only the opt-in Inspiration
                # path promotes the one-line brief to a first-class field.
                "negative_constraints": instruction
                if not inspiration_mode
                else optional_string(settings, "negative_constraints"),
                "planning_mode": (
                    "reference"
                    if settings.get("inspiration_reference_planning") is True
                    else (
                        "creative"
                        if settings.get("inspiration_planning") is True
                        else ""
                    )
                ),
            }
        )
