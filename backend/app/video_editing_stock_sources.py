"""Free stock-media sources for supplement materials (W4, v3).

Every source is searched server-side only; the browser never talks to a stock
site (site CSP allows only our own domain). Each normalised candidate carries
its provider, page URL, author and licence so an imported material records
where it came from.

* Pexels / Pixabay need a free API key. Keys are read from server files
  (``video_stock_*_key_file``); a missing or empty file turns that source off
  and the panel says「暂未开通」. Keys are never logged or returned.
* Openverse (CC0 / CC BY only) and Wikimedia Commons need no key. They are the
  fallback when no key is installed; when the server is refused (HTTP 403 /
  bot challenge) the source is marked unavailable for a while instead of
  failing the whole search.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from .config import Settings

Provider = Literal["pexels", "pixabay", "openverse", "commons"]
Kind = Literal["image", "video"]
PROVIDERS: tuple[Provider, ...] = ("pexels", "pixabay", "openverse", "commons")
LABELS = {
    "pexels": "Pexels",
    "pixabay": "Pixabay",
    "openverse": "Openverse",
    "commons": "维基共享资源",
}
USER_AGENT = "PolarisVideoMaterials/1.0 (server-side stock search)"
SEARCH_TIMEOUT = 12.0
UNAVAILABLE_SECONDS = 600
SEARCH_TTL_SECONDS = 24 * 3600  # Pixabay asks API results to be cached 24h.

# Download hosts per provider: every redirect hop must stay inside the set.
HOSTS: dict[str, frozenset[str]] = {
    "pexels": frozenset({"images.pexels.com", "videos.pexels.com"}),
    "pixabay": frozenset({"pixabay.com", "cdn.pixabay.com"}),
    "openverse": frozenset(
        {"api.openverse.org", "upload.wikimedia.org", "live.staticflickr.com"}
    ),
    "commons": frozenset({"upload.wikimedia.org"}),
}
OPENVERSE_LICENSES = {"cc0": "CC0 1.0", "by": "CC BY"}
COMMONS_LICENSES = re.compile(r"^(cc0|public domain|cc by( \d\.\d)?)$", re.I)


@dataclass(frozen=True)
class Candidate:
    provider: Provider
    provider_ref: str
    kind: Kind
    width: int
    height: int
    duration_ms: int | None
    thumb_url: str
    download_url: str
    page_url: str
    author: str
    author_url: str | None
    license: str
    license_url: str
    attribution: str | None = None
    title: str | None = None

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.kind}:{self.provider_ref}"

    def public(self) -> dict[str, Any]:
        """Card for the browser: no remote URLs (thumbs go through our proxy)."""
        return {
            "key": self.key,
            "provider": self.provider,
            "provider_label": LABELS[self.provider],
            "kind": self.kind,
            "width": self.width,
            "height": self.height,
            "duration_ms": self.duration_ms,
            "author": self.author,
            "license": self.license,
            "license_url": self.license_url,
            "page_url": self.page_url,
            "attribution": self.attribution,
        }

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> Candidate:
        return cls(**value)


@dataclass
class SourceState:
    provider: Provider
    available: bool
    reason: str | None = None


@dataclass
class _Health:
    blocked_until: dict[str, float] = field(default_factory=dict)
    healthy_until: dict[str, float] = field(default_factory=dict)


_health = _Health()


def read_key(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        value = path.read_text("utf-8").strip()
    except OSError:
        return None
    return value if re.fullmatch(r"[A-Za-z0-9_\-]{8,128}", value) else None


def keys(settings: Settings) -> dict[str, str]:
    found = {
        "pexels": read_key(settings.video_stock_pexels_key_file),
        "pixabay": read_key(settings.video_stock_pixabay_key_file),
    }
    return {name: key for name, key in found.items() if key}


def states(settings: Settings, now: float | None = None) -> list[SourceState]:
    now = time.monotonic() if now is None else now
    installed = keys(settings)
    rows: list[SourceState] = []
    for provider in PROVIDERS:
        if provider in ("pexels", "pixabay"):
            ok = provider in installed
            reason = None if ok else "暂未开通"
        else:
            enabled = (
                settings.video_stock_openverse_enabled
                if provider == "openverse"
                else settings.video_stock_commons_enabled
            )
            ok, reason = enabled, None if enabled else "暂未开通"
        if ok and _health.blocked_until.get(provider, 0) > now:
            ok, reason = False, "暂时无法访问"
        rows.append(SourceState(provider, ok, reason))
    return rows


def active(settings: Settings) -> list[Provider]:
    return [row.provider for row in states(settings) if row.available]


def allowed_url(provider: str, url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.hostname in HOSTS.get(provider, frozenset())
            and not parts.username
            and not parts.password
            and parts.port in (None, 443)
        )
    except ValueError:
        return False


def _mark_blocked(provider: str) -> None:
    _health.blocked_until[provider] = time.monotonic() + UNAVAILABLE_SECONDS


PROBES: dict[str, tuple[str, dict[str, str | int]]] = {
    "openverse": ("https://api.openverse.org/v1/images/", {"q": "tea", "page_size": 1}),
    "commons": (
        "https://commons.wikimedia.org/w/api.php",
        {"action": "query", "format": "json", "meta": "siteinfo"},
    ),
}
HEALTHY_SECONDS = 1800


def probe_fallbacks(settings: Settings, *, client: httpx.Client | None = None) -> None:
    """One cheap request per keyless source not checked recently (4 s cap).

    A refusal (403 / bot challenge) marks the source「暂时无法访问」before the
    user opens it, instead of failing their first search.
    """
    now = time.monotonic()
    enabled = {
        "openverse": settings.video_stock_openverse_enabled,
        "commons": settings.video_stock_commons_enabled,
    }
    own = client is None
    client = client or httpx.Client()
    try:
        for provider, (url, params) in PROBES.items():
            if not enabled[provider]:
                continue
            if _health.healthy_until.get(provider, 0) > now:
                continue
            if _health.blocked_until.get(provider, 0) > now:
                continue
            try:
                response = client.get(
                    url,
                    params=params,
                    headers={"User-Agent": USER_AGENT},
                    timeout=4.0,
                    follow_redirects=False,
                )
                ok = response.status_code == 200 and "json" in response.headers.get(
                    "content-type", ""
                )
            except httpx.HTTPError:
                ok = False
            if ok:
                _health.healthy_until[provider] = now + HEALTHY_SECONDS
            else:
                _mark_blocked(provider)
    finally:
        if own:
            client.close()


# ---------------------------------------------------------------- parsing


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and value > 0 else 0


def parse_pexels_photos(data: dict) -> list[Candidate]:
    rows = []
    for item in data.get("photos") or []:
        src = item.get("src") or {}
        download = src.get("large2x") or src.get("original")
        thumb = src.get("medium") or src.get("small")
        if not (download and thumb and item.get("id")):
            continue
        rows.append(
            Candidate(
                provider="pexels",
                provider_ref=str(item["id"]),
                kind="image",
                width=_int(item.get("width")),
                height=_int(item.get("height")),
                duration_ms=None,
                thumb_url=thumb,
                download_url=download,
                page_url=str(item.get("url") or "https://www.pexels.com/"),
                author=str(item.get("photographer") or "Pexels 作者"),
                author_url=item.get("photographer_url"),
                license="Pexels License（可免费商用，无需署名）",
                license_url="https://www.pexels.com/license/",
                title=item.get("alt") or None,
            )
        )
    return rows


def _best_file(files: list[dict], width_key: str = "width") -> dict | None:
    usable = [
        row
        for row in files
        if row.get("link" if "link" in row else "url")
        and _int(row.get(width_key))
        and (row.get("file_type") in (None, "video/mp4"))
    ]
    if not usable:
        return None

    def score(row: dict) -> tuple[int, int]:
        short = min(_int(row.get("width")), _int(row.get("height")) or 10**6)
        # Closest to 1080 on the short side, never far above it.
        return (abs(short - 1080) + (2000 if short > 1440 else 0), -short)

    return min(usable, key=score)


def parse_pexels_videos(data: dict) -> list[Candidate]:
    rows = []
    for item in data.get("videos") or []:
        chosen = _best_file(item.get("video_files") or [])
        if not chosen or not item.get("id") or not item.get("image"):
            continue
        user = item.get("user") or {}
        rows.append(
            Candidate(
                provider="pexels",
                provider_ref=str(item["id"]),
                kind="video",
                width=_int(chosen.get("width")),
                height=_int(chosen.get("height")),
                duration_ms=_int(item.get("duration")) * 1000 or None,
                thumb_url=item["image"],
                download_url=chosen["link"],
                page_url=str(item.get("url") or "https://www.pexels.com/"),
                author=str(user.get("name") or "Pexels 作者"),
                author_url=user.get("url"),
                license="Pexels License（可免费商用，无需署名）",
                license_url="https://www.pexels.com/license/",
            )
        )
    return rows


def parse_pixabay_photos(data: dict) -> list[Candidate]:
    rows = []
    for item in data.get("hits") or []:
        download = item.get("largeImageURL") or item.get("webformatURL")
        thumb = item.get("webformatURL") or item.get("previewURL")
        if not (download and thumb and item.get("id")):
            continue
        rows.append(
            Candidate(
                provider="pixabay",
                provider_ref=str(item["id"]),
                kind="image",
                width=_int(item.get("imageWidth")),
                height=_int(item.get("imageHeight")),
                duration_ms=None,
                thumb_url=thumb,
                download_url=download,
                page_url=str(item.get("pageURL") or "https://pixabay.com/"),
                author=str(item.get("user") or "Pixabay 作者"),
                author_url=None,
                license="Pixabay Content License（可免费商用，无需署名）",
                license_url="https://pixabay.com/service/license-summary/",
                title=item.get("tags") or None,
            )
        )
    return rows


def parse_pixabay_videos(data: dict) -> list[Candidate]:
    rows = []
    for item in data.get("hits") or []:
        variants = item.get("videos") or {}
        files = [
            {**value, "link": value.get("url"), "name": name}
            for name, value in variants.items()
            if isinstance(value, dict)
        ]
        chosen = _best_file(files)
        thumb = (chosen or {}).get("thumbnail") or next(
            (row.get("thumbnail") for row in files if row.get("thumbnail")), None
        )
        if not chosen or not thumb or not item.get("id"):
            continue
        rows.append(
            Candidate(
                provider="pixabay",
                provider_ref=str(item["id"]),
                kind="video",
                width=_int(chosen.get("width")),
                height=_int(chosen.get("height")),
                duration_ms=_int(item.get("duration")) * 1000 or None,
                thumb_url=thumb,
                download_url=chosen["link"],
                page_url=str(item.get("pageURL") or "https://pixabay.com/"),
                author=str(item.get("user") or "Pixabay 作者"),
                author_url=None,
                license="Pixabay Content License（可免费商用，无需署名）",
                license_url="https://pixabay.com/service/license-summary/",
            )
        )
    return rows


def parse_openverse(data: dict) -> list[Candidate]:
    rows = []
    for item in data.get("results") or []:
        code = str(item.get("license") or "").lower()
        if code not in OPENVERSE_LICENSES:
            continue
        url, thumb = item.get("url"), item.get("thumbnail")
        if not (url and thumb and item.get("id")):
            continue
        if not allowed_url("openverse", url):
            continue
        version = item.get("license_version") or ""
        rows.append(
            Candidate(
                provider="openverse",
                provider_ref=str(item["id"]),
                kind="image",
                width=_int(item.get("width")),
                height=_int(item.get("height")),
                duration_ms=None,
                thumb_url=thumb,
                download_url=url,
                page_url=str(item.get("foreign_landing_url") or url),
                author=str(item.get("creator") or "佚名"),
                author_url=item.get("creator_url"),
                license=f"{OPENVERSE_LICENSES[code]} {version}".strip(),
                license_url=str(
                    item.get("license_url")
                    or "https://creativecommons.org/licenses/by/4.0/"
                ),
                attribution=item.get("attribution"),
                title=item.get("title"),
            )
        )
    return rows


def _plain(html: str | None) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def parse_commons(data: dict) -> list[Candidate]:
    rows = []
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        short = _plain((meta.get("LicenseShortName") or {}).get("value"))
        if not COMMONS_LICENSES.match(short):
            continue
        url, thumb = info.get("url"), info.get("thumburl")
        if not (url and thumb) or not allowed_url("commons", url):
            continue
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        author = _plain((meta.get("Artist") or {}).get("value")) or "佚名"
        rows.append(
            Candidate(
                provider="commons",
                provider_ref=str(page.get("pageid")),
                kind="image",
                width=_int(info.get("width")),
                height=_int(info.get("height")),
                duration_ms=None,
                thumb_url=thumb,
                download_url=url,
                page_url=str(info.get("descriptionurl") or url),
                author=author[:120],
                author_url=None,
                license=short,
                license_url=_plain((meta.get("LicenseUrl") or {}).get("value"))
                or "https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia",
                attribution=f"{author[:80]} / {short} / Wikimedia Commons",
                title=page.get("title"),
            )
        )
    return rows


# ---------------------------------------------------------------- search


def _cache_dir(settings: Settings) -> Path:
    root = settings.video_stock_cache_dir or (
        settings.video_editing_tasks_dir / "stock-cache"
    )
    return root / "search"


def _cached(settings: Settings, name: str) -> list[Candidate] | None:
    path = _cache_dir(settings) / f"{name}.json"
    try:
        if time.time() - path.stat().st_mtime > SEARCH_TTL_SECONDS:
            return None
        return [Candidate.from_json(row) for row in json.loads(path.read_text())]
    except (OSError, ValueError, TypeError):
        return None


def _store(settings: Settings, name: str, rows: list[Candidate]) -> None:
    folder = _cache_dir(settings)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{name}.tmp"
        tmp.write_text(json.dumps([row.to_json() for row in rows], ensure_ascii=False))
        tmp.replace(folder / f"{name}.json")
    except OSError:
        pass


def _request(
    client: httpx.Client, provider: str, url: str, params: dict, headers: dict
) -> dict | None:
    try:
        response = client.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, **headers},
            timeout=SEARCH_TIMEOUT,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        return None
    if response.status_code in (401, 403, 429) or (
        response.status_code == 200
        and "json" not in response.headers.get("content-type", "")
    ):
        _mark_blocked(provider)
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def search_provider(
    settings: Settings,
    provider: Provider,
    query: str,
    kind: Kind,
    *,
    per_page: int = 6,
    client: httpx.Client | None = None,
) -> list[Candidate]:
    query = re.sub(r"\s+", " ", query).strip()[:80]
    if not query or provider not in active(settings):
        return []
    if kind == "video" and provider in ("openverse", "commons"):
        return []
    name = hashlib.sha256(f"{provider}|{kind}|{per_page}|{query}".encode()).hexdigest()[
        :32
    ]
    if (hit := _cached(settings, name)) is not None:
        return hit
    secret = keys(settings).get(provider, "")
    own = client is None
    client = client or httpx.Client()
    try:
        if provider == "pexels":
            url = (
                "https://api.pexels.com/videos/search"
                if kind == "video"
                else "https://api.pexels.com/v1/search"
            )
            data = _request(
                client,
                provider,
                url,
                {
                    "query": query,
                    "per_page": per_page,
                    "orientation": "portrait",
                    "locale": "zh-CN",
                },
                {"Authorization": secret},
            )
            rows = (
                (parse_pexels_videos if kind == "video" else parse_pexels_photos)(data)
                if data
                else []
            )
        elif provider == "pixabay":
            url = (
                "https://pixabay.com/api/videos/"
                if kind == "video"
                else "https://pixabay.com/api/"
            )
            params = {
                "key": secret,
                "q": query,
                "lang": "zh",
                "safesearch": "true",
                "per_page": max(3, per_page),
            }
            if kind == "image":
                params.update(image_type="photo", orientation="vertical")
            data = _request(client, provider, url, params, {})
            rows = (
                (parse_pixabay_videos if kind == "video" else parse_pixabay_photos)(
                    data
                )
                if data
                else []
            )
        elif provider == "openverse":
            data = _request(
                client,
                provider,
                "https://api.openverse.org/v1/images/",
                {
                    "q": query,
                    "license": "cc0,by",
                    "page_size": per_page,
                    "mature": "false",
                },
                {},
            )
            rows = parse_openverse(data) if data else []
        else:
            data = _request(
                client,
                provider,
                "https://commons.wikimedia.org/w/api.php",
                {
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": f"{query} filetype:bitmap",
                    "gsrnamespace": 6,
                    "gsrlimit": per_page,
                    "prop": "imageinfo",
                    "iiprop": "url|size|extmetadata|mime",
                    "iiurlwidth": 480,
                },
                {},
            )
            rows = parse_commons(data) if data else []
    finally:
        if own:
            client.close()
    rows = [
        row
        for row in rows
        if allowed_url(provider, row.download_url) and row.width and row.height
    ]
    _store(settings, name, rows)
    return rows


def _words(text: str | None) -> set[str]:
    return {
        w
        for w in re.split(r"[^0-9a-z\u4e00-\u9fff]+", (text or "").lower())
        if len(w) > 2
    }


def rank(rows: list[Candidate], queries: list[str] | None = None) -> list[Candidate]:
    """Relevance (query words found in the item's tags/title), then portrait,
    enough resolution, video, provider order."""
    wanted = set().union(*(_words(q) for q in queries or [])) if queries else set()

    def score(row: Candidate) -> tuple:
        portrait = row.height >= row.width
        short = min(row.width, row.height)
        hits = len(wanted & _words(row.title)) if wanted else 0
        return (
            -hits,
            0 if portrait else 1,
            0 if short >= 720 else 1,
            0 if row.kind == "video" else 1,
            PROVIDERS.index(row.provider),
        )

    seen: set[str] = set()
    ordered = []
    for row in sorted(rows, key=score):
        if row.key not in seen:
            seen.add(row.key)
            ordered.append(row)
    return ordered


def search_sentence(
    settings: Settings,
    queries: list[str],
    *,
    want_video: bool = True,
    limit: int = 3,
    client: httpx.Client | None = None,
) -> list[Candidate]:
    """Up to ``limit`` candidates for one sentence across active providers."""
    found: list[Candidate] = []
    providers = active(settings)
    for query in queries[:3]:
        for provider in providers:
            kinds: tuple[Kind, ...] = ("video", "image") if want_video else ("image",)
            for kind in kinds:
                found.extend(
                    search_provider(
                        settings, provider, query, kind, per_page=4, client=client
                    )
                )
            if len(found) >= limit * 3:
                break
        if len(found) >= limit:
            break
    return rank(found, queries)[:limit]
