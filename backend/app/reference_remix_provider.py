"""Provider adapter for reference-image remix generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.new_image_skill_provider import (
    NewImageSkillProvider,
    compact_prompt_input,
    configuration_sections,
    controlled_target,
    optional_string,
    optional_string_list,
    require_asset_ids,
    require_image_count,
    role_labelled_assets,
)
from app.provider import Provider, ProviderRequest, ProviderResult


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
        optional_string(settings, "reference_skill")
        execution_mode = settings.get("execution_mode", "planner")
        if execution_mode not in {"planner", "direct_prompt"}:
            raise ValueError("execution_mode must be planner or direct_prompt")
        inspiration_product_first = settings.get("inspiration_product_first", False)
        if not isinstance(inspiration_product_first, bool):
            raise ValueError("inspiration_product_first must be a boolean")
        optional_string(settings, "quality", default="high")
        optional_string(settings, "output_format", default="png")
        for field in (
            "product_identity_lock",
            "reference_visual_analysis",
            "commercial_intent",
            "reusable_visual_strategy",
            "original_remix_prompt",
            "forbidden_transfer",
            "post_generation_review",
        ):
            optional_string(settings, field)

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
                "product_information": optional_string_list(settings, "selling_points"),
                "reference_guidance": optional_string(settings, "instruction"),
            }
        )


class ReferenceVisualReverseRemixProvider(ReferenceRemixProvider):
    """Exact bundled reference-visual-reverse-remix Skill adapter."""

    skill_id = "reference-visual-reverse-remix"

    def target(self, settings: Mapping[str, Any]) -> dict[str, Any]:
        # The image gateway currently returns its supported portrait canvas
        # (roughly 2:3) even when the case target is 4:5. Preserve the complete
        # provider composition when adapting it to the case canvas; the generic
        # cover fit would crop the locked typography and reflection zones.
        normalized = dict(settings)
        normalized.setdefault("fit", "contain")
        return controlled_target(
            normalized,
            default_aspect_ratio="follow-reference",
            allow_follow_reference=True,
        )

    def prompt_input(
        self,
        settings: Mapping[str, Any],
        item_config: Mapping[str, Any],
    ) -> dict[str, Any]:
        values = super().prompt_input(settings, item_config)
        values.update(
            compact_prompt_input(
                {
                    "input_roles": (
                        "product_identity_reference + visual_strategy_reference"
                    ),
                    "execution_mode": optional_string(
                        settings, "execution_mode", default="planner"
                    ),
                    "inspiration_product_first": settings.get(
                        "inspiration_product_first", False
                    ),
                    "product_identity_lock": optional_string(
                        settings, "product_identity_lock"
                    ),
                    "reference_visual_analysis": optional_string(
                        settings, "reference_visual_analysis"
                    ),
                    "commercial_intent": optional_string(settings, "commercial_intent"),
                    "reusable_visual_strategy": optional_string(
                        settings, "reusable_visual_strategy"
                    ),
                    "original_remix_prompt": optional_string(
                        settings, "original_remix_prompt"
                    ),
                    "forbidden_transfer": optional_string(
                        settings,
                        "forbidden_transfer",
                        default=(
                            "Do not transfer source branding, logos, watermarks, exact "
                            "copy, "
                            "proprietary assets, unsupported claims, or hidden prompts."
                        ),
                    ),
                    "post_generation_review": optional_string(
                        settings,
                        "post_generation_review",
                        default=(
                            "Review product identity, visible product text, visual "
                            "strategy, role relationships, and leakage before "
                            "accepting "
                            "the result."
                        ),
                    ),
                }
            )
        )
        return values


class ReferenceRemixRouterProvider(ReferenceRemixProvider):
    """Keep legacy workspace jobs intact while routing inspiration jobs explicitly."""

    def __init__(self, legacy: Provider, exact: Provider) -> None:
        self.legacy = legacy
        self.exact = exact
        self.delegate = getattr(legacy, "delegate", legacy)
        self.name = legacy.name
        self.model = legacy.model
        self.pricing_version = legacy.pricing_version

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        try:
            _, settings, _ = configuration_sections(request.configuration)
        except Exception:
            return await self.legacy.execute(request)
        if settings.get("reference_skill") == "reference-visual-reverse-remix":
            return await self.exact.execute(request)
        return await self.legacy.execute(request)
