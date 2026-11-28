"""快讯直播 / 深青标题 / 星光商务：长句宿主侧拆行，模板文件与身份不变。"""

import copy

import pytest

from app.bihuo_suite import adaptive_layout as adaptive
from app.bihuo_suite import registry

# Real 24-line furniture script sentences (dev e2e) plus the longest a plan may
# carry: two planned lines of 18 word characters each.
LONG = [
    "所以挑家具这件事，得先把标准想清楚",
    "家具不是天天买，但是你要天天用",
    "我建议你先量好尺寸，再去门店慢慢挑选材质和颜色",
    "实木的质感确实好，但保养起来真的比板材要麻烦很多",
]


def _resolved(texts, spans=None, lines=None):
    rows = []
    for i, text in enumerate(texts):
        row_lines = (lines or {}).get(i) or [
            {"text": text, "emphasis_spans": (spans or {}).get(i, [])}
        ]
        rows.append(
            {"text": text, "time": [i * 3 + 0.2, i * 3 + 2.8], "lines": row_lines}
        )
    return {"duration": len(texts) * 3 + 1.0, "captions": rows, "materials": []}


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"not decoded at compile time")
    return path


def _compile(template_id, resolved, source):
    with adaptive.compilation(template_id):
        return registry.compile_request(
            template_id,
            resolved,
            source_path=str(source),
            creative_options={"title": "", "name_card": {"enabled": False}},
        )["config"]


def test_navy_long_sentences_become_lines_that_pass_the_native_gate(source):
    module = registry.runtime("bihuo-23-v1")
    resolved = _resolved(LONG, spans={0: [[3, 5]], 2: [[5, 7]]})
    before = copy.deepcopy(resolved)
    with pytest.raises(AssertionError):  # unchanged native gate, unwrapped input
        cfg = registry.compile_request(
            "bihuo-23-v1", resolved, source_path=str(source), creative_options={}
        )["config"]
        module._captions(cfg, cfg["captions"][0]["frames"][0])
    cfg = _compile("bihuo-23-v1", resolved, source)
    assert resolved == before  # the plan's resolved input is not mutated
    for row, original in zip(cfg["captions"], LONG, strict=True):
        assert row["text"] == original
        assert "".join(x["text"] for x in row["lines"]) == original
        assert 1 <= len(row["lines"]) <= 3
        for frame in range(row["frames"][0], row["frames"][1], 7):
            layers = module._captions(cfg, frame)  # native assert <= 1010 px
            box = layers["caption_body"].getbbox()
            assert box and box[0] >= 20 and box[2] <= 1060
    assert [len(r["lines"]) > 1 for r in cfg["captions"]] == [True, False, True, True]
    marked = [
        line["text"][a:b]
        for line in cfg["captions"][0]["lines"]
        for a, b in line["emphasis_spans"]
    ]
    assert marked == ["家具"]
    assert module.compile_request is not None
    assert "wrapped" not in module.compile_request.__name__  # hook restored


def test_navy_short_captions_compile_byte_identical(source):
    resolved = _resolved(["这款白色头戴耳机，", "打开降噪，"], spans={1: [[2, 3]]})
    with_hook = _compile("bihuo-23-v1", resolved, source)
    plain = registry.compile_request(
        "bihuo-23-v1",
        resolved,
        source_path=str(source),
        creative_options={"title": "", "name_card": {"enabled": False}},
    )["config"]
    assert with_hook == plain


def test_qingbai_wraps_only_the_wide_line_and_keeps_others_full_size(source):
    module = registry.runtime("bihuo-24-v1")
    texts = ["打开降噪，", LONG[0], "键盘声都安静了。"]
    plain = registry.compile_request(
        "bihuo-24-v1", _resolved(texts), source_path=str(source), creative_options={}
    )["config"]
    assert plain["caption_size"] < 64  # native: one long line shrinks every caption
    cfg = _compile("bihuo-24-v1", _resolved(texts), source)
    assert cfg["caption_size"] == 64
    assert [len(c["lines"]) for c in cfg["captions"]] == [1, 2, 1]
    for row in cfg["captions"]:
        assert "".join(x["text"] for x in row["lines"]) == row["text"]
        module.E.captions(cfg, int(row["range"][0]) + 1)  # native assert <= 1040


def test_qingbai_overlong_sentence_no_longer_rejects_the_whole_video(source):
    text = "我建议你先量好尺寸再去门店慢慢挑选材质和颜色还有五金件"
    with pytest.raises(ValueError, match="semantic line break"):
        registry.compile_request(
            "bihuo-24-v1",
            _resolved([text]),
            source_path=str(source),
            creative_options={},
        )
    cfg = _compile("bihuo-24-v1", _resolved([text]), source)
    assert len(cfg["captions"][0]["lines"]) == 2
    registry.runtime("bihuo-24-v1").E.captions(cfg, 6)


def test_qingbai_keeps_planned_two_lines_within_its_two_line_limit(source):
    lines = {
        0: [
            {"text": "家具不是天天买，", "emphasis_spans": []},
            {"text": "但是你要天天用", "emphasis_spans": [[4, 7]]},
        ]
    }
    cfg = _compile("bihuo-24-v1", _resolved([LONG[1]], lines=lines), source)
    assert cfg["captions"][0]["lines"] == lines[0]


def _business_cfg(text, spans):
    fonts = registry.fonts("bihuo-47-v1")
    return {
        "fonts": {"body": fonts["caption"], "title": fonts["title"]},
        "captions": [{"text": text, "frames": [10, 80], "emphasis_spans": spans}],
    }


def test_business_lopsided_cut_is_rebalanced_instead_of_leaving_the_frame():
    module = registry.runtime("bihuo-47-v1")
    text = "所以挑家具这件事得先把标准想清楚然后再去门店慢慢看看材质和颜色"
    cfg = _business_cfg(text, [[0, 2]])
    native, _ = module._caps(cfg, 30)
    left, _, right, _ = native["caption_body"].getbbox()
    assert left <= 0 or right >= 1080  # native: emphasis end at 2 -> overflow
    shown, meta = adaptive.business_caps(module, module._caps, cfg, 30)
    left, _, right, _ = shown["caption_body"].getbbox()
    assert left > 0 and right < 1080 and meta["line_count"] == 2
    emphasis = shown["caption_emphasis"].getbbox()
    assert emphasis is not None


def test_business_fitting_captions_stay_native():
    module = registry.runtime("bihuo-47-v1")
    for text, spans in [("家具不是天天买", []), (LONG[0], [[3, 5], [12, 14]])]:
        cfg = _business_cfg(text, spans)
        native, meta = module._caps(cfg, 30)
        shown, shown_meta = adaptive.business_caps(module, module._caps, cfg, 30)
        assert shown_meta == meta
        assert all(shown[k].tobytes() == native[k].tobytes() for k in native)


def test_wrap_never_changes_bundle_identity():
    before = {t: registry.bundle_identity(t)["sha256"] for t in registry.definitions()}
    with adaptive.compilation("bihuo-23-v1"):
        pass
    assert before == {
        t: registry.bundle_identity(t)["sha256"] for t in registry.definitions()
    }
