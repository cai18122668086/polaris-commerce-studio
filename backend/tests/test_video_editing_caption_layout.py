"""Real font metrics on a tiny Pillow font; original-engine proof is separate."""

import copy

import pytest
from PIL import ImageFont

from app.motion_library import atomic_json, sha256
from app.video_editing_caption_layout import (
    layout_main_captions,
    verify_native_caption_layout,
)
from app.video_editing_captioning import CaptionFailure


def font_package(tmp_path):
    package = tmp_path / "library"
    package.mkdir()
    path = package / "pillow-test-font.ttf"
    path.write_bytes(ImageFont.load_default().path.getvalue())
    atomic_json(
        package / "asset-manifest.json",
        {
            "assets": [
                {
                    "id": "test-font",
                    "kind": "font",
                    "path": path.name,
                    "sha256": sha256(path),
                }
            ]
        },
    )
    return package, path


def test_explicit_native_lines_keep_price_and_grade_without_new_times(tmp_path):
    package, path = font_package(tmp_path)
    font = ImageFont.truetype(str(path), 48)
    text = "你看看我下面这个链接14块9，"
    rows = [
        {
            "text": text,
            "start_seconds": 8.65,
            "end_seconds": 10.91,
            "token_ids": ["source-word"],
        }
    ]
    original = copy.deepcopy(rows)
    role = {
        "font_id": "test-font",
        "size_px": 48,
        "max_width_px": font.getlength(text[:-2]),
        "max_lines": 2,
    }
    native, report = layout_main_captions(package, rows, role, True)
    lines = native[0]["text"].split("\n")
    assert len(lines) == 2
    assert "".join(lines) == text
    assert any("14块9" in line for line in lines)
    assert all(font.getlength(line) <= role["max_width_px"] for line in lines)
    assert native[0]["start_seconds"] == 8.65 and native[0]["end_seconds"] == 10.91
    assert rows == original
    assert not report["timing_changed"] and report["visual_review"] == "unreviewed"


def test_atomic_label_does_not_fit_requires_review_without_font_substitution(tmp_path):
    package, _ = font_package(tmp_path)
    role = {"font_id": "test-font", "size_px": 48, "max_width_px": 5, "max_lines": 2}
    with pytest.raises(CaptionFailure) as error:
        layout_main_captions(
            package,
            [{"text": "1000kg", "start_seconds": 1, "end_seconds": 2}],
            role,
            True,
        )
    assert error.value.code == "EDITING_CAPTION_CAPACITY_REVIEW_REQUIRED"


def test_missing_original_font_or_changed_bytes_is_not_silently_replaced(tmp_path):
    package, path = font_package(tmp_path)
    role = {"font_id": "test-font", "size_px": 48, "max_width_px": 200, "max_lines": 2}
    path.write_bytes(b"changed fixture bytes")
    with pytest.raises(CaptionFailure) as error:
        layout_main_captions(
            package,
            [{"text": "14.9", "start_seconds": 1, "end_seconds": 2}],
            role,
            True,
        )
    assert error.value.code == "EDITING_CAPTION_FONT_CHANGED"


def test_actual_native_layout_must_match_the_prepared_lines(tmp_path):
    atomic_json(
        tmp_path / "caption-adapter-layout.json",
        {
            "enabled": True,
            "font_sha256": "a",
            "events": [
                {
                    "native_text": "14块9",
                    "lines": ["14块9"],
                    "line_widths": [80],
                    "start_seconds": 1,
                    "end_seconds": 2,
                }
            ],
        },
    )
    atomic_json(
        tmp_path / "plans/caption-layout.json",
        {
            "font_sha256": "a",
            "events": [
                {
                    "text": "14块9",
                    "lines": ["14块", "9"],
                    "line_widths": [60, 20],
                    "start_seconds": 1,
                    "end_seconds": 2,
                }
            ],
        },
    )
    with pytest.raises(CaptionFailure) as error:
        verify_native_caption_layout(tmp_path)
    assert error.value.code == "EDITING_CAPTION_LAYOUT_MISMATCH"
