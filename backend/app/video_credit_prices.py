"""Video studio credit prices shown next to every paid action.

Prices are a business decision and come only from configuration
(``POLARIS_VIDEO_CREDIT_PRICES``, a JSON object keyed by the actions below). An
action without a configured price is reported as unpriced; the page then marks
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
]
ACTIONS: tuple[str, ...] = VideoPricedAction.__args__  # type: ignore[attr-defined]
PRICING_VERSION = "video-credits-config-v1"


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
