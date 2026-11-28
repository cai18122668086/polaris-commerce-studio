"""Render MG cues to transparent PNG frames in headless Chromium.

One browser per video; each cue gets its own page sized to its card box, the
anime.js timeline is seeked to the exact frame time (``n / fps``, fps taken
from the actual video) and the page is captured with a transparent
background. Fonts are the repository's OFL fonts, verified by SHA-256.
"""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .catalog import STYLES, box_size

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ANIME = BACKEND / "third_party" / "animejs" / "anime.umd.min.js"
ANIME_SHA256 = "8d5b3a58a1f64023a04a4cedeef135a2263b18da04b35177ac13438a0bad033b"
FONT_DIR = HERE.parent / "bihuo_suite/templates/fk-1104-know-white-capsule/fonts"
FONTS = {
    # 思源黑体 CN Bold / Noto Sans SC Medium — SIL Open Font License 1.1
    "MGTitle": (
        FONT_DIR / "62383707c086-思源黑体_CN_Bold--62383707c086.otf",
        "62383707c086a32f3afd5e293f34c7eff64c7fea31f579fdc6cbe34d920519a6",
    ),
    "MGBody": (
        FONT_DIR / "9c62ceb174d7-Noto_Sans_SC_Medium--9c62ceb174d7.otf",
        "9c62ceb174d7529ae4a7f2071f6531991cfadbc2f1897910b48ba951a580ac57",
    ),
}
RENDERER_VERSION = "mg-render/1"


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_resources() -> dict[str, str]:
    """Raise if anime.js or a font is missing/changed; return their digests."""
    found = {"anime.js": _sha(ANIME)}
    if found["anime.js"] != ANIME_SHA256:
        raise ValueError("anime.js changed")
    for family, (path, digest) in FONTS.items():
        found[family] = _sha(path)
        if found[family] != digest:
            raise ValueError(f"MG font changed: {family}")
    return found


def page_html(
    component: str,
    params: dict[str, Any],
    style: str,
    duration_ms: int,
    size: tuple[int, int],
) -> str:
    faces = "\n".join(
        f"@font-face{{font-family:{family};src:url('{path.as_uri()}')}}"
        for family, (path, _) in FONTS.items()
    )
    payload = {
        "component": component,
        "params": params,
        "style": STYLES[style],
        "duration_ms": int(duration_ms),
        "width": size[0],
        "height": size[1],
    }
    # JSON inside <script>: escape "</" so text can never close the tag.
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + faces
        + (HERE / "runtime.css").read_text("utf-8")
        + "</style></head><body><div id='mg'></div><script>"
        + ANIME.read_text("utf-8")
        + "</script><script>window.MG_INPUT="
        + data
        + ";</script><script>"
        + (HERE / "runtime.js").read_text("utf-8")
        + "</script></body></html>"
    )


@contextmanager
def browser() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as play:
        instance = play.chromium.launch(
            headless=True, args=["--allow-file-access-from-files", "--disable-gpu"]
        )
        try:
            yield instance
        finally:
            instance.close()


def render_cue(
    instance: Any,
    work: Path,
    component: str,
    params: dict[str, Any],
    style: str,
    frames: int,
    fps: float,
) -> list[Path]:
    """Write ``frames`` RGBA PNGs (frame 0 = cue start) and return their paths."""
    size = box_size(component, params)
    duration_ms = round(frames * 1000 / fps)
    work.mkdir(parents=True, exist_ok=True)
    page_file = work / "page.html"
    page_file.write_text(
        page_html(component, params, style, duration_ms, size), "utf-8"
    )
    page = instance.new_page(
        viewport={"width": size[0], "height": size[1]}, device_scale_factor=1
    )
    try:
        page.goto(page_file.as_uri())
        fonts = page.evaluate("window.mgReady")
        if any(not str(row).endswith(":loaded") for row in fonts):
            raise ValueError(f"MG fonts not loaded: {fonts}")
        paths = []
        for n in range(frames):
            page.evaluate(f"window.mgSeek({n * 1000 / fps:.3f})")
            target = work / f"{n:05d}.png"
            page.screenshot(path=str(target), omit_background=True, type="png")
            paths.append(target)
        return paths
    finally:
        page.close()
        page_file.unlink(missing_ok=True)


def escape(text: str) -> str:  # for previews / receipts
    return html.escape(text)
