"""Supply explicit lexical newlines to the unchanged native caption renderer."""

import math
from pathlib import Path
from typing import Any

from PIL import ImageFont

from .motion_library import read_json, sha256
from .video_editing_captioning import CaptionFailure, text_boundaries


def layout_main_captions(
    package: Path,
    captions: list[dict],
    role: dict,
    enabled: bool,
) -> tuple[list[dict], dict[str, Any]]:
    report: dict[str, Any] = {
        "policy": "native-font-lexical-wrap/1",
        "enabled": enabled,
        "renderer": "unmodified original caption export with explicit newlines",
        "spoken_tokens_changed": False,
        "timing_changed": False,
        "visual_review": "unreviewed",
        "events": [],
    }
    if not enabled:
        return [], report
    assets = {a["id"]: a for a in read_json(package / "asset-manifest.json")["assets"]}
    asset = assets.get(role["font_id"])
    if not asset or asset["kind"] != "font":
        raise CaptionFailure("EDITING_CAPTION_FONT_MISSING")
    file = (package / asset["path"]).resolve()
    if (
        not file.is_relative_to(package.resolve())
        or not file.is_file()
        or sha256(file) != asset["sha256"]
    ):
        raise CaptionFailure("EDITING_CAPTION_FONT_CHANGED")
    size, width, limit = role["size_px"], role["max_width_px"], role.get("max_lines", 2)
    if (
        not all(
            type(v) in {int, float} and math.isfinite(v) and v > 0
            for v in (size, width)
        )
        or type(limit) is not int
        or limit < 1
    ):
        raise CaptionFailure("EDITING_CAPTION_LAYOUT_INVALID")
    font = ImageFont.truetype(str(file), size, index=role.get("face", 0))
    report.update(
        font_id=role["font_id"],
        font_sha256=asset["sha256"],
        size_px=size,
        max_width_px=width,
        max_lines=limit,
    )
    output = []
    for row in captions:
        text = row["text"]
        safe, preferred = text_boundaries(text)
        nodes = sorted({0, len(text), *safe})
        target = font.getlength(text) / max(1, math.ceil(font.getlength(text) / width))
        best: dict[int, tuple[float, int, int]] = {0: (0, 0, 0)}
        for stop in nodes[1:]:
            choices = []
            for start in reversed(nodes):
                if start >= stop:
                    continue
                pixels = font.getlength(text[start:stop])
                if pixels > width:
                    break
                if start not in best or best[start][2] >= limit:
                    continue
                cost = best[start][0] + 1000 + ((pixels - target) / size) ** 2
                cost += 40 if stop != len(text) and stop not in preferred else 0
                choices.append((cost, start, best[start][2] + 1))
            if choices:
                best[stop] = min(choices)
        if len(text) not in best:
            raise CaptionFailure("EDITING_CAPTION_CAPACITY_REVIEW_REQUIRED")
        lines, cursor = [], len(text)
        while cursor:
            start = best[cursor][1]
            lines.append(text[start:cursor])
            cursor = start
        lines.reverse()
        native_text = "\n".join(lines)
        output.append(
            {
                "text": native_text,
                "start_seconds": row["start_seconds"],
                "end_seconds": row["end_seconds"],
            }
        )
        report["events"].append(
            {
                "raw_text": text,
                "native_text": native_text,
                "lines": lines,
                "line_widths": [font.getlength(line) for line in lines],
                "start_seconds": row["start_seconds"],
                "end_seconds": row["end_seconds"],
            }
        )
    return output, report


def verify_native_caption_layout(root: Path) -> str:
    expected = read_json(root / "caption-adapter-layout.json")
    if not expected["enabled"]:
        return "disabled_for_existing_source_captions"
    native = read_json(root / "plans/caption-layout.json")
    if native["font_sha256"] != expected["font_sha256"] or len(native["events"]) != len(
        expected["events"]
    ):
        raise CaptionFailure("EDITING_CAPTION_LAYOUT_MISMATCH")
    for actual, planned in zip(native["events"], expected["events"], strict=True):
        if (
            any(
                actual[key] != planned[key]
                for key in ("lines", "line_widths", "start_seconds", "end_seconds")
            )
            or actual["text"] != planned["native_text"]
        ):
            raise CaptionFailure("EDITING_CAPTION_LAYOUT_MISMATCH")
    return "verified_against_original_caption_engine"
