"""Benchmark covers served from our own origin.

The site's CSP only allows its own images, and the platforms' CDNs check the
referer and sign their links with an expiry. So a cover is fetched server-side
(allow-listed hosts only), kept in a small cache under the editing task dir,
and served same-origin. Search pages pre-fetch their covers right away, while
the signed links are still valid.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .config import Settings

logger = logging.getLogger(__name__)
HOSTS = (
    ".douyinpic.com",
    ".xhscdn.com",
    ".rednotecdn.com",
    ".hdslb.com",
    ".byteimg.com",
)
MAX_BYTES = 3 * 1024 * 1024
# Tests inject a mock transport here; production uses the network.
TRANSPORT: httpx.BaseTransport | None = None
TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
}


def cache_dir(settings: Settings) -> Path:
    return Path(settings.video_editing_tasks_dir) / "_benchmark_covers"


def key(task_id: str, platform_id: str) -> str:
    return hashlib.sha256(f"{task_id}:{platform_id}".encode()).hexdigest()[:40]


def cached(
    settings: Settings, task_id: str, platform_id: str
) -> tuple[Path, str] | None:
    base = cache_dir(settings)
    for content_type, suffix in TYPES.items():
        path = base / (key(task_id, platform_id) + suffix)
        if path.is_file():
            return path, content_type
    return None


def allowed(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and not parts.username and host.endswith(HOSTS)


def fetch(
    settings: Settings, task_id: str, platform_id: str, url: str
) -> tuple[Path, str] | None:
    """Download one cover into the cache; None when it cannot be had."""
    if not allowed(url):
        return None
    hit = cached(settings, task_id, platform_id)
    if hit:
        return hit
    try:
        with httpx.Client(
            timeout=httpx.Timeout(10, connect=5),
            follow_redirects=False,
            transport=TRANSPORT,
        ) as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
    except httpx.HTTPError:
        return None
    content_type = (
        response.headers.get("content-type", "").split(";")[0].strip().lower()
    )
    if response.status_code != 200 or len(response.content) > MAX_BYTES:
        return None
    body = response.content
    if content_type in {"image/heic", "image/heif"}:
        # 抖音 serves HEIC covers, which browsers outside Safari cannot show.
        body, content_type = to_jpeg(settings, body), "image/jpeg"
    if not body or content_type not in TYPES:
        return None
    base = cache_dir(settings)
    base.mkdir(parents=True, exist_ok=True)
    path = base / (key(task_id, platform_id) + TYPES[content_type])
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(body)
    tmp.replace(path)
    return path, content_type


def to_jpeg(settings: Settings, heic: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="cover-") as work:
        source, target = Path(work) / "in.heic", Path(work) / "out.jpg"
        source.write_bytes(heic)
        try:
            done = subprocess.run(
                [
                    str(settings.video_editing_ffmpeg or "ffmpeg"),
                    "-nostdin",
                    "-v",
                    "error",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=min(720\\,iw):-2",
                    "-q:v",
                    "4",
                    "-y",
                    str(target),
                ],
                capture_output=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return b""
        return target.read_bytes() if done.returncode == 0 and target.is_file() else b""


def prefetch(settings: Settings, task_id: str, items: list[dict[str, Any]]) -> None:
    """Best effort, right after a search page completes."""
    work = [(i["platform_id"], i["cover_url"]) for i in items if i.get("cover_url")]
    if not work:
        return
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(
                pool.map(lambda pair: fetch(settings, task_id, pair[0], pair[1]), work)
            )
    except Exception:  # noqa: BLE001 - covers are decoration; never fail the search
        logger.warning("benchmark cover prefetch failed", extra={"task_id": task_id})
