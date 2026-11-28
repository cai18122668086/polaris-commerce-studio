"""Image routes shared by video-studio image features (covers, supplement images).

Same routing as the site's image generation: the primary image route first,
then — when ``POLARIS_PROVIDER_FAILOVER_ENABLED`` — the failover base URL with
``provider_failover_image_model``. The failover key setting may hold an ordered
list ("k1, k2, ..."); like ``xinghe_agent`` each key becomes its own route
(failover-1, failover-2, ...). Callers move to the next route only on transport
errors, 5xx, 401/403 from a route key, or 429.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Settings


@dataclass(frozen=True)
class ImageRoute:
    name: str
    base_url: str
    api_key: str
    model: str


def image_routes(settings: Settings) -> list[ImageRoute]:
    routes: list[ImageRoute] = []
    primary_key = settings.image_api_key.get_secret_value().strip()
    if primary_key and settings.image_base_url.startswith("https://"):
        routes.append(
            ImageRoute(
                "primary",
                settings.image_base_url.rstrip("/"),
                primary_key,
                settings.image_model,
            )
        )
    keys = [
        part.strip()
        for part in re.split(
            r"[\s,]+", settings.provider_failover_api_key.get_secret_value()
        )
        if part.strip()
    ]
    if (
        settings.provider_failover_enabled
        and keys
        and settings.provider_failover_base_url.startswith("https://")
    ):
        for index, key in enumerate(keys, start=1):
            routes.append(
                ImageRoute(
                    "failover" if len(keys) == 1 else f"failover-{index}",
                    settings.provider_failover_base_url.rstrip("/"),
                    key,
                    settings.provider_failover_image_model,
                )
            )
    return routes
