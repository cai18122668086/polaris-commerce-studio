"""Per-platform contracts for 爆款对标: search, pasted links, details, transcripts.

Every search asks the supplier for the most-liked ordering and the page is
re-sorted by public like count, so the order shown is never "relevance".
Signed media URLs stay server-side (receipt only); public results carry the
canonical post link and display fields.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

import httpx

from .errors import ApiError

Platform = Literal["douyin", "xiaohongshu", "bilibili"]
PLATFORMS: tuple[Platform, ...] = ("douyin", "xiaohongshu", "bilibili")
LABELS: dict[str, str] = {"douyin": "抖音", "xiaohongshu": "小红书", "bilibili": "B站"}
MAX_DURATION_SECONDS = 300
MAX_LINKS = 3
MOBILE_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
METRICS = ("like_count", "comment_count", "collect_count", "share_count")

DOUYIN_HOSTS = {"www.douyin.com", "douyin.com", "www.iesdouyin.com", "m.douyin.com"}
XHS_HOSTS = {"www.xiaohongshu.com", "xiaohongshu.com"}
BILI_HOSTS = {"www.bilibili.com", "bilibili.com", "m.bilibili.com"}
SHORT_HOSTS = {
    "v.douyin.com": "douyin",
    "xhslink.com": "xiaohongshu",
    "b23.tv": "bilibili",
}
ID_PATTERNS: dict[str, str] = {
    "douyin": r"[0-9]{6,25}",
    "xiaohongshu": r"[0-9a-f]{24}",
    "bilibili": r"BV[0-9A-Za-z]{10}",
}
# Hosts a signed short-video file may be downloaded from for our own ASR.
MEDIA_HOST_SUFFIXES = (".xhscdn.com", ".rednotecdn.com", ".xiaohongshu.com")


def label(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def count(value: Any) -> int | None:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def seconds(row: dict[str, Any]) -> float | None:
    for key in ("duration_seconds", "duration_sec"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                continue
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
        ):
            return float(value)
    if isinstance(row.get("duration_ms"), int) and row["duration_ms"] > 0:
        return row["duration_ms"] / 1000
    return None


def https_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith("http://"):
        value = "https://" + value[len("http://") :]
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        return None
    return value[:2048]


def invalid(message: str = "暂只支持抖音、小红书、B站的公开视频链接。") -> ApiError:
    return ApiError(422, "VIDEO_SOURCE_URL_INVALID", message)


def parse_post(url: str) -> tuple[Platform, str, str] | None:
    """(platform, id, canonical link) for a full post link; None for short links."""
    try:
        parts = urlsplit(url.strip())
        _ = parts.port
    except ValueError:
        raise invalid() from None
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"https", "http"} or parts.username or parts.password:
        raise invalid("链接不能包含账号信息。")
    if host in SHORT_HOSTS:
        return None
    if host in DOUYIN_HOSTS:
        selected = parse_qs(parts.query).get("modal_id", [])
        match = re.fullmatch(r"/(?:share/)?(?:video|note)/(\d{6,25})/?", parts.path)
        post = selected[0] if len(selected) == 1 else match[1] if match else None
        if post and re.fullmatch(ID_PATTERNS["douyin"], post):
            return "douyin", post, "https://www.douyin.com/video/" + post
        raise invalid("请粘贴具体的抖音视频链接。")
    if host in XHS_HOSTS:
        match = re.fullmatch(
            r"/(?:explore|discovery/item)/([0-9a-f]{24})/?", parts.path
        )
        if not match:
            raise invalid("请粘贴具体的小红书笔记链接。")
        token = parse_qs(parts.query).get("xsec_token", [""])[0]
        canonical = "https://www.xiaohongshu.com/explore/" + match[1]
        if re.fullmatch(r"[A-Za-z0-9_=+/-]{1,200}", token or ""):
            canonical += "?xsec_token=" + token
        return "xiaohongshu", match[1], canonical
    if host in BILI_HOSTS:
        match = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10})/?", parts.path)
        if not match:
            raise invalid("请粘贴具体的 B站视频链接（BV 号）。")
        return "bilibili", match[1], "https://www.bilibili.com/video/" + match[1]
    raise invalid()


def resolve_link(
    url: str, transport: httpx.BaseTransport | None = None
) -> tuple[Platform, str, str]:
    """Follow at most three redirects of a share short link to its post link."""
    for _ in range(4):
        parsed = parse_post(url)
        if parsed:
            return parsed
        host = (urlsplit(url).hostname or "").lower()
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10, connect=5),
                follow_redirects=False,
                transport=transport,
            ) as client:
                response = client.get(
                    "https://" + host + urlsplit(url).path,
                    headers={"User-Agent": MOBILE_AGENT},
                )
        except httpx.HTTPError:
            raise ApiError(
                502,
                "VIDEO_SOURCE_LINK_UNRESOLVED",
                "分享短链暂时打不开，请换成作品完整链接。",
            ) from None
        location = response.headers.get("location", "")
        if response.status_code not in {301, 302, 303, 307, 308} or not location:
            raise ApiError(
                422,
                "VIDEO_SOURCE_LINK_UNRESOLVED",
                "分享短链没有指向具体作品，请换成作品完整链接。",
            )
        url = location if location.startswith("http") else "https://" + host + location
    raise ApiError(
        422, "VIDEO_SOURCE_LINK_UNRESOLVED", "分享短链跳转过多，请换成作品完整链接。"
    )


def links_in(text: str) -> list[str]:
    """Links in pasted share text (「复制打开抖音… https://v.douyin.com/x/」)."""
    found = re.findall(
        r"https?://[A-Za-z0-9.-]+(?:/[^\s，。！？、；：“”‘’（）()<>【】\[\]]*)?", text
    )
    unique: list[str] = []
    for link in found:
        link = link.rstrip(".,!?;:'\"")
        if link not in unique:
            unique.append(link)
    return unique


def search_body(
    platform: str, keyword: str, page_token: str, publish_time: str = "unlimited"
) -> dict[str, Any]:
    if platform == "douyin":
        params: dict[str, Any] = {
            "keyword": keyword,
            "sort": "most_liked",
            "publish_time": publish_time,
            "page_token": page_token,
            "limit": 20,
        }
    elif platform == "xiaohongshu":
        params = {"keyword": keyword, "sort": "most_liked", "content_type": "video"}
    elif platform == "bilibili":
        params = {"keyword": keyword, "sort": "most_liked"}
    else:
        raise invalid()
    if page_token and platform != "douyin":
        params["page_token"] = page_token
    return {"platform": platform, "action": "search", "params": params}


def detail_body(platform: str, url: str) -> dict[str, Any]:
    action = "note" if platform == "xiaohongshu" else "video"
    return {"platform": platform, "action": action, "params": {"url": url}}


def drop_reason(platform: str, row: Any) -> str | None:
    if not isinstance(row, dict):
        return "not_object"
    post = row.get("id")
    if type(post) is int:
        post = str(post)
    if not isinstance(post, str) or not re.fullmatch(ID_PATTERNS[platform], post):
        return "invalid_id"
    if platform == "douyin" and row.get("media_type") not in {"video", None}:
        return "not_video"
    if platform == "xiaohongshu" and row.get("is_video") is False:
        return "not_video"
    duration = seconds(row)
    if duration is not None and duration > MAX_DURATION_SECONDS:
        return "longer_than_300s"
    return None


def ratio(part: int | None, likes: int | None) -> float | None:
    return part / likes if likes and part is not None else None


def candidate(
    platform: str, row: dict[str, Any], rank: int | None = None
) -> tuple[dict[str, Any], str | None]:
    """Public display fields, plus the signed media URL kept server-side only."""
    post = str(row["id"])
    if platform == "douyin":
        link = "https://www.douyin.com/video/" + post
        cover = row.get("cover_image_url")
    elif platform == "xiaohongshu":
        parsed = parse_post(row["url"]) if isinstance(row.get("url"), str) else None
        link = (
            parsed[2]
            if parsed and parsed[1] == post
            else "https://www.xiaohongshu.com/explore/" + post
        )
        images = row.get("images")
        first = images[0] if isinstance(images, list) and images else None
        if isinstance(first, dict):
            first = first.get("url")
        cover = row.get("image_url") or first
        if isinstance(cover, str):
            # The CDN serves HEIF by default, which browsers cannot show.
            cover = cover.replace("format/heif", "format/jpg")
    else:
        link = "https://www.bilibili.com/video/" + post
        cover = row.get("thumbnail_url")
    metrics = {key: count(row.get(key)) for key in METRICS}
    if platform == "bilibili":
        metrics["collect_count"] = count(row.get("favorite_count"))
    likes = metrics["like_count"]
    text = label(row.get("text"), 6000)
    title = label(row.get("title"), 200) or text.split("\n", 1)[0][:200]
    media = https_url(row.get("video_url")) if platform == "xiaohongshu" else None
    if media and not (urlsplit(media).hostname or "").endswith(MEDIA_HOST_SUFFIXES):
        media = None
    return {
        "platform": platform,
        "platform_id": post,
        "source_url": link,
        "title": title,
        "description": text,
        "cover_url": https_url(cover),
        "author_name": label(row.get("author_name"), 200) or None,
        "author_id": label(row.get("author_id"), 200) or None,
        "author_follower_count": count(
            row.get("author_follower_count", row.get("follower_count"))
        ),
        "posted_at": row.get("posted_at")
        if isinstance(row.get("posted_at"), str)
        else None,
        "duration_seconds": seconds(row),
        "search_rank": rank,
        **(
            {"view_count": count(row.get("view_count"))}
            if platform == "bilibili"
            else {}
        ),
        "media_status": "unverified",
        **metrics,
        "collect_like_ratio": ratio(metrics["collect_count"], likes),
        "share_like_ratio": ratio(metrics["share_count"], likes),
        "comment_like_ratio": ratio(metrics["comment_count"], likes),
    }, media


def by_likes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items, key=lambda item: (item["like_count"] is None, -(item["like_count"] or 0))
    )


def transcript_body(platform: str, url: str) -> dict[str, Any] | None:
    """Supplier transcript call; None means our own ASR (小红书)."""
    if platform == "douyin":
        return {
            "platform": "douyin",
            "action": "transcript",
            "params": {"url": url},
            "mode": "async",
        }
    if platform == "bilibili":
        return {"platform": "bilibili", "action": "subtitles", "params": {"url": url}}
    return None


def performance(item: dict[str, Any]) -> list[str]:
    """Deterministic reading of public counts; thresholds from the teardown method."""
    notes: list[str] = []
    collect, share, comment = (
        item.get(key)
        for key in ("collect_like_ratio", "share_like_ratio", "comment_like_ratio")
    )
    if collect is not None:
        if collect >= 0.4:
            notes.append(f"收藏/点赞 {collect:.0%}：干货收藏型，观众想存下来照着做")
        elif collect < 0.1:
            notes.append(f"收藏/点赞 {collect:.0%}：偏情绪或娱乐，靠共鸣拿赞")
    if share is not None and share >= 0.1:
        notes.append(f"分享/点赞 {share:.0%}：有转发价值，适合「发给需要的人」式结尾")
    if comment is not None and comment >= 0.05:
        notes.append(f"评论/点赞 {comment:.0%}：话题性强，评论区讨论多")
    return notes
