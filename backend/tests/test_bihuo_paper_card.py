"""生活手记（bihuo-10）知识卡片：不成句的词不上卡，金色条为空时整块不画。"""

from PIL import Image

from app.bihuo_suite import adaptive_layout as adaptive

# Real dev compilations (de672109 / 559858f4, 11-28).
WINTER = [
    "开店第三年，",
    "我才明白冬天最该备的是护手霜。",
    "清爽不黏腻，",
    "吸收快，",
    "抹完就能玩手机。",
    "就是我们店自己做的小熊暖暖护手霜。",
]
NAILS = [
    "做了六年美甲，",
    "护手霜一定要选清爽不黏腻的。",
    "今天把我自己做的这支推荐给你。",
]


def _config(captions, items, button=""):
    return {
        "duration": 16.0,
        "captions": [{"text": t} for t in captions],
        "materials": [{"end": 4.0}],
        "stars_at": 8.7,
        "card": {
            "enabled": True,
            "title": "冬天",
            "items": items,
            "button": button,
            "entry": items[0]["at"] if items else 12.8,
            "exit": [15.68, 15.88],
            "links": [11.85, 12.25],
            "button_at": 10.4,
        },
    }


def test_half_clauses_are_dropped_and_real_phrases_kept():
    ok = adaptive.card_phrase_ok
    assert not ok("就能玩手机。", WINTER)  # starts with 就, cut out of 抹完就能…
    assert not ok("推荐", NAILS)  # 这支推荐给你: mid-clause slice
    assert ok("小熊暖暖护手霜。", WINTER)  # ……做的 + whole product name
    assert ok("清爽不黏腻", WINTER) and ok("吸收快", WINTER)
    assert not ok("一定要选", NAILS) and not ok("了", NAILS)
    assert ok("三步护手法", WINTER)  # planner-written phrase, not a caption slice


def test_card_keeps_meaningful_items_and_retimes_from_the_first_kept_one():
    items = [
        {"text": "就能玩手机。", "at": 9.6},
        {"text": "小熊暖暖护手霜。", "at": 13.52},
    ]
    config = _config(WINTER, items)
    result = adaptive.paper_card_items(config, {"conclusion": None})
    card = result["card"]
    assert [row["text"] for row in card["items"]] == ["小熊暖暖护手霜。"]
    assert card["enabled"] and card["entry"] == 12.8  # min(13.52, 16*0.8)
    assert card["dropped_items"] == ["就能玩手机。"]
    assert config["card"]["items"] == items  # input untouched
    assert result["stars_at"] == max(4.0, 12.8 - 0.88)


def test_no_meaningful_item_and_no_closing_means_no_card():
    config = _config(NAILS, [{"text": "推荐", "at": 7.95}])
    card = adaptive.paper_card_items(config, {})["card"]
    assert card["items"] == [] and card["enabled"] is False


def test_good_cards_compile_unchanged():
    items = [{"text": "清爽不黏腻", "at": 9.0}, {"text": "吸收快", "at": 10.0}]
    config = _config(WINTER, items, "认准小熊暖暖")
    assert adaptive.paper_card_items(config, {}) is config


def test_empty_golden_bar_and_its_links_are_not_drawn():
    blank = (1080, 1920)

    def native_card(t, cfg):
        layers = {}
        for key in (
            "card",
            "card-items",
            "card-links",
            "card-button",
            "card-conclusion",
        ):
            im = Image.new("RGBA", blank)
            im.putpixel((540, 760), (173, 137, 40, 255))
            layers[key] = im
        return layers

    module = type("M", (), {})()
    module.C = type(
        "C", (), {"ink": staticmethod(lambda *a: Image.new("RGBA", (1, 1)))}
    )()
    cfg = _config(WINTER, [{"text": "吸收快", "at": 10.0}])
    roles = adaptive.paper_card_layers(module, native_card, 11.0, cfg)
    assert roles["card-button"].getbbox() is None
    assert roles["card-conclusion"].getbbox() is None
    assert roles["card-links"].getbbox() is None
    assert roles["card"].getbbox() is not None and roles["card-items"].getbbox()
    cfg["card"]["button"] = "认准小熊暖暖"
    roles = adaptive.paper_card_layers(module, native_card, 11.0, cfg)
    assert roles["card-button"].getbbox() is not None
