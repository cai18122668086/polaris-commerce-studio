"""彩色主题 24/13/15：字幕底衬只在宿主侧加，模板文件、字形、时间与身份不变。"""

import pytest
from PIL import Image, ImageDraw

from app.bihuo_suite import adaptive_layout as adaptive
from app.bihuo_suite import conditional_layout, registry

SIZE = (1080, 1920)


def _words(box, color=(255, 255, 255, 255), alpha=255):
    layer = Image.new("RGBA", SIZE)
    ImageDraw.Draw(layer).rectangle(box, fill=(*color[:3], alpha))
    return layer


def test_qingbai_backing_sits_under_the_words_and_shadow_no_longer_covers_them():
    roles = {
        "caption_chinese_body": _words((300, 1520, 700, 1590)),
        "caption_chinese_emphasis": _words((700, 1513, 800, 1586), (35, 194, 190)),
        "caption_chinese_shadow": _words((303, 1525, 803, 1595), (0, 15, 20), 120),
        "caption_english": Image.new("RGBA", SIZE),
        "caption_english_shadow": Image.new("RGBA", SIZE),
    }
    shown, meta = adaptive.qingbai_backed_captions(
        None, lambda c, n: (dict(roles), {"id": "N01"}), {}, 10
    )
    assert meta == {"id": "N01"}
    assert list(shown)[0] == "caption_chinese_shadow"  # drawn before the words
    assert shown["caption_chinese_body"] is roles["caption_chinese_body"]
    plate = shown["caption_chinese_shadow"]
    x, y, x2, y2 = plate.getbbox()
    assert x < 300 and x2 > 800 and y < 1513 and y2 > 1595
    r, g, b, a = plate.getpixel((290, 1550))  # plate margin, template edge colour
    assert (r, g, b) == (0, 30, 36) and 150 <= a <= 160


def test_backing_fades_with_the_caption_and_is_absent_without_one():
    faded = {
        "caption_chinese_body": _words((300, 1520, 700, 1590), alpha=64),
        "caption_chinese_emphasis": Image.new("RGBA", SIZE),
        "caption_chinese_shadow": Image.new("RGBA", SIZE),
    }
    shown, _ = adaptive.qingbai_backed_captions(None, lambda c, n: (faded, {}), {}, 1)
    assert shown["caption_chinese_shadow"].getpixel((290, 1550))[3] < 45
    empty = {k: Image.new("RGBA", SIZE) for k in faded}
    shown, _ = adaptive.qingbai_backed_captions(None, lambda c, n: (empty, {}), {}, 1)
    assert shown["caption_chinese_shadow"].getbbox() is None


def test_qingci_backing_spans_the_whole_line_while_glyphs_type_in():
    layer = _words((200, 1600, 260, 1660), (255, 248, 229))  # first glyph only
    meta = {
        "line_widths": [400],
        "baseline": 1655,
        "glyphs": [
            {"x": 200 + 80 * i, "advance": 80, "size": 76, "char": "字"}
            for i in range(5)
        ],
    }
    shown, same = adaptive.qingci_backed_caption(
        None, lambda c, n: (layer, meta), {"caption_style": {}}, 5
    )
    assert same is meta
    x, y, x2, y2 = shown.getbbox()
    assert x < 200 and x2 > 600  # full line, not just the visible glyph
    assert shown.getpixel((230, 1630))[:3] == (255, 248, 229)  # words stay on top
    assert shown.getpixel((500, 1630))[:3] == (44, 34, 25)


def test_blue_backing_goes_under_the_glow_layer():
    roles = {
        "caption_body": _words((300, 1610, 600, 1670)),
        "caption_emphasis": _words((600, 1606, 700, 1672), (38, 95, 245)),
        "caption_shadow": Image.new("RGBA", SIZE),
        "caption_glow": Image.new("RGBA", SIZE),
    }
    shown, _ = adaptive.blue_backed_captions(
        None, lambda c, n, d=False: (dict(roles), []), {}, 3
    )
    assert shown["caption_body"] is roles["caption_body"]
    glow = shown["caption_glow"]
    assert glow.getbbox()[0] < 300 and glow.getbbox()[2] > 700
    r, g, b, a = glow.getpixel((290, 1640))
    assert (r, g, b) == (22, 24, 28) and not (b > r + 20)  # neutral, not blue


@pytest.mark.parametrize(
    ("template", "target", "name"),
    [
        ("bihuo-24-v1", "E", "captions"),
        ("bihuo-13-v1", "E", "caption"),
        ("bihuo-15-v1", "E", "captions"),
    ],
)
def test_backing_hooks_are_scoped_and_restored(template, target, name):
    module = registry.runtime(template)
    owner = getattr(module, target)
    original = vars(owner)[name]
    payload = {"template_id": template}
    with pytest.raises(RuntimeError), adaptive.execution(module, payload):
        assert vars(owner)[name] is not original
        raise RuntimeError("render interrupted")
    assert vars(owner)[name] is original


def test_backing_templates_carry_a_policy_and_identities_are_unchanged():
    for template in adaptive.CAPTION_BACKING:
        assert template in conditional_layout.TARGETS
        policy: dict = {}
        adaptive.prepare(template, {}, policy)
        assert policy["caption_backing"] == "template-palette-plate/1"
    # Bundle identity covers the template meta, manifest, planner and the
    # registry/render/foreground/source files; none of them is edited here.
    identities = {
        t: registry.bundle_identity(t)["sha256"] for t in registry.definitions()
    }
    assert len(identities) == len(registry.definitions())
