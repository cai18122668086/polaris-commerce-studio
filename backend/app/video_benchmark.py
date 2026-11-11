"""Normalize one public Douyin search page without storing media URLs."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from .errors import ApiError
from .video_assistance_provider import video_source_url

BENCHMARK_KIND = "benchmark_search"
MAX_PAGES = 10
VIDEO_PREFIX = "https://www.douyin.com/video/"
METRICS = ("like_count", "comment_count", "collect_count", "share_count")
SOURCE_FIELDS = (
    "id",
    "text",
    "media_type",
    "author_name",
    "author_id",
    "author_follower_count",
    "posted_at",
    "duration_sec",
    "search_rank",
    "view_count",
    *METRICS,
)


def count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def label(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def posted_at(value: Any) -> str | None:
    if isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo:
                return stamp.astimezone(UTC).isoformat()
        except (ValueError, OverflowError):
            pass
    return None


def candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    post_id = row.get("id")
    if type(post_id) is int:
        post_id = str(post_id)
    if not isinstance(post_id, str) or not re.fullmatch(r"[0-9]{6,25}", post_id):
        return None
    url = VIDEO_PREFIX + post_id
    source_url = row.get("url")
    if not isinstance(source_url, str):
        return None
    try:
        if video_source_url(source_url) != url:
            return None
    except ApiError:
        return None
    duration = row.get("duration_sec")
    duration = (
        duration
        if isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and duration > 0
        else None
    )
    if duration is not None and duration > 300:
        return None
    metrics = {key: count(row.get(key)) for key in METRICS}
    likes = metrics["like_count"]
    collects, shares = metrics["collect_count"], metrics["share_count"]
    return {
        "platform_id": post_id,
        "source_url": url,
        "description": label(row.get("text"), 6000),
        "author_name": label(row.get("author_name"), 200) or None,
        "author_id": label(row.get("author_id"), 200) or None,
        "author_follower_count": count(row.get("author_follower_count")),
        "posted_at": posted_at(row.get("posted_at")),
        "duration_seconds": duration,
        "search_rank": count(row.get("search_rank")),
        "media_status": (
            "link_reported"
            if label(row.get("video_url"), 8) == "https://"
            else "unverified"
        ),
        **metrics,
        "collect_like_ratio": collects / likes
        if likes and collects is not None
        else None,
        "share_like_ratio": shares / likes if likes and shares is not None else None,
    }


def page_identity(task_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "page": inputs["page"],
        "root_task_id": inputs["root_task_id"] or task_id,
        "previous_task_id": inputs["previous_task_id"],
        **{
            key: inputs["search_params"][key]
            for key in ("keyword", "sort", "publish_time")
        },
    }


def benchmark_page(
    data: dict[str, Any], task_id: str, inputs: dict[str, Any], captured_at: datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = data.get("results")
    if not isinstance(rows, list) or len(rows) > 250:
        raise ApiError(
            502, "VIDEO_BENCHMARK_RESPONSE_INVALID", "对标搜索回执格式异常。"
        )

    params, page = inputs["search_params"], inputs["page"]
    seen = set(inputs["seen_ids"])
    items, original_rows = [], []
    duplicates = skipped = 0
    for row in rows:
        item = (
            candidate(row)
            if isinstance(row, dict) and row.get("media_type") == "video"
            else None
        )
        if item is None:
            skipped += 1
            continue
        if item["platform_id"] in seen:
            duplicates += 1
            continue
        seen.add(item["platform_id"])
        items.append(item)
        original_rows.append(
            {
                "source_url": item["source_url"],
                **{
                    key: row[key][:12000] if isinstance(row[key], str) else row[key]
                    for key in SOURCE_FIELDS
                    if key in row and (row[key] is None or type(row[key]) in {int, str})
                },
                "duration_sec": (
                    row["duration_sec"]
                    if item["duration_seconds"] is not None
                    else None
                ),
            }
        )

    token = data.get("next_page_token")
    if (
        not isinstance(token, str)
        or not token.strip()
        or len(token) > 8192
        or token == params["page_token"]
        or page >= MAX_PAGES
    ):
        token = None
    authors = Counter(item["author_id"] for item in items if item["author_id"])
    billing = data.get("billing")
    return {
        "items": items,
        **page_identity(task_id, inputs),
        "captured_at": captured_at.isoformat(),
        "has_more": token is not None,
        "next_page_expires_at": (captured_at + timedelta(hours=24)).isoformat()
        if token
        else None,
        "received_count": len(rows),
        "duplicate_count": duplicates,
        "skipped_count": skipped,
        "author_count": len(authors),
        "top_author_item_count": max(authors.values(), default=0),
        "unknown_author_count": sum(not item["author_id"] for item in items),
    }, {
        "provider_id": label(data.get("id"), 160),
        "billing": {
            key: billing[key]
            for key in ("charged", "charged_usd")
            if isinstance(billing, dict)
            and isinstance(billing.get(key), (bool, int, float, str))
        },
        "original_rows": original_rows,
        "seen_ids": sorted(seen),
        "next_page_token": token,
    }
