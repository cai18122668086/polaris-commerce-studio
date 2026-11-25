"""benchmark_search e2e (2026-11-25): 11 paid rows, 0 kept, no way to tell why.

Skipped rows now carry a reason (receipt only, no media/page URLs) and the
checks that were stricter than the data needs gained a fallback: a row
without a page URL, or with a share short link, is identified by its numeric
post id; a row without media_type but with a /video/ page is a video.
"""

from collections import Counter
from datetime import UTC, datetime

from app.video_benchmark import benchmark_page, candidate, drop_reason

POST = "7697610661158075300"


def row(**changes):
    return {
        "id": POST,
        "url": f"https://www.douyin.com/video/{POST}?previous_page=search",
        "media_type": "video",
        "video_url": "https://media.invalid/clip.mp4?signature=private",
        "duration_sec": 8,
        "like_count": 10,
        **changes,
    }


def page(rows):
    inputs = {
        "page": 1,
        "root_task_id": None,
        "previous_task_id": None,
        "seen_ids": [],
        "search_params": {
            "keyword": "头戴耳机",
            "sort": "most_liked",
            "publish_time": "half_year",
            "page_token": None,
        },
    }
    return benchmark_page({"results": rows}, "task", inputs, datetime.now(UTC))


def test_saved_shape_row_is_kept():
    assert drop_reason(row()) is None
    assert candidate(row())["source_url"] == "https://www.douyin.com/video/" + POST


def test_fallbacks_for_missing_url_short_link_and_missing_media_type():
    assert candidate(row(url=None))["platform_id"] == POST
    assert candidate(row(url="https://v.douyin.com/iAbCdEf/"))["platform_id"] == POST
    no_type = {k: v for k, v in row().items() if k != "media_type"}
    assert candidate(no_type)["platform_id"] == POST


def test_each_drop_has_a_reason_and_no_url_is_stored():
    rows = [
        row(),
        row(media_type="image"),
        row(duration_sec=301),
        row(url=["malformed"]),
        row(url="https://elsewhere.invalid/video/" + POST),
        row(url="https://www.douyin.com/video/7697610661158075301"),
        row(id="abc"),
        row(url=None, media_type=None),
    ]
    result, receipt = page(rows)
    assert result["skipped_count"] == 7 and len(result["items"]) == 1
    assert result["skip_reasons"] == dict(
        Counter(
            {
                "media_type_image": 1,
                "longer_than_300s": 1,
                "url_invalid": 1,
                "url_not_video": 1,
                "url_id_mismatch": 1,
                "invalid_id": 1,
                "missing_url": 1,
            }
        )
    )
    diagnostics = receipt["skipped_rows"]
    assert len(diagnostics) == 7
    text = repr(diagnostics)
    assert "signature=private" not in text and "media.invalid" not in text
    assert all(POST not in str(d.get("url_shape")) for d in diagnostics)
