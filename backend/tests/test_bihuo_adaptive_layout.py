"""Material dominance and content-sized cards through real native samplers."""

from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app.bihuo_suite import adaptive_layout as layout
from app.bihuo_suite import registry


@pytest.mark.parametrize("tid", ["bihuo-03-v1", "bihuo-04-v1"])
@pytest.mark.parametrize("size", [(1800, 962), (720, 1280)])
def test_application_material_uses_its_reading_area_without_distortion(
    tmp_path, tid, size
):
    path = tmp_path / "actual.png"
    image = Image.new("RGB", size, "#d5e9ef")
    ImageDraw.Draw(image).rectangle(
        (0, 0, size[0] - 1, size[1] - 1), outline="red", width=8
    )
    image.save(path)
    module = registry.runtime(tid)
    native = module.bottom.BASE if tid == "bihuo-04-v1" else module.top
    cfg = {
        "size": [1080, 1920],
        "material_mode": "provided",
        "materials": [
            {"id": "actual", "path": str(path), "type": "image", "start": 0, "end": 2}
        ],
    }
    painted = layout.app_material(native, cfg, 1, tid == "bihuo-04-v1")
    x, y, x2, y2 = painted.getbbox()
    w, h = x2 - x, y2 - y
    assert abs(w / h - size[0] / size[1]) < 0.02
    assert w >= 780 if size[0] > size[1] else h >= 530
    assert y2 <= 1400


@pytest.mark.parametrize("tid", ["bihuo-16-v1", "bihuo-19-v1", "bihuo-40-v1"])
def test_native_window_keeps_short_reading_cards_compact_and_restores_helpers(tid):
    module = registry.runtime(tid)
    native = __import__(module.encode.__globals__["__name__"], fromlist=["window"])
    original = native.window
    original_card = native.textcard
    font = next(iter(registry.fonts(tid).values()))
    with layout.execution(module, {"template_id": tid, "config": {}}):
        tile = native.textcard("产品是否清楚", font, 922, 922)
        window = native.window(tile, [80, 540, 1002, 1462], 30)
        x, y, x2, y2 = window.getbbox()
        assert y2 - y < 260
        assert y < 650
        assert tile.getpixel((0, 921))[3] == 0
    assert native.window is original and native.textcard is original_card


@pytest.mark.parametrize("size", [(414, 312), (551, 552), (922, 922)])
def test_long_information_stays_inside_its_real_capacity(size):
    font = next(iter(registry.fonts("bihuo-40-v1").values()))
    tile = layout.compact_textcard(
        "规格和使用场景有没有讲完整，颜色和排版是不是统一。", font, *size
    )
    box = tile.getbbox()
    assert box and 0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1]


def test_milkblue_material_clears_the_caption_and_keeps_all_four_corners(tmp_path):
    path = tmp_path / "material.png"
    im = Image.new("RGB", (1600, 900), "red")
    im.save(path)
    keys = [
        "materials",
        "material_text",
        "outline_cyan",
        "outline_white",
        "presenter_foreground",
        "caption_body",
        "background",
    ]

    def blank():
        return Image.new("RGBA", (1080, 1920))

    def original(raw, c, n, roles=False):
        out = {k: blank() for k in keys}
        ImageDraw.Draw(out["caption_body"]).rectangle(
            (220, 1580, 850, 1660), fill="yellow"
        )
        return raw, out

    def subject(raw, c, n, box, out):
        ImageDraw.Draw(out["presenter_foreground"]).rectangle(box, fill="blue")

    def ramp(t, a, b):
        return max(0, min(1, (t - a) / (b - a)))

    native = SimpleNamespace(
        blank=blank, subject=subject, ramp=ramp, opacity=lambda image, q: image
    )
    cfg = {"duration": 12, "materials": [{"path": str(path), "start": 0, "end": 10}]}
    rgb, out = layout.milkblue_render(
        native, original, Image.new("RGB", (1080, 1920)), cfg, 25, True
    )
    assert out["materials"].getbbox()[3] < 1500
    assert out["caption_body"].getbbox() == (220, 1580, 851, 1661)
    assert rgb.getpixel((540, 1600)) == (255, 255, 0)
    assert rgb.getpixel((540, 1000)) == (255, 0, 0)


def test_head_breakout_and_room_share_one_source_transform(tmp_path):
    module = registry.runtime("bihuo-19-v1")
    native = __import__(module.encode.__globals__["__name__"], fromlist=["head"])
    alpha = Image.new("L", (1080, 1920))
    ImageDraw.Draw(alpha).rectangle((200, 200, 800, 1500), fill=255)
    path = tmp_path / "alpha.png"
    alpha.save(path)
    raw = Image.new("RGBA", (1080, 1920), "red")
    ImageDraw.Draw(raw).rectangle((0, 700, 1079, 1919), fill="blue")
    out = {
        k: native.blank() for k in ["presenter_room", "room_glow", "head_foreground"]
    }
    layout.coherent_head(
        native, raw, {"foreground_alpha": {"0": {"path": str(path)}}}, 0, out
    )
    for y in [270, 300, 350]:
        assert (
            out["presenter_room"].getpixel((540, y))[:3]
            == out["head_foreground"].getpixel((540, y))[:3]
        )
    assert out["head_foreground"].getbbox()[3] <= 506


def test_milkblue_caption_keeps_complete_words_and_source_clock():
    font = next(iter(registry.fonts("bihuo-16-v1").values()))
    text = "规格和使用场景有没有讲完整。"
    display = layout.fit(text, font, 1000, (76, 72, 68, 64, 60), 2)
    assert "".join(display["lines"]) == text
    assert any("完整" in line for line in display["lines"])
    assert min(len(line) for line in display["lines"]) >= 5
    module = registry.runtime("bihuo-16-v1")
    native = __import__(module.encode.__globals__["__name__"], fromlist=["caption"])
    row = {
        "text": text,
        "time": [1, 3],
        "lines": [{"text": text, "emphasis_spans": []}],
    }
    cfg = {"font": font, "captions": [row]}
    out = {
        k: native.blank()
        for k in ["caption_body", "caption_emphasis", "caption_shadow"]
    }
    layout.milkblue_caption(native, native.caption, cfg, 50, out)
    assert cfg["captions"] == [row] and row["time"] == [1, 3]
    assert out["caption_body"].getbbox()[3] < 1710
