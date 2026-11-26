"""bihuo-frame/1 text-dip: a text switch on a card never shows both texts."""

from __future__ import annotations

from PIL import Image, ImageDraw

from app.bihuo_suite import frame_policy as fp

W, H = fp.W, fp.H
CARD = (148, 775, 931, 1419)
GREY = (238, 238, 238, 255)
INK = (30, 60, 200, 255)


class NoFace:
    def detect(self, image):
        return None


def policy():
    p = fp.Policy()
    p.detector = NoFace()
    p.error = None
    return p


def card(top):
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rectangle(CARD, fill=GREY)
    for i in range(3):  # three text lines
        d.rectangle((190, top + i * 60, 790, top + i * 60 + 40), fill=INK)
    return image


def render(p, n, info):
    roles = {
        "presenter": Image.new("RGBA", (W, H), (0, 0, 0, 0)),
        "information": info,
    }
    ImageDraw.Draw(roles["presenter"]).rectangle(
        (606, 372, 967, 733), fill=(90, 90, 90, 255)
    )
    canvas = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    for image in roles.values():
        canvas.alpha_composite(image)
    return p.frame(n, (canvas.convert("RGB"), roles))


def test_moved_text_dips_through_the_card_instead_of_overlapping():
    p = policy()
    seq = [card(820)] * 3 + [card(1010)] * 6
    both = []
    for n, info in enumerate(seq):
        rgb = render(p, n, info)[0]
        a = rgb.getpixel((300, 840))  # old text only
        b = rgb.getpixel((300, 1150))  # new text only
        old_on = a[2] - a[0] > 40
        new_on = b[2] - b[0] > 40
        both.append(old_on and new_on)
        assert rgb.getpixel((800, 1300))[:3] == GREY[:3]  # card never blinks
    assert not any(both)
    assert p.summary["dissolves"]["switch"] == 1
    assert p.summary["text_dips"] == 1
    last = render(p, 9, card(1010))[0]
    assert last.getpixel((300, 1150))[:3] == INK[:3]


def test_picture_switch_keeps_the_crossfade():
    p = policy()
    red = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(red).rectangle(CARD, fill=(230, 40, 30, 255))
    blue = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(blue).rectangle(CARD, fill=(30, 40, 230, 255))
    reds = []
    for n, info in enumerate([red] * 3 + [blue] * 6):
        reds.append(render(p, n, info)[0].getpixel((540, 1000))[0])
    mid = reds[3 : 3 + fp.DISSOLVE_FRAMES]
    assert all(30 < r < 230 for r in mid)
    assert p.summary["text_dips"] == 0


def text_only(top):
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    for i in range(3):  # thin strokes on a transparent layer, like glyphs
        for x in range(190, 790, 24):
            d.rectangle((x, top + i * 60, x + 8, top + i * 60 + 40), fill=INK)
    return image


def test_text_only_layer_fades_out_before_the_new_text_fades_in():
    p = policy()
    seq = [text_only(820)] * 3 + [text_only(1010)] * 6
    both = []
    for n, info in enumerate(seq):
        rgb = render(p, n, info)[0]
        a = rgb.getpixel((194, 840))
        b = rgb.getpixel((194, 1150))
        both.append(a[0] < 200 and b[0] < 200)  # ink darkens the white page
    assert not any(both)
    assert p.summary["text_dips"] == 1
