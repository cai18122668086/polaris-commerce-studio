"""Provider reservation bound for confirmed native replica execution."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SKILLS = {
    "exact": "aurora-ecommerce-reference-remix",
    "style": "all-category-style-benchmark-still",
}


def native_replica_budget(
    configuration: Mapping[str, Any],
    item_count: int,
    image_budget_micros: int,
    review_reserve_micros: int,
) -> tuple[int, int, int] | None:
    """Return cost, HTTP request and review bounds; never authorize more work.

    Each canvas allows an initial image and one repair, each with at most two
    image routes. Every native contract allows three schema-validation attempts.
    Exact execution has two pixel audits and one repair-plan contract per module;
    style execution has two audits per target and one final set-audit contract.
    Native planner dispatch is single-route. Planning before confirmation is
    separately recorded by the replica analysis session.
    """

    settings = configuration.get("settings")
    if not isinstance(settings, Mapping):
        return None
    method = settings.get("replication_method")
    if (
        not isinstance(method, str)
        or method not in _SKILLS
        or settings.get("reference_skill") != _SKILLS[method]
        or not re.fullmatch(
            r"rep_[a-f0-9]{32}", str(configuration.get("replica_session_id", ""))
        )
        or not re.fullmatch(r"[a-f0-9]{64}", str(settings.get("replica_plan_hash", "")))
        or type(item_count) is not int
        or item_count <= 0
        or settings.get("image_count") != item_count
    ):
        return None
    review_requests = 9 * item_count if method == "exact" else 6 * item_count + 3
    image_requests = 4 * item_count
    return (
        4 * image_budget_micros + review_requests * review_reserve_micros,
        image_requests + review_requests,
        review_requests,
    )
