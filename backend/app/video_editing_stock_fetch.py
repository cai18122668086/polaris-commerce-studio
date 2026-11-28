"""Server-side download of stock media into a bounded, clearable cache.

* Every hop (including redirects) must be https on the provider's allow-list.
* Size caps: images 15 MB, videos 80 MB; streamed, aborted when exceeded.
* Images are decoded and re-encoded to JPEG (≤2160 px long side, no EXIF).
* Videos are transcoded to H.264/yuv420p MP4, ≤1080×1920 box, ≤15 s, ≤30 fps,
  no audio track (narration stays the presenter's).
* Cache: ``<video_stock_cache_dir>/media``; least-recently-used entries are
  evicted above ``video_stock_cache_max_bytes``. ``python -m
  app.video_editing_stock_fetch --clear`` empties it in one go.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import subprocess
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from .config import Settings
from .video_editing_stock_sources import USER_AGENT, Candidate, allowed_url

IMAGE_LIMIT = 15 * 1024 * 1024
VIDEO_LIMIT = 80 * 1024 * 1024
THUMB_LIMIT = 2 * 1024 * 1024
MAX_REDIRECTS = 4
MAX_VIDEO_SECONDS = 6  # b-roll length; long clips dominated the cut
Image.MAX_IMAGE_PIXELS = 80_000_000


class FetchError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def cache_root(settings: Settings) -> Path:
    return settings.video_stock_cache_dir or (
        settings.video_editing_tasks_dir / "stock-cache"
    )


def media_dir(settings: Settings) -> Path:
    return cache_root(settings) / "media"


def download(
    provider: str,
    url: str,
    limit: int,
    *,
    client: httpx.Client | None = None,
) -> tuple[bytes, str]:
    own = client is None
    client = client or httpx.Client()
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not allowed_url(provider, url):
                raise FetchError("STOCK_HOST_NOT_ALLOWED")
            with client.stream(
                "GET",
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    url = str(response.url.join(location))
                    continue
                if response.status_code != 200:
                    raise FetchError("STOCK_DOWNLOAD_FAILED")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > limit:
                    raise FetchError("STOCK_TOO_LARGE")
                chunks, size = [], 0
                for chunk in response.iter_bytes(256 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise FetchError("STOCK_TOO_LARGE")
                    chunks.append(chunk)
                return b"".join(chunks), response.headers.get("content-type", "")
        raise FetchError("STOCK_TOO_MANY_REDIRECTS")
    except httpx.HTTPError as error:
        raise FetchError("STOCK_DOWNLOAD_FAILED") from error
    finally:
        if own:
            client.close()


def normalise_image(payload: bytes) -> tuple[bytes, int, int]:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP"):
                raise FetchError("STOCK_FORMAT")
            rgb = ImageOps.exif_transpose(image).convert("RGB")
            rgb.thumbnail((2160, 2160))
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=90, optimize=True)
            return out.getvalue(), rgb.width, rgb.height
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise FetchError("STOCK_FORMAT") from error


def transcode_video(settings: Settings, source: Path, target: Path) -> None:
    command = [
        settings.video_editing_ffmpeg,
        "-v",
        "error",
        "-y",
        "-i",
        str(source),
        "-t",
        str(MAX_VIDEO_SECONDS),
        "-an",
        "-vf",
        "scale=w='min(1080,iw)':h='min(1920,ih)':force_original_aspect_ratio=decrease,"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps='min(30,source_fps)'",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(target),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=240)
    except (subprocess.SubprocessError, OSError) as error:
        target.unlink(missing_ok=True)
        raise FetchError("STOCK_TRANSCODE_FAILED") from error


def _entry(settings: Settings, candidate: Candidate) -> Path:
    digest = hashlib.sha256(
        f"{candidate.key}|{candidate.download_url}".encode()
    ).hexdigest()
    return media_dir(settings) / digest[:2] / digest


def fetch_media(
    settings: Settings, candidate: Candidate, *, client: httpx.Client | None = None
) -> tuple[Path, str, int, int]:
    """Cached, normalised local file for a candidate → (path, mime, w, h)."""
    entry = _entry(settings, candidate)
    name = "media.jpg" if candidate.kind == "image" else "media.mp4"
    final = entry / name
    if final.is_file():
        os.utime(final)
        if candidate.kind == "image":
            with Image.open(final) as image:
                return final, "image/jpeg", image.width, image.height
        return final, "video/mp4", candidate.width, candidate.height
    entry.mkdir(parents=True, exist_ok=True)
    try:
        if candidate.kind == "image":
            payload, _ = download(
                candidate.provider, candidate.download_url, IMAGE_LIMIT, client=client
            )
            data, width, height = normalise_image(payload)
            tmp = entry / ".media.jpg"
            tmp.write_bytes(data)
            tmp.replace(final)
            result = (final, "image/jpeg", width, height)
        else:
            payload, mime = download(
                candidate.provider, candidate.download_url, VIDEO_LIMIT, client=client
            )
            if not (mime.startswith("video/") or mime == "application/octet-stream"):
                raise FetchError("STOCK_FORMAT")
            raw = entry / ".raw"
            raw.write_bytes(payload)
            try:
                tmp = entry / ".media.mp4"
                transcode_video(settings, raw, tmp)
                tmp.replace(final)
            finally:
                raw.unlink(missing_ok=True)
            result = (final, "video/mp4", candidate.width, candidate.height)
    except BaseException:
        shutil.rmtree(entry, ignore_errors=True)
        raise
    evict(settings)
    return result


def fetch_thumb(
    settings: Settings, provider: str, url: str, *, client: httpx.Client | None = None
) -> bytes:
    digest = hashlib.sha256(f"{provider}|{url}".encode()).hexdigest()
    path = cache_root(settings) / "thumbs" / digest[:2] / f"{digest}.jpg"
    if path.is_file():
        os.utime(path)
        return path.read_bytes()
    payload, _ = download(provider, url, THUMB_LIMIT, client=client)
    try:
        with Image.open(io.BytesIO(payload)) as image:
            rgb = ImageOps.exif_transpose(image).convert("RGB")
            rgb.thumbnail((480, 480))
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=82)
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise FetchError("STOCK_FORMAT") from error
    data = out.getvalue()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        pass
    return data


def usage(settings: Settings) -> tuple[int, list[tuple[float, int, Path]]]:
    rows: list[tuple[float, int, Path]] = []
    total = 0
    root = cache_root(settings)
    if not root.exists():
        return 0, rows
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            total += stat.st_size
            rows.append((stat.st_mtime, stat.st_size, path))
    return total, rows


def evict(settings: Settings) -> int:
    """Delete least-recently-used files until under the cap. Returns bytes freed."""
    cap = settings.video_stock_cache_max_bytes
    total, rows = usage(settings)
    freed = 0
    for _, size, path in sorted(rows):
        if total - freed <= cap:
            break
        path.unlink(missing_ok=True)
        freed += size
        if path.name.startswith("media.") and not any(path.parent.iterdir()):
            path.parent.rmdir()
    return freed


def clear(settings: Settings) -> int:
    total, _ = usage(settings)
    shutil.rmtree(cache_root(settings), ignore_errors=True)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="补充素材下载缓存")
    parser.add_argument("--clear", action="store_true", help="清空缓存")
    args = parser.parse_args()
    settings = Settings()
    if args.clear:
        print(f"已清理 {clear(settings)} 字节")
    else:
        total, rows = usage(settings)
        cap = settings.video_stock_cache_max_bytes
        print(f"{len(rows)} 个文件，{total} 字节，上限 {cap}")


if __name__ == "__main__":
    main()
