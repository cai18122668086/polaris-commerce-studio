"""Video studio credit prices shown next to every paid action.

Prices are a business decision and come only from configuration
(``POLARIS_VIDEO_CREDIT_PRICES``, a JSON object keyed by the actions below).
When the variable is not set, ``DEFAULT_PRICES`` applies (derivation in
``docs/video-pricing-20261125.md``); ``{}`` turns every action back to unpriced.
An action without a configured price is reported as unpriced; the page then marks
the button as billable and says it is charged by actual usage instead of
showing a made-up number, and the action is not charged. Priced actions are
held, settled and released by ``video_credit_billing``.
"""

from typing import Literal

from pydantic import BaseModel

VideoPricedAction = Literal[
    "lipsync",
    "avatar_motion",
    "avatar_register",
    "voice_clone",
    "editing_planning",
    "editing_render",
    "benchmark_search",
    "writing_generate",
    "cover_generate",
    "editing_auto_image",
    "avatar_polish",
]
ACTIONS: tuple[str, ...] = VideoPricedAction.__args__  # type: ignore[attr-defined]
PRICING_VERSION = "video-credits-config-v1"

# Flat credits per successful action: vendor cost (conservative) x 3 / 0.06 CNY
# per credit (cheapest plan rate), rounded up to a friendly number. See
# docs/video-pricing-20261125.md before changing any value.
DEFAULT_PRICES: dict[str, int] = {
    "lipsync": 50,
    "avatar_motion": 60,
    "avatar_register": 5,
    "voice_clone": 30,
    "editing_planning": 10,
    "editing_render": 10,
    "benchmark_search": 5,
    "writing_generate": 10,
    # Image actions are a flat 7 credits per image (approved 2026-11-28).
    "cover_generate": 7,
    # AI 补充配图：¥0.1/张 ×1.25 失败余量 ×3 ÷ ¥0.06 → 7（负责人定价）
    "editing_auto_image": 7,
    # AI 润色形象照：图片类统一 7 积分 / 张（2026-11-28 批准），失败不扣
    "avatar_polish": 7,
}


class VideoCreditPrice(BaseModel):
    action: VideoPricedAction
    credits: int | None


class VideoCreditPricesResponse(BaseModel):
    pricing_version: str
    configured: bool
    prices: list[VideoCreditPrice]


def price_list(configured: dict[str, int]) -> VideoCreditPricesResponse:
    prices = [
        VideoCreditPrice(
            action=action,  # type: ignore[arg-type]
            credits=configured[action]
            if isinstance(configured.get(action), int) and configured[action] >= 0
            else None,
        )
        for action in ACTIONS
    ]
    return VideoCreditPricesResponse(
        pricing_version=PRICING_VERSION,
        configured=any(item.credits is not None for item in prices),
        prices=prices,
    )
