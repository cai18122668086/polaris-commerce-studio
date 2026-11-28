"""第三轮自动写稿编排：按角度写、批量质检、只修点名句、去重、重试上限、不自动入库。

The model is faked at ``VideoAssistanceProvider.request``; tasks, documents,
revisions and the run checkpoint are the real ones (SQLite here, PG in CI).
"""

import json
from uuid import uuid4

import pytest

from app import video_auto_writing as auto
from app import video_brief_writing as bw
from app import video_writing_routes
from app.video_assistance_models import VideoAssistanceRecord
from app.video_assistance_provider import VideoAssistanceProvider
from app.video_writing_models import VideoWritingDocument
from tests.test_video_auto_writing import stored

pytest_plugins = ["tests.test_video_auto_writing"]

FACT_CARD = {
    "facts": [
        {"id": "f1", "category": "identity", "label": "店名", "value": "恒志欧式家具店", "status": "user_declared"},
        {"id": "f2", "category": "identity", "label": "位置", "value": "在新恒", "status": "user_declared"},
        {"id": "f3", "category": "product", "label": "风格", "value": "欧式家具", "status": "user_declared"},
        {"id": "f4", "category": "product", "label": "卖点", "value": "高端设计", "status": "user_declared"},
        {"id": "f5", "category": "product", "label": "材质", "value": "真皮家具", "status": "user_declared"},
        {"id": "f6", "category": "product", "label": "设计", "value": "名师设计", "status": "user_declared"},
    ]
}
ANGLES = [
    {"id": "a1", "name": "老板带看镇店款", "hook": "场景代入", "genre": "单品特写", "focus": ["真皮"], "platform": "douyin"},
    {"id": "a2", "name": "真皮怎么分好坏", "hook": "痛点提问", "genre": "选购避坑", "focus": ["真皮"], "platform": "douyin"},
    {"id": "a3", "name": "名师设计值在哪", "hook": "反常识", "genre": "单品特写", "focus": ["名师设计"], "platform": "douyin"},
    {"id": "a4", "name": "三句话介绍我的店", "hook": "结果前置", "genre": "门店介绍", "focus": ["高端设计"], "platform": "douyin"},
]
BRIEF = {
    "version": 1,
    "speaker": "merchant_self",
    "audience": "consumer",
    "goal": "store_visit",
    "category": "欧式真皮家具",
    "locality": "新恒",
    "summary": "你是新恒一家欧式家具店的老板，想让本地准备买家具的人到店看看。",
    "cta": {"action": "visit", "text": ""},
    "duration": 45,
    "word_range": [200, 260],
    "angles": ANGLES,
}

BODY = [
    "我是恒志欧式家具店的老板，店就在新恒。",
    "我们店只做欧式家具，主打真皮家具。",
    "很多人觉得欧式就是花哨，其实好的欧式家具靠的是比例和线条。",
    "我们的款都是名师设计，坐着舒服、看着耐看。",
    "真皮的好坏，光看照片是看不出来的，得用手摸、坐下去感受。",
    "所以我一直跟顾客说，买家具别急着在网上下单。",
    "先想清楚家里的面积和风格，再来店里一件一件对比。",
    "你要是正在准备装修，或者想换一套客厅家具。",
    "周末带上家里的尺寸，来新恒的店里坐一坐、摸一摸，主页有位置。",
]
OPENINGS = {
    "老板带看镇店款": ("今天带你看店里这套沙发", "今天带你看看我店里这一套镇店的沙发，坐下去就知道。"),
    "真皮怎么分好坏": ("真皮好坏，摸一下就知道", "真皮和仿皮到底怎么分？很多人买回家才后悔。"),
    "名师设计值在哪": ("名师设计到底贵在哪", "名师设计到底值在哪里？不是多几个花纹那么简单。"),
    "三句话介绍我的店": ("三句话介绍新恒这家店", "用三句话说清楚我这家店，你就知道值不值得来。"),
}


def script(angle):
    title, opening = OPENINGS[angle]
    return {
        "publish_title": title,
        "publish_body": f"{title}。想看实物的，主页有位置。 #欧式家具 #真皮沙发 #家具店",
        "script": [opening, *BODY],
        "missing": ["店开了几年"],
    }


class Model:
    """Fake planner: answers by what the request is, and records every call."""

    def __init__(self):
        self.calls = []
        self.draft = {}  # angle name → list of answers, one per call
        self.review = {}  # key → verdict dict
        self.recheck_ok = {}
        self.fixes = {}

    def __call__(self, service, owner, method, path, json=None, **_):  # noqa: A002
        messages = json["messages"]
        system, user = messages[0]["content"], messages[1]["content"]
        payload = __import__("json").loads(user)
        if payload.get("task") == "brief_draft":
            angle = payload["angle"]["name"]
            self.calls.append(("draft", angle, len(messages)))
            answers = self.draft.get(angle) or [script(angle)]
            n = sum(1 for c in self.calls if c[:2] == ("draft", angle)) - 1
            content = answers[min(n, len(answers) - 1)]
        elif "check_lines" in system:
            self.calls.append(("recheck", [d["key"] for d in payload["drafts"]]))
            content = {"reviews": [{"key": d["key"], "ok": self.recheck_ok.get(d["key"], True)} for d in payload["drafts"]]}
        elif "审稿编辑" in system:
            self.calls.append(("review", [d["key"] for d in payload["drafts"]]))
            content = {
                "reviews": [
                    {"key": d["key"], **self.review.get(d["key"], {"speaker_ok": True, "audience_ok": True, "on_goal": True, "readable": True, "repetition": 2, "invented": [], "problems": []})}
                    for d in payload["drafts"]
                ]
            }
        elif "只改fix里点名" in system:
            self.calls.append(("repair", [f["line"] for f in payload["fix"]]))
            content = {"fixes": [{"line": f["line"], "text": self.fixes.get(f["line"], "我们只说店里真有的东西。")} for f in payload["fix"]]}
        elif "提炼出2到3个" in system:
            self.calls.append(("compare",))
            content = {"skeletons": []}
        else:
            raise AssertionError(system[:40])
        return {
            "id": str(uuid4()),
            "model": "fake",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 300},
            "choices": [{"message": {"content": __import__("json").dumps(content, ensure_ascii=False)}}],
        }


@pytest.fixture
def brief_run(app_client, monkeypatch):
    app, client, root, project = app_client
    monkeypatch.setattr(video_writing_routes, "verify_writing_package", lambda _: {})
    monkeypatch.setattr(bw, "verify_writing_package", lambda _: {})
    model = Model()
    monkeypatch.setattr(
        VideoAssistanceProvider, "request", lambda service, *a, **k: model(service, *a, **k)
    )
    facts = client.post(
        f"{root}/writing-documents/facts",
        json={"request_id": str(uuid4()), "project_id": project, "body": FACT_CARD},
    )
    assert facts.status_code == 200, facts.text
    facts_id = facts.json()["id"]

    def prep(run, inputs, state=None):
        run.save(brief=BRIEF, facts_document_id=facts_id)

    monkeypatch.setattr(auto, "STEPS", [("facts", prep), ("write", auto.step_write)])

    def go(count=4):
        body = {
            "request_id": str(uuid4()),
            "project_id": project,
            "expected_revision": 1,
            "platform": "douyin",
            "count": count,
            "query": "家具店",
            "facts_text": "恒志欧式家具店，在新恒。欧式家具，高端设计，真皮家具，名师设计。",
        }
        response = client.post(f"{root}/auto-writing", json=body)
        assert response.status_code == 200, response.text
        return stored(app, response.json()["id"])

    return app, client, root, model, go


def library_count(client, root):
    return len(client.get(f"{root}/script-library").json()["items"])


def test_four_angles_four_drafts_one_review_and_nothing_in_the_library(brief_run):
    app, client, root, model, go = brief_run
    row = go()
    assert row.status == "completed", row.result.get("message")
    drafts = row.result["drafts"]
    assert [d["angle"]["name"] for d in drafts] == [a["name"] for a in ANGLES]
    assert [d["label"] for d in drafts] == [a["name"] for a in ANGLES]
    for d in drafts:
        assert d["mode"] == "brief" and d["document_id"] and d["dropped_reason"] is None
        assert d["skeleton"]["kind"] == "generic" and d["skeleton"]["name"]
        assert d["duration"] == 45 and 200 <= d["chars"] <= 260
        assert d["seconds"] == round(d["chars"] / 4.8)
        assert d["quality"]["checked"] and d["quality"]["speaker_ok"]
        assert d["attempts"] == 1
        assert "library_entry_id" not in d
        assert d["notes"]["suggest"] == ["店开了几年"]
    assert [c[0] for c in model.calls].count("review") == 1  # one batch review
    assert library_count(client, root) == 0  # 不再自动入库
    stats = row.result["drafting"]
    assert stats["write_calls"] == 4 and stats["review_calls"] == 1
    assert stats["fix_calls"] == stats["rewrite_calls"] == 0
    assert stats["delivered"] == 4 and stats["dropped"] == 0
    assert stats["prompt_tokens"] == 5000 and stats["completion_tokens"] == 1500
    # Each brief task carries no benchmark text, only the skeleton.
    with app.state.session_factory() as session:
        tasks = session.query(VideoAssistanceRecord).filter_by(kind="fact_draft").all()
        assert len(tasks) == 4
        assert all(t.inputs["draft_mode"] == "brief" and "analysis" not in t.inputs for t in tasks)
        doc = session.get(VideoWritingDocument, drafts[0]["document_id"])
        assert doc.body["draft"]["schema_version"] == "tengli.brief-draft/1"
        assert doc.reference_document_id is None


def test_a_hard_rule_miss_is_corrected_once_inside_the_task(brief_run):
    app, client, root, model, go = brief_run
    visitor = script("真皮怎么分好坏")
    visitor["script"] = [visitor["script"][0], "最近朋友都在推荐这家店，我趁周末去看了看。", *BODY[1:]]
    model.draft["真皮怎么分好坏"] = [visitor, script("真皮怎么分好坏")]
    row = go()
    d = row.result["drafts"][1]
    assert d["document_id"] and d["attempts"] == 2
    corrected = [c for c in model.calls if c[:2] == ("draft", "真皮怎么分好坏")]
    assert [c[2] for c in corrected] == [2, 4]  # the second call carries the correction
    assert row.result["drafting"]["fix_calls"] == 1


def test_review_names_a_line_and_only_that_line_is_rewritten(brief_run):
    app, client, root, model, go = brief_run
    model.review["v3"] = {
        "speaker_ok": True, "audience_ok": True, "on_goal": True, "readable": True, "repetition": 2,
        "invented": [{"line": 4, "text": BODY[3], "reason": "说了没写过的舒适度"}], "problems": [],
    }
    model.fixes = {4: "我们的款都是名师设计，看着耐看。"}
    row = go()
    d = row.result["drafts"][2]
    assert d["document_id"] and d["attempts"] == 2 and d["dropped_reason"] is None
    assert ("repair", [4]) in model.calls and ("recheck", ["v3"]) in model.calls
    with app.state.session_factory() as session:
        doc = session.get(VideoWritingDocument, d["document_id"])
        lines = [s["text"] for s in doc.body["draft"]["sentences"]]
        parent = session.get(VideoWritingDocument, doc.body["revision"]["parent_document_id"])
        before = [s["text"] for s in parent.body["draft"]["sentences"]]
    assert lines[4] == "我们的款都是名师设计，看着耐看。"
    assert [x for i, x in enumerate(lines) if i != 4] == [x for i, x in enumerate(before) if i != 4]
    assert any("没写过" in n for n in d["notes"]["removed"])


def test_a_repair_that_still_fails_the_recheck_is_dropped_not_hidden(brief_run):
    app, client, root, model, go = brief_run
    model.review["v1"] = {
        "speaker_ok": True, "audience_ok": True, "on_goal": True, "readable": True, "repetition": 2,
        "invented": [{"line": 2, "text": BODY[1], "reason": "编的"}], "problems": [],
    }
    model.recheck_ok["v1"] = False
    row = go()
    d = row.result["drafts"][0]
    assert d["document_id"] is None and d["dropped_reason"] == "quality"
    assert d["dropped_message"] and "没写过" in d["dropped_message"]
    assert d["dropped_document_id"]  # kept for 「仍然保留」
    assert row.result["drafting"]["delivered"] == 3


def test_a_near_duplicate_is_rewritten_once_on_another_skeleton(brief_run):
    app, client, root, model, go = brief_run
    twin = script("老板带看镇店款")
    model.draft["三句话介绍我的店"] = [twin, script("三句话介绍我的店")]
    row = go()
    d = row.result["drafts"][3]
    assert d["document_id"] and d["attempts"] == 2 and d["dropped_reason"] is None
    with app.state.session_factory() as session:
        title = session.get(VideoWritingDocument, d["document_id"]).body["draft"]["publish_title"]
    assert title == "三句话介绍新恒这家店"
    assert row.result["drafting"]["rewrite_calls"] == 1


def test_never_more_than_three_calls_for_one_draft(brief_run):
    app, client, root, model, go = brief_run
    bad = script("名师设计值在哪")
    bad["script"] = [bad["script"][0], "我们店开了十年。", *BODY]
    model.draft["名师设计值在哪"] = [bad]
    row = go()
    d = row.result["drafts"][2]
    assert d["document_id"] is None and d["dropped_reason"] == "failed"
    assert "数字" in d["dropped_message"] and "dropped_document_id" not in d
    assert d["attempts"] == 3
    # the task's write + correction, then one rewrite on another skeleton
    assert len([c for c in model.calls if c[:2] == ("draft", "名师设计值在哪")]) == 3
    assert row.status == "completed"


def test_too_little_to_say_is_reported_as_insufficient_facts(brief_run):
    app, client, root, model, go = brief_run
    short = script("老板带看镇店款")
    short["script"] = short["script"][:3]
    model.draft["老板带看镇店款"] = [short]
    row = go()
    d = row.result["drafts"][0]
    assert d["dropped_reason"] == "insufficient_facts" and d["document_id"] is None


def test_review_call_failing_delivers_drafts_marked_unchecked(brief_run, monkeypatch):
    app, client, root, model, go = brief_run
    original = model.__call__

    def broken(service, owner, method, path, json=None, **kw):  # noqa: A002
        if "审稿编辑" in json["messages"][0]["content"]:
            return {"usage": None, "choices": [{"message": {"content": "不是JSON"}}]}
        return original(service, owner, method, path, json=json, **kw)

    monkeypatch.setattr(VideoAssistanceProvider, "request", broken)
    row = go()
    assert all(d["document_id"] and d["quality"]["checked"] is False for d in row.result["drafts"])


def test_all_drafts_failing_stops_the_run_and_resume_keeps_the_brief_path(brief_run):
    app, client, root, model, go = brief_run
    bad = {"publish_title": "x", "publish_body": "", "script": ["我们店开了十年。"]}
    for angle in OPENINGS:
        model.draft[angle] = [bad]
    row = go(count=2)
    assert (row.status, row.error_code) == ("failed", "VIDEO_AUTO_DRAFTS_FAILED")
    model.draft.clear()
    resumed = client.post(f"{root}/auto-writing/{row.id}/resume")
    assert resumed.status_code == 200
    row = stored(app, row.id)
    assert row.status == "completed"
    assert all(d["document_id"] and d["mode"] == "brief" for d in row.result["drafts"])


def test_a_brief_draft_can_be_edited_line_by_line(brief_run):
    app, client, root, model, go = brief_run
    row = go(count=1)
    doc = row.result["drafts"][0]["document_id"]
    lines = [{"text": t, "fact_ids": []} for t in [*BODY, "欢迎来看看。"]]
    ok = client.post(
        f"{root}/writing-documents/{doc}/revise",
        json={"request_id": str(uuid4()), "title": "改过的", "sentences": lines},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["body"]["draft"]["schema_version"] == "tengli.brief-draft/1"
    bad = client.post(
        f"{root}/writing-documents/{doc}/revise",
        json={"request_id": str(uuid4()), "title": "改过的", "sentences": [*lines, {"text": "我们开了十年。", "fact_ids": []}]},
    )
    assert bad.status_code == 422 and "年" in bad.json()["error"]["message"]
    assert library_count(client, root) == 0


def test_without_a_brief_the_old_writer_runs_unchanged(app_client, monkeypatch):
    """开关关（run 没有 brief）：step_write 走 b2199c02 的旧路径，照旧入库。"""
    called = []
    monkeypatch.setattr(
        "app.video_auto_drafting.step_write_brief", lambda *a: called.append(a)
    )
    state = {"benchmarks": [], "facts_document_id": "x", "main_reference_id": "m"}

    class FakeRun:
        id = "r"

        def save(self, **values):
            raise auto.Stop("X", "旧路径")

    with pytest.raises(auto.Stop):
        auto.step_write(FakeRun(), {"platform": "douyin", "query": "q", "project_id": "p"}, state)
    assert called == []


def test_skeleton_payload_is_small(brief_run):
    """写稿请求只带简报、角度、事实和骨架：远小于旧的整份拆解 + 原文（约 8000 token）。"""
    app, client, root, model, go = brief_run
    captured = []
    original = model.__call__

    def spy(service, owner, method, path, json=None, **kw):  # noqa: A002
        if '"brief_draft"' in json["messages"][1]["content"]:
            captured.append(json["messages"][1]["content"])
        return original(service, owner, method, path, json=json, **kw)

    import app.video_assistance_provider as vap

    vap.VideoAssistanceProvider.request = spy  # restored by monkeypatch teardown
    go(count=1)
    assert captured and len(captured[0]) < 6000
    payload = json.loads(captured[0])
    assert set(payload) >= {"brief", "angle", "facts", "skeleton", "rules", "word_range"}
    assert "reference" not in payload and "analysis" not in payload
