from uuid import uuid4

import httpx
import pytest

from app import video_benchmark_platforms as platforms
from app.errors import ApiError
from app.video_benchmark import benchmark_page
from app.video_writing_contracts import (
    SourceMetrics,
    WritingAnalysis,
    WritingReference,
)
from app.video_writing_provider import sanitize_analysis, validate_analysis
from app.video_writing_rules import sentence_units

XHS_ID = "66972605000000000d00eabe"


def test_every_platform_searches_by_likes():
    for platform in platforms.PLATFORMS:
        body = platforms.search_body(platform, "护手霜", "")
        assert body["platform"] == platform and body["action"] == "search"
        assert body["params"]["sort"] == "most_liked"
    assert (
        platforms.search_body("xiaohongshu", "k", "")["params"]["content_type"]
        == "video"
    )
    assert "page_token" not in platforms.search_body("bilibili", "k", "")["params"]
    assert platforms.search_body("bilibili", "k", "t")["params"]["page_token"] == "t"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.douyin.com/video/7705679663783316778",
            ("douyin", "7705679663783316778"),
        ),
        (
            "https://www.douyin.com/jingxuan?modal_id=7705679663783316778",
            ("douyin", "7705679663783316778"),
        ),
        (
            "https://www.iesdouyin.com/share/video/7705679663783316778/?region=CN",
            ("douyin", "7705679663783316778"),
        ),
        (
            f"https://www.xiaohongshu.com/explore/{XHS_ID}?xsec_token=AB12",
            ("xiaohongshu", XHS_ID),
        ),
        (
            f"http://www.xiaohongshu.com/discovery/item/{XHS_ID}",
            ("xiaohongshu", XHS_ID),
        ),
        (
            "https://www.bilibili.com/video/BV1nPczeqED6/?spm_id_from=333",
            ("bilibili", "BV1nPczeqED6"),
        ),
        ("https://m.bilibili.com/video/BV1nPczeqED6", ("bilibili", "BV1nPczeqED6")),
    ],
)
def test_full_post_links(url, expected):
    platform, post, canonical = platforms.parse_post(url)
    assert (platform, post) == expected and post in canonical
    assert canonical.startswith("https://")


def test_xhs_keeps_access_token_and_rejects_other_hosts():
    _, _, canonical = platforms.parse_post(
        f"https://www.xiaohongshu.com/explore/{XHS_ID}?xsec_token=AB12&x=1"
    )
    assert canonical.endswith("?xsec_token=AB12")
    for bad in [
        "https://www.kuaishou.com/short-video/3x",
        "https://user:pw@www.douyin.com/video/7705679663783316778",
        "https://www.bilibili.com/space/1",
    ]:
        with pytest.raises(ApiError):
            platforms.parse_post(bad)
    assert platforms.parse_post("https://v.douyin.com/abc/") is None


def test_links_in_share_text_and_short_link_redirects():
    text = (
        "3.07 复制打开抖音，看看【某某的作品】指如削葱根！ "
        "https://v.douyin.com/iAbCdEf/ 07/12 a@B.go\n还有 https://b23.tv/xYz12。"
    )
    assert platforms.links_in(text) == [
        "https://v.douyin.com/iAbCdEf/",
        "https://b23.tv/xYz12",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "v.douyin.com":
            return httpx.Response(
                302,
                headers={
                    "location": "https://www.iesdouyin.com/share/video/7705679663783316778/?from=web"
                },
            )
        return httpx.Response(200)

    resolved = platforms.resolve_link(
        "https://v.douyin.com/iAbCdEf/", httpx.MockTransport(handler)
    )
    assert resolved == (
        "douyin",
        "7705679663783316778",
        "https://www.douyin.com/video/7705679663783316778",
    )
    with pytest.raises(ApiError):
        platforms.resolve_link("https://b23.tv/xYz12", httpx.MockTransport(handler))


def page_inputs(platform):
    return {
        "platform": platform,
        "mode": "search",
        "search_params": {
            "keyword": "护手霜",
            "sort": "most_liked",
            "publish_time": "unlimited",
            "page_token": "",
        },
        "page": 1,
        "root_task_id": None,
        "previous_task_id": None,
        "seen_ids": [],
    }


def run_page(platform, rows):
    from datetime import UTC, datetime

    return benchmark_page(
        {"results": rows}, str(uuid4()), page_inputs(platform), datetime.now(UTC)
    )


def test_xhs_rows_sorted_by_likes_media_kept_private():
    rows = [
        {
            "id": "a" * 24,
            "url": "https://www.xiaohongshu.com/explore/" + "a" * 24,
            "title": "少赞",
            "text": "正文A",
            "like_count": 10,
            "collect_count": 5,
            "is_video": True,
            "video_url": "http://sns-video-v6.xhscdn.com/stream/1",
            "image_url": "https://sns-i.xhscdn.com/c.jpg",
            "duration_sec": 20,
        },
        {
            "id": "b" * 24,
            "url": "https://www.xiaohongshu.com/explore/" + "b" * 24,
            "title": "多赞",
            "text": "正文B",
            "like_count": 900,
            "collect_count": 450,
            "is_video": True,
            "video_url": "https://evil.example/stream/2",
            "duration_sec": 30,
        },
        {"id": "c" * 24, "title": "图文", "like_count": 99999, "is_video": False},
        {
            "id": "d" * 24,
            "title": "太长",
            "like_count": 1,
            "is_video": True,
            "duration_sec": 600,
        },
    ]
    result, receipt = run_page("xiaohongshu", rows)
    assert [item["title"] for item in result["items"]] == ["多赞", "少赞"]
    assert result["skip_reasons"] == {"not_video": 1, "longer_than_300s": 1}
    top = result["items"][0]
    assert top["collect_like_ratio"] == 0.5 and top["platform"] == "xiaohongshu"
    assert "video_url" not in str(result) and "xhscdn.com/stream" not in str(result)
    assert receipt["media_urls"] == {
        "a" * 24: "https://sns-video-v6.xhscdn.com/stream/1"
    }
    assert result["platform"] == "xiaohongshu" and result["sort"] == "most_liked"


def test_bilibili_favorites_count_as_collects_and_views_are_real():
    rows = [
        {
            "id": "BV1nPczeqED6",
            "title": "大糙手爆改",
            "text": "",
            "like_count": 8913,
            "favorite_count": 13730,
            "view_count": 531858,
            "thumbnail_url": "https://i2.hdslb.com/x.jpg",
            "duration_seconds": 36,
            "author_name": "作者",
        }
    ]
    result, _ = run_page("bilibili", rows)
    (item,) = result["items"]
    assert item["collect_count"] == 13730 and item["view_count"] == 531858
    assert item["source_url"] == "https://www.bilibili.com/video/BV1nPczeqED6"
    assert (
        item["cover_url"] == "https://i2.hdslb.com/x.jpg"
        and item["duration_seconds"] == 36
    )


def test_performance_readings_follow_teardown_thresholds():
    notes = platforms.performance(
        {
            "collect_like_ratio": 0.73,
            "share_like_ratio": 0.13,
            "comment_like_ratio": 0.01,
        }
    )
    assert any("干货收藏型" in n for n in notes) and any("转发" in n for n in notes)
    assert platforms.performance({"collect_like_ratio": None}) == []


def reference(metrics=True):
    text = (
        "这也太吓人了。经常玩手机的宝赶紧看看你的手。分享个低成本的方法。"
        "先用温水泡三分钟。关注我，下期教你按摩。"
    )
    return WritingReference(
        reference_id=uuid4(),
        original_text=text,
        sentences=sentence_units(text),
        source_metrics=SourceMetrics(
            platform="bilibili", like_count=100, collect_count=60
        )
        if metrics
        else None,
    )


def analysis_body(ref):
    ids = [s.id for s in ref.sentences]
    return {
        "topic": "手部护理",
        "hook_sentence_ids": [ids[0]],
        "sections": [
            {
                "id": "s1",
                "first_sentence_id": ids[0],
                "last_sentence_id": ids[1],
                "function": "痛点引入",
                "explanation": "先吓一跳",
                "technique": "第二人称直呼",
                "emotion": "焦虑",
            },
            {
                "id": "s2",
                "first_sentence_id": ids[2],
                "last_sentence_id": ids[4],
                "function": "方法+互动",
                "explanation": "给方法再要关注",
            },
        ],
        "reusable_structure": ["痛点→方法→关注"],
        "limitations": ["只分析文字"],
        "hook": {
            "sentence_ids": [ids[0]],
            "type": "情绪共鸣",
            "technique": "惊叹开场",
            "why": "制造紧张",
        },
        "expressions": [
            {
                "name": "直呼",
                "sentence_id": ids[1],
                "quote": "赶紧看看你的手",
                "effect": "拉近",
                "how_to_reuse": "换成你的人群",
            },
            {
                "name": "编造",
                "sentence_id": ids[1],
                "quote": "原文里没有这句",
                "effect": "x",
                "how_to_reuse": "x",
            },
        ],
        "conversion": [
            {"sentence_id": ids[4], "kind": "关注", "note": "预告下期"},
            {"sentence_id": "r9999", "kind": "评论", "note": "x"},
        ],
        "replace_slots": [
            {
                "id": "p1",
                "category": "product",
                "sentence_id": ids[3],
                "source_quote": "温水泡三分钟",
                "label": "使用方法",
                "question": "你的产品怎么用？",
            },
            {
                "id": "p2",
                "category": "product",
                "sentence_id": ids[3],
                "source_quote": "不存在",
                "label": "x",
                "question": "x",
            },
        ],
        "why_hot": ["收藏/点赞 60%，属于干货收藏"],
    }


def test_sanitizer_drops_uncited_rows_and_unbacked_reasons():
    ref = reference()
    parsed = WritingAnalysis.model_validate(analysis_body(ref))
    sanitize_analysis(parsed, ref)
    validate_analysis(parsed, ref)
    assert [e.name for e in parsed.expressions] == ["直呼"]
    assert len(parsed.conversion) == 1 and [s.id for s in parsed.replace_slots] == [
        "p1"
    ]
    assert (
        parsed.interaction_analysis == "public_counts"
        and parsed.schema_version.endswith("/2")
    )

    bare = reference(metrics=False)
    parsed = WritingAnalysis.model_validate(analysis_body(bare))
    sanitize_analysis(parsed, bare)
    assert parsed.why_hot == [] and parsed.interaction_analysis == "not_provided"


def test_old_analysis_documents_still_load():
    ref = reference()
    body = analysis_body(ref)
    old = {
        key: body[key]
        for key in ("topic", "hook_sentence_ids", "reusable_structure", "limitations")
    }
    old["sections"] = [
        {k: v for k, v in s.items() if k not in {"technique", "emotion"}}
        for s in body["sections"]
    ]
    parsed = WritingAnalysis.model_validate(
        {"schema_version": "tengli.writing-analysis/1", **old}
    )
    assert parsed.hook is None and parsed.expressions == []
