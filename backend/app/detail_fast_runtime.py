"""Version selection for independent domestic detail."""

from collections.abc import Mapping
from typing import Any

from . import aurora_detail_authored, detail_fast, refined_detail

# Contracts that run the fast-style execution: one authored plan, parallel
# independent screens through the durable fast gateway, no pixel review.
_FAST_STYLE = {
    detail_fast.PIPELINE_VERSION: detail_fast,
    aurora_detail_authored.PIPELINE_VERSION: aurora_detail_authored,
}
_FAST_STYLE_SKILLS = {
    detail_fast.SKILL_ID: detail_fast,
    aurora_detail_authored.SKILL_ID: aurora_detail_authored,
}


def is_fast(configuration: Mapping[str, Any]) -> bool:
    """Fast-style execution (quick fast detail or the authored 精致版)."""
    return configuration.get("domestic_detail_pipeline") in _FAST_STYLE


def is_independent(configuration: Mapping[str, Any]) -> bool:
    return is_fast(configuration) or refined_detail.is_refined(configuration)


def contract(configuration: Mapping[str, Any]) -> Any:
    return _FAST_STYLE.get(
        str(configuration.get("domestic_detail_pipeline")), refined_detail
    )


def skill_contract(skill_id: str | None) -> Any:
    return _FAST_STYLE_SKILLS.get(str(skill_id), refined_detail)


def fast_style_skill(skill_id: str | None) -> bool:
    return skill_id in _FAST_STYLE_SKILLS


def independent_skill(skill_id: str | None) -> bool:
    return skill_id in {*_FAST_STYLE_SKILLS, refined_detail.SKILL_ID}
