"""第三轮 brief 写稿：硬规则、句子级修复只动点名句、去重、骨架 label 映射、反例夹具。"""

import json
from pathlib import Path

import pytest

from app import video_brief_writing as bw
from app.video_writing_contracts import (
    SpokenDraftLine,
    WritingAnalysis,
    WritingBriefDraft,
    WritingFacts,
)
from app.video_writing_rules import (
    DURATION_WORDS,
    GENERIC_SKELETONS,
    brief_draft_rules,
    generic_skeleton,
)

FIXTURES = Path(__file__).parent / "fixtures/writing_brief"
BAD = json.loads((FIXTURES / "c8dbc697_drafts.json").read_text("utf-8"))

FACTS = WritingFacts.model_validate(
    {
        "facts": [
            {"id": "f1", "category": "identity", "label": "店名", "value": "恒志欧式家具店", "status": "user_declared"},
            {"id": "f2", "category": "identity", "label": "位置", "value": "在新恒", "status": "user_declared"},
            {"id": "f3", "category": "product", "label": "风格", "value": "欧式家具", "status": "user_declared"},
            {"id": "f4", "category": "product", "label": "卖点", "value": "高端设计", "status": "user_declared"},
            {"id": "f5", "category": "product", "label": "材质", "value": "真皮家具", "status": "user_declared"},
            {"id": "f6", "category": "product", "label": "设计", "value": "名师设计", "status": "user_declared"},
            {"id": "f7", "category": "identity", "label": "年限", "value": "开了6年", "status": "user_declared"},
        ]
    }
)
BRIEF = {
    "speaker": "merchant_self",
    "audience": "consumer",
    "goal": "store_visit",
    "category": "欧式真皮家具",
    "locality": "新恒",
    "summary": "你是新恒一家欧式家具店的老板，想让本地准备买家具的人到店看看。",
    "cta": {"action": "visit", "text": "到店看看"},
}

# A merchant's own 45-second script: only the facts above, ~230 spoken chars.
GOOD = [
    "买沙发最怕什么？买回家坐了半年，皮面就开始起皱。",
    "我是恒志欧式家具店的老板，店就在新恒，开了6年。",
    "我们店只做欧式家具，主打真皮家具。",
    "很多人觉得欧式就是花哨，其实好的欧式家具靠的是比例和线条。",
    "我们的款都是名师设计，高端设计不是堆装饰，而是坐着舒服、看着耐看。",
    "真皮的好坏，光看照片是看不出来的，得用手摸、坐下去感受。",
    "所以我一直跟顾客说，买欧式家具别急着在网上下单。",
    "先想清楚家里的面积和风格，再来店里一件一件对比。",
    "你要是正在准备装修，或者想换一套客厅家具。",
    "周末带上家里的尺寸，来新恒的店里坐一坐、摸一摸，主页有位置。",
]


def draft(lines=None, title="真皮沙发别只看颜色，坐下去才知道", body=None):
    return WritingBriefDraft(
        title="老板带看镇店款",
        publish_title=title,
        publish_body=body
        or "在新恒开欧式家具店，今天聊聊真皮家具怎么挑。想看实物的，主页有位置。 #欧式家具 #真皮沙发 #家具店",
        sentences=[SpokenDraftLine(text=t) for t in (lines or GOOD)],
    )


def basis(**changes):
    return {
        "brief": BRIEF,
        "angle": {"id": "a1", "name": "老板带看镇店款"},
        "words": list(DURATION_WORDS[45]),
        "platform": "douyin",
        **changes,
    }


def check(lines=None, strict=True, **changes):
    return bw.check_brief(draft(lines, **{k: v for k, v in changes.items() if k in {"title", "body"}}),
                          basis(**{k: v for k, v in changes.items() if k not in {"title", "body"}}),
                          FACTS, strict=strict)


def issue(lines=None, **changes):
    with pytest.raises(bw.BriefIssue) as caught:
        check(lines, **changes)
    return caught.value.issue["kind"]


def test_a_merchants_own_script_passes_and_lines_get_their_facts():
    text = check()
    assert 200 <= bw.spoken_chars(text) <= 260
    d = draft()
    bw.check_brief(d, basis(), FACTS)
    assert "f1" in d.sentences[1].fact_ids and "f7" in d.sentences[1].fact_ids


def test_numbers_and_years_must_come_from_the_facts():
    assert issue([*GOOD[:-1], "我们店已经开了十年，欢迎来看。"]) == "numeric"
    assert issue([*GOOD[:-1], "店里有300多款沙发，欢迎来看。"]) == "numeric"
    # 「6年」 written as 「六年」 is the same declared fact.
    lines = [line.replace("开了6年", "开了六年") for line in GOOD]
    check(lines)
    # 「三句话」「第一」 count the talk, not the shop.
    check([*GOOD[:-1], "三句话说完我的店，第一次来也不会迷路，主页有位置。"])


@pytest.mark.parametrize(
    "line",
    [
        "最近朋友都在推荐这家店，我趁周末去看了看。",
        "一进门销售先招呼我坐下喝茶。",
        "今天我走进恒志欧式家具店，逛下来的感觉很好。",
        "店员跟我说这些都是名师设计。",
    ],
)
def test_visitor_narration_is_rejected_when_the_owner_speaks(line):
    lines = [*GOOD[:3], line, *GOOD[4:]]
    assert issue(lines) == "visitor_voice"
    # The same line is a visitor's own voice when a visitor speaks.
    assert check(lines, brief={**BRIEF, "speaker": "visitor"}, strict=False)


@pytest.mark.parametrize(
    "line",
    [
        "做同城生意的老板，别再天天拍产品了。",
        "家具店怎么拍视频才有流量？",
        "评论区打出家具，我把整理好的开头发给你。",
    ],
)
def test_talking_to_other_shop_owners_is_rejected_for_consumers(line):
    lines = [*GOOD[:3], line, *GOOD[4:]]
    assert issue(lines) == "peer_talk"
    assert check(lines, brief={**BRIEF, "audience": "peer"}, strict=False)


def test_length_band_and_repetition_are_style_rules_only_when_strict():
    short = GOOD[:4]
    assert issue(short) == "length"
    check(short, strict=False)
    repeated = [*GOOD[:6], *["高端设计就是我们的特点，高端设计看得见。"] * 2, *GOOD[8:]]
    assert issue(repeated) == "repetition"
    # 不限时长：没有字数带
    check(GOOD[:4], words=None)


def test_unbacked_superlatives_forbidden_terms_and_placeholders():
    assert issue([*GOOD[:-1], "全城最好的真皮家具就在这里。"]) == "unbacked"
    assert issue([*GOOD[:-1], "地址在【门店地址】，欢迎来。"]) == "placeholder"
    facts = FACTS.model_copy(update={"forbidden_terms": ["名师"]})
    with pytest.raises(bw.BriefIssue):
        bw.check_brief(draft(), basis(), facts)


def test_benchmark_brands_never_travel_into_the_script():
    analysis = WritingAnalysis.model_construct(
        source_claims=[
            type("Claim", (), {"quote": "源氏木语", "handling": "do_not_copy"})()
        ]
    )
    lines = [*GOOD[:-1], "和源氏木语比起来，我们更看重设计，主页有位置。"]
    with pytest.raises(bw.BriefIssue) as caught:
        bw.check_brief(draft(lines), basis(), FACTS, None, analysis)
    assert caught.value.issue["kind"] == "benchmark_brand"


def test_publish_title_keeps_the_platform_limit():
    assert issue(title="真" * 31).startswith("publish_title")
    check(title="真皮沙发别只看颜色")


@pytest.mark.parametrize("item", BAD["drafts"], ids=lambda d: d["key"])
def test_every_draft_of_the_failed_production_run_is_rejected(item):
    """正式站 c8dbc697 的 8 条成稿：店主向消费者写稿的规则下一条都不能过。"""
    facts = WritingFacts.model_validate(BAD["facts"])
    d = WritingBriefDraft(
        title="反例",
        publish_title=item["publish_title"][:30],
        publish_body=item["publish_body"],
        sentences=[SpokenDraftLine(text=t) for t in item["lines"]],
    )
    with pytest.raises(bw.BriefIssue) as caught:
        bw.check_brief(
            d,
            {"brief": BAD["brief"], "words": list(DURATION_WORDS[45]), "platform": item["platform"]},
            facts,
        )
    assert caught.value.issue["kind"] in {
        "visitor_voice",
        "peer_talk",
        "length",
        "repetition",
        "unbacked",
    }


def test_normalising_splits_sentences_and_cuts_stage_notes():
    lines, removed = bw.normalise_lines(
        ["1. 先说皮。再说设计！（镜头推近）", "#欧式家具 欢迎来店里", "", "嗯"]
    )
    assert lines == ["先说皮。", "再说设计！", "欢迎来店里"]
    assert removed == ["括号里的提示", "口播里的话题标签"]


def test_sentence_repair_only_touches_the_named_lines():
    lines = ["第一句。", "第二句编的。", "第三句。", "第四句也编了。"]
    fixes = {
        "fixes": [
            {"line": 1, "text": "第二句改好了。"},
            {"line": 2, "text": "模型顺手改了第三句"},  # not named: ignored
            {"line": 3, "text": ""},  # named and emptied: deleted
            {"line": 9, "text": "越界"},
        ]
    }
    result, touched = bw.apply_fixes(lines, fixes, {1, 3})
    assert result == ["第一句。", "第二句改好了。", "第三句。"]
    assert touched == [1]
    assert bw.apply_fixes(lines, {"oops": 1}, {1}) == (lines, [])


def test_reviews_map_lines_by_number_or_quote_and_fail_closed_on_problems():
    lines = ["我是老板。", "进门先招呼您喝茶。", "欢迎来店里。"]
    verdicts = bw.parse_reviews(
        {
            "reviews": [
                {
                    "key": "v1",
                    "speaker_ok": True,
                    "audience_ok": True,
                    "on_goal": True,
                    "readable": True,
                    "repetition": 1,
                    "invented": [{"line": 99, "text": "进门先招呼您喝茶", "reason": "服务细节"}],
                    "problems": [],
                },
                {"key": "zzz", "speaker_ok": False},
            ]
        },
        {"v1": lines},
    )
    assert list(verdicts) == ["v1"]
    v = verdicts["v1"]
    assert v["invented"][0]["line"] == 1 and not bw.verdict_passes(v)
    assert bw.flagged_lines(v) == {1: "这句说了用户没写过的内容：服务细节"}
    ok = {**v, "invented": []}
    assert bw.verdict_passes(ok)
    assert not bw.verdict_passes({**ok, "speaker_ok": False})
    assert not bw.verdict_passes({**ok, "repetition": 5})
    assert bw.parse_reviews("not json", {"v1": lines}) == {}


def test_titles_and_openings_that_overlap_are_duplicates():
    a = {"publish_title": "欧式家具怎么选不踩坑？", "lines": ["今天讲讲怎么选。", "先说材质。"]}
    b = {"publish_title": "欧式家具怎么挑不踩坑？先看这家", "lines": ["别急。", "先看一家店。"]}
    c = {"publish_title": "三句话介绍我的店", "lines": ["我是老板。", "店在新恒。"]}
    assert bw.overlap(a["publish_title"], b["publish_title"]) >= 0.5
    assert bw.too_similar(a, b) and not bw.too_similar(a, c)


def test_skeleton_refs_are_labels_mapped_back_and_unknown_labels_dropped():
    labels = {"对标1": "ref-a", "对标2": "ref-b"}
    rows = bw.map_skeletons(
        {
            "skeletons": [
                {"name": "痛点开场", "hook": "痛点提问", "sections": ["痛点", "卖点", "邀约"], "refs": ["对标1", "对标 2"]},
                {"name": "编的", "hook": "x", "sections": ["a", "b"], "refs": ["对标7", "3d7f8c77-uuid"]},
                {"name": "太短", "sections": ["只有一段"], "refs": ["对标1"]},
                {"name": "场景开场", "hook": "未知钩子", "sections": ["场景", "特写", "位置"], "refs": ["对标2"]},
            ]
        },
        labels,
    )
    assert [r["refs"] for r in rows] == [["ref-a", "ref-b"], ["ref-b"]]
    assert rows[1]["hook"] == "其他"
    assert bw.map_skeletons(None, labels) == []


def test_generic_skeletons_cover_every_genre_and_skip_used_ones():
    assert len(GENERIC_SKELETONS) == 8
    assert generic_skeleton("选购避坑")["id"] == "g-guide"
    assert generic_skeleton("选购避坑", {"g-guide"})["id"] == "g-qa"
    assert generic_skeleton("没有这个体裁")["id"] == GENERIC_SKELETONS[0]["id"]


def test_rules_follow_the_brief_and_the_platform():
    rules = "\n".join(brief_draft_rules(BRIEF, {"hook": "场景代入"}, "xiaohongshu", (200, 260)))
    assert "访客视角" in rules and "不得教人怎么拍视频" in rules
    assert "小红书口播" in rules and "200到260字" in rules and "场景代入" in rules
    assert "逐段" not in rules and "replacements" not in rules


def test_skeleton_for_drafting_carries_no_source_wording():
    analysis = {
        "hook": {"type": "痛点提问", "technique": "反问"},
        "sections": [
            {"function": "痛点引入", "explanation": "原文说了源氏木语"},
            {"function": "痛点引入"},
            {"function": "卖点论证"},
        ],
        "expressions": [{"name": "反问", "quote": "原句：源氏木语", "how_to_reuse": "开头反问"}],
    }
    skeleton = bw.skeleton_from_analysis(analysis, "对标标题")
    assert skeleton["sections"] == ["痛点引入", "卖点论证"]
    assert "源氏木语" not in json.dumps(skeleton, ensure_ascii=False)
