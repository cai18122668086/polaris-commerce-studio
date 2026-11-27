"""Offline cover rules: exact title, face kept clear, warm design colours."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from app import video_cover_compose as cc

FACE_LOW = (420, 640, 660, 900)  # centred, lower half -> top title first
FACE_HIGH = (420, 260, 660, 520)  # centred, upper half -> bottom title first
FACE_RIGHT = (700, 420, 940, 680)


def plain(color=(236, 226, 214)) -> Image.Image:
    return Image.new("RGB", cc.CANVAS, color)


def busy() -> Image.Image:
    image = plain()
    draw = ImageDraw.Draw(image)
    for x in range(0, cc.CANVAS[0], 40):
        draw.rectangle((x, 0, x + 20, cc.CANVAS[1]), fill=(30, 25, 20))
    return image


@pytest.mark.parametrize(
    "title",
    [
        "夏天必备的冰丝凉席",
        "3个方法让你的皮肤状态翻倍，学生党也能轻松做到！",
        "iPhone 17 Pro 真实体验：续航到底怎么样？",
        "别再乱买了",
    ],
)
@pytest.mark.parametrize("face", [FACE_LOW, FACE_HIGH, FACE_RIGHT, None])
def test_every_layout_keeps_the_title_exact_and_off_the_face(title, face):
    text = cc.normalise_cover_text(title)
    result, checks = cc.compose(plain(), text, cc.choose_layouts(face), face)
    assert checks.passed, checks
    assert "".join(result.lines).replace(" ", "") == text.replace(" ", "")
    assert checks.face_overlap_px == 0
    assert result.image.size == (1080, 1440)
    assert result.font_size >= cc.MIN_FONT


def test_two_candidates_use_structurally_different_layouts():
    for face in (FACE_LOW, FACE_HIGH, FACE_RIGHT, None):
        first, second = cc.choose_layouts(face, text="夏天必备的冰丝凉席")[:2]
        assert first != second
    assert cc.choose_layouts(FACE_LOW)[0] == "top"
    assert cc.choose_layouts(FACE_HIGH)[0] == "bottom"
    assert cc.choose_layouts(FACE_RIGHT)[0] == "side"
    # 换一批: unused layouts first.
    assert cc.choose_layouts(FACE_LOW, previous=("top", "bottom"))[0] == "side"


def test_line_breaks_follow_cjk_punctuation_rules():
    for count in (2, 3):
        lines = cc.break_lines("3个方法让你的皮肤状态翻倍，学生党也能轻松做到！", count)
        assert lines and len(lines) == count
        assert all(line[0] not in cc.NO_LINE_START for line in lines)
        assert all(line[-1] not in cc.NO_LINE_END for line in lines)
    # Latin words and numbers are never split.
    lines = cc.break_lines("iPhone17Pro续航实测", 2)
    assert lines and all(
        "iPhone17Pro" in line or "iPhone" not in line for line in lines
    )


def test_glyph_check_catches_characters_the_font_cannot_draw():
    assert cc.missing_glyphs("冰丝凉席，夏天必备！") == []
    assert cc.missing_glyphs("好物😀") == ["😀"]
    assert (
        cc.default_cover_text("夏天必备😀 冰丝凉席 #好物推荐 #夏天")
        == "夏天必备 冰丝凉席"
    )


def test_text_check_fails_when_lines_do_not_match():
    result, _ = cc.compose(plain(), "夏天必备的冰丝凉席", ["top"], FACE_LOW)
    result.lines = ["夏天必备的冰丝"]
    assert not cc.verify(result, "夏天必备的冰丝凉席", FACE_LOW).text_exact


def test_face_check_fails_when_text_touches_the_face():
    result, _ = cc.compose(plain(), "夏天必备的冰丝凉席", ["top"], FACE_LOW)
    moved = (
        FACE_LOW[0],
        result.text_boxes[0][1],
        FACE_LOW[2],
        result.text_boxes[0][3] + 80,
    )
    checks = cc.verify(result, "夏天必备的冰丝凉席", moved)
    assert not checks.face_clear and not checks.passed


def test_design_colours_are_never_blue_or_purple():
    for background in (plain(), plain((20, 20, 24)), busy()):
        result, checks = cc.compose(
            background,
            "夏天必备的冰丝凉席",
            ["top", "bottom"],
            FACE_LOW,
            highlight="冰丝",
        )
        assert checks.design_colors_ok
        assert not any(cc.is_blue_purple(cc.hex_rgb(c)) for c in result.design_colors)
    assert cc.is_blue_purple((40, 80, 220)) and cc.is_blue_purple((140, 60, 220))
    assert not cc.is_blue_purple(cc.hex_rgb(cc.HIGHLIGHT_ON_DARK_TEXT))


def test_blue_picture_is_only_a_hint_never_a_failure():
    blue = plain((30, 70, 200))
    result, checks = cc.compose(blue, "夏天必备的冰丝凉席", ["top"], FACE_LOW)
    assert checks.passed
    assert checks.picture_cool_hint and checks.picture_cool_share > cc.PICTURE_COOL_HINT


def test_busy_backgrounds_get_a_plate_and_light_ones_dark_text():
    light, _ = cc.compose(plain(), "夏天必备的冰丝凉席", ["top"], FACE_LOW)
    assert light.tone == "dark" and light.plate is None
    noisy, checks = cc.compose(busy(), "夏天必备的冰丝凉席", ["top"], FACE_LOW)
    assert noisy.plate is not None and checks.face_clear


def test_too_long_text_is_rejected_before_any_charge():
    with pytest.raises(cc.CoverComposeError) as error:
        cc.compose(plain(), "这" * 90, ["side"], FACE_RIGHT)
    assert error.value.code == "COVER_TEXT_DOES_NOT_FIT"


def test_crop_keeps_the_face_inside_a_3_4_canvas():
    frame = Image.new("RGB", (1080, 1920), (200, 190, 180))
    cropped, face = cc.crop_to_canvas(frame, (440, 500, 640, 760))
    assert cropped.size == cc.CANVAS
    assert face and 0 <= face[0] < face[2] <= 1080 and 0 <= face[1] < face[3] <= 1440
    wide = Image.new("RGB", (1920, 1080))
    assert cc.crop_to_canvas(wide, None)[0].size == cc.CANVAS


def test_sample_times_skip_the_edges():
    times = cc.sample_times(20.0, 12)
    assert len(times) == 12 and times[0] == 1.0 and times[-1] == 19.0


def test_layouts_that_cannot_hold_the_title_are_skipped():
    big_face = (300, 150, 780, 900)  # a close-up: no room above the head
    text = "3个方法让皮肤状态翻倍，学生党也能做到"
    layouts = cc.choose_layouts(big_face, text=text)
    assert layouts and "top" not in layouts
    for layout in ("top", "bottom", "side"):
        fits = cc.fit_text(text, cc.text_zone(layout, big_face), layout) is not None
        assert fits == (layout in layouts)
    for layout in layouts:
        assert cc.compose(plain(), text, [layout], big_face)[1].passed


def test_crop_slides_for_title_room_but_never_cuts_the_face():
    frame = Image.new("RGB", (1080, 1920), (200, 190, 180))
    face = (140, 270, 680, 1030)  # close-up near the top of a 9:16 frame
    text = "3个方法让皮肤状态翻倍，学生党也能做到"
    cropped, moved = cc.crop_to_canvas(frame, face, text)
    assert cropped.size == cc.CANVAS and moved is not None
    assert moved[1] > 0 and moved[3] < cc.CANVAS[1]  # whole face kept
    assert any(
        cc.fit_text(text, cc.text_zone(x, moved), x) for x in cc.choose_layouts(moved)
    )


def test_line_breaks_keep_particles_with_their_word():
    for count in (2, 3):
        lines = cc.break_lines("夏天必备的冰丝凉席", count)
        assert lines and not any(line[0] in cc.PARTICLES for line in lines)


def test_face_detection_is_serialised_across_threads(monkeypatch):
    """Two covers in parallel must never run the detector at the same time."""

    import threading
    import time

    active, peak = [0], [0]

    class Slow:
        def detect(self, image):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            active[0] -= 1
            return None

    monkeypatch.setattr(cc, "_detector", lambda size: Slow())
    threads = [
        threading.Thread(target=lambda: [cc.detect_face(plain()) for _ in range(5)])
        for _ in range(4)
    ]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert peak[0] == 1
