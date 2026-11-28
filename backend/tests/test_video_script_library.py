"""v3 文案三件套：标题 + 发布正文 + 口播稿的校验、纠错重试、自动入库与文案库接口."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app import video_script_library as library
from app import video_writing_provider as provider
from app.video_writing_contracts import (
    WritingAnalysis,
    WritingFacts,
    WritingReference,
    WritingStructureDraft,
)
from app.video_writing_models import VideoScriptLibraryEntry, VideoWritingDocument
from app.video_writing_provider import validate_draft
from tests.test_video_projects import base, payload

pytest_plugins = ["tests.test_video_projects"]

DATA = json.loads(
    (Path(__file__).parent / "fixtures/writing_fact_draft_hand_cream.json").read_text(
        "utf-8"
    )
)
METRICS = {
    "platform": "xiaohongshu",
    "title": "冬天必备樱花护手霜香到犯规真的绝了",
    "author_name": "小美爱分享",
}
GOOD_TITLE = "冬天手干？这支樱花香护手霜太香了"
GOOD_BODY = (
    "冬天手一干就起皮，试了这支樱花香护手霜，淡淡樱花香，清爽不黏腻，吸收快🌸\n\n"
    "#护手霜 #冬季护手 #好物分享 #樱花香"
)


def reference(**metrics):
    body = copy.deepcopy(DATA["reference"])
    body["source_metrics"] = {**METRICS, **metrics}
    return WritingReference.model_validate(body)


def facts():
    return WritingFacts.model_validate(DATA["facts"])


def analysis():
    return WritingAnalysis.model_validate(DATA["analysis"])


def draft(**changes):
    body = copy.deepcopy(DATA["accepted_draft"])
    body.update(publish_title=GOOD_TITLE, publish_body=GOOD_BODY)
    body.update(changes)
    return WritingStructureDraft.model_validate(body)


def publish(d, platform="xiaohongshu", ref=None):
    ref = ref or reference()
    text = validate_draft(d, ref, facts(), analysis())
    provider.validate_publish(d, platform, ref, facts(), analysis(), text)
    return d


# ------------------------------------------------------------ validation ----


def test_a_complete_title_body_and_script_pass():
    d = publish(draft())
    assert d.publish_title == GOOD_TITLE
    assert d.publish_body.endswith("#樱花香")


def test_the_title_limit_follows_the_platform():
    long_title = "冬天手干到起皮的姐妹一定要试试这支樱花香护手霜"  # 23 字
    assert provider.visible_length(long_title) == 23
    with pytest.raises(provider.PublishIssue) as caught:
        publish(draft(publish_title=long_title), "xiaohongshu")
    assert caught.value.issue["kind"] == "publish_title_length"
    assert "最多20个字" in caught.value.hint
    publish(draft(publish_title=long_title), "douyin")  # 抖音上限 30
    with pytest.raises(provider.PublishIssue):
        publish(draft(publish_title=long_title * 2), "douyin")


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ("冬天手一干就起皮，试了这支樱花香护手霜，淡淡樱花香。", "publish_tags"),
        ("冬天手干，试试这支。#护手霜 #冬季护手", "publish_tags"),
        ("#护手霜 #冬季护手 #好物分享", "publish_body_empty"),
    ],
)
def test_the_body_needs_text_and_three_to_six_hashtags(body, kind):
    with pytest.raises(provider.PublishIssue) as caught:
        publish(draft(publish_body=body))
    assert caught.value.issue["kind"] == kind


def test_more_than_six_hashtags_are_cut_to_six_with_a_note():
    body = "樱花香护手霜，清爽不黏腻。\n" + " ".join(f"#话题{i}" for i in range(9))
    d = publish(draft(publish_body=body))
    assert d.publish_body.count("#") == 6 and "#话题6" not in d.publish_body
    assert any("已保留前6个" in w for w in d.warnings)
    # Repeated tags count once; after the cut there are still 3-6.
    body = "樱花香护手霜，清爽不黏腻。\n" + " ".join(
        ["#护手霜"] * 4 + ["#冬季", "#好物"]
    )
    d = publish(draft(publish_body=body))
    assert len(set(provider.HASHTAG.findall(d.publish_body))) == 3
    assert not any("已保留前6个" in w for w in d.warnings)


def test_a_title_may_not_carry_hashtags():
    with pytest.raises(provider.PublishIssue) as caught:
        publish(draft(publish_title="樱花香护手霜 #护手霜"))
    assert caught.value.issue["kind"] == "publish_title_tag"


def test_benchmark_brands_never_reach_title_body_or_script():
    # 「舒肤佳」 is only inside a long source quote; the model lists it itself.
    title = "舒肤佳同款香味的护手霜"
    with pytest.raises(provider.PublishIssue) as caught:
        publish(draft(publish_title=title, benchmark_brands=["舒肤佳"]))
    assert caught.value.issue == {"kind": "publish_brand", "index": 0, "text": "舒肤佳"}
    d = draft(benchmark_brands=["舒肤佳"])
    d.sentences[0].text += "香味像舒肤佳。"
    with pytest.raises(provider.PublishIssue, match="benchmark brand"):
        publish(d)
    # A listed name that is not in the benchmark (the user's own) is dropped.
    d = publish(draft(benchmark_brands=["樱花香护手霜", "小熊"]))
    assert d.benchmark_brands == []


def test_the_benchmark_author_and_title_are_not_copied():
    with pytest.raises(provider.PublishIssue) as caught:
        publish(draft(publish_body="小美爱分享同款，" + GOOD_BODY))
    assert caught.value.issue["kind"] == "publish_source_claim"
    with pytest.raises(provider.PublishIssue) as caught:
        publish(draft(publish_body="樱花护手霜香到犯规真的绝了！" + GOOD_BODY))
    assert caught.value.issue["kind"] == "publish_source_title"


def test_numbers_and_restricted_claims_need_the_users_facts():
    with pytest.raises(provider.PublishIssue) as caught:
        publish(draft(publish_title="只要56块的樱花香护手霜"))
    assert caught.value.issue["kind"] == "publish_numeric"
    card = facts().model_copy(deep=True)
    card.forbidden_terms = ["犯规"]
    d = draft(publish_body="香到犯规。" + GOOD_BODY)
    text = validate_draft(d, reference(title=""), card, analysis())
    with pytest.raises(provider.PublishIssue) as caught:
        provider.validate_publish(
            d, "xiaohongshu", reference(title=""), card, analysis(), text
        )
    assert caught.value.issue["kind"] == "publish_forbidden"
    with pytest.raises(provider.PublishIssue) as caught:  # 事实卡要求不写功效
        publish(draft(publish_body="用了能治疗手裂。" + GOOD_BODY))
    assert caught.value.issue["kind"] == "publish_restricted"


@pytest.mark.parametrize(
    "body",
    [
        "樱花香护手霜，清爽不黏腻。#护手霜 #平价好物 #冬季护手",  # 真实运行里出现过
        "销量第一的樱花香护手霜。#护手霜 #好物 #冬季护手",
        "樱花香护手霜，清爽不黏腻。#护手霜 #冬季护手 #医生推荐",
    ],
)
def test_price_ranking_and_endorsement_words_need_the_users_facts(body):
    with pytest.raises(provider.PublishIssue) as caught:
        publish(draft(publish_body=body))
    assert caught.value.issue["kind"] == "publish_unbacked"
    assert "没有依据" in caught.value.hint
    card = facts().model_copy(deep=True)
    card.facts[2].value = "清爽不黏腻，吸收快，平价"  # the user said it: allowed
    d = draft(publish_body="樱花香护手霜，平价好用。#护手霜 #平价好物 #冬季护手")
    text = validate_draft(d, reference(), card, analysis())
    provider.validate_publish(d, "xiaohongshu", reference(), card, analysis(), text)


def test_old_drafts_without_title_or_body_still_load():
    old = WritingStructureDraft.model_validate(DATA["accepted_draft"])
    assert old.publish_title == "" and old.publish_body == ""
    assert "樱花香护手霜" in validate_draft(old, reference(), facts(), analysis())


# ------------------------------------------------- one call, one retry ------


def service(tmp_path, contents, calls):
    def request(*_, **kwargs):
        calls.append(copy.deepcopy(kwargs["json"]["messages"]))
        return {"choices": [{"message": {"content": contents[len(calls) - 1]}}]}

    return SimpleNamespace(
        settings=SimpleNamespace(
            video_writing_workflow_enabled=True,
            video_writing_library_dir=tmp_path,
            video_script_model="deepseek-v4.1-flash-1017",
            video_editing_tasks_dir=tmp_path,
        ),
        request=request,
    )


def inputs(**extra):
    ref = DATA["reference"] | {"source_metrics": METRICS}
    return {
        "reference": ref,
        "facts": DATA["facts"],
        "analysis": DATA["analysis"],
        "draft_mode": "structure",
        "writing_task_id": str(uuid4()),
        **extra,
    }


def dumped(**changes):
    return draft(**changes).model_dump_json()


@pytest.mark.parametrize(
    ("bad", "hint"),
    [
        (
            {"publish_title": "冬天手干到起皮的姐妹一定要试试这支樱花香护手霜"},
            "最多20个字",
        ),
        ({"publish_body": "冬天手干，试试樱花香护手霜。"}, "3到6个"),
        (
            {"publish_title": "舒肤佳同款香味的护手霜", "benchmark_brands": ["舒肤佳"]},
            "舒肤佳",
        ),
    ],
)
def test_one_call_writes_all_three_and_a_bad_title_or_body_is_corrected_once(
    tmp_path, monkeypatch, bad, hint
):
    monkeypatch.setattr(provider, "verify_writing_package", lambda _: {})
    calls = []
    svc = service(tmp_path, [dumped(**bad), dumped()], calls)
    result, receipt = provider.plan_writing(
        svc, "fact_draft", inputs(publish_platform="xiaohongshu")
    )
    assert not result.get("validation_error"), result
    assert result["draft"]["publish_title"] == GOOD_TITLE
    assert "#护手霜" in result["draft"]["publish_body"]
    assert "樱花香护手霜" in result["text"]
    assert len(receipt["attempts"]) == 2  # 同一次写稿：一次纠错重试
    first = json.loads(calls[0][1]["content"])
    assert any("publish_title" in rule for rule in first["rules"])
    assert "publish_title" in first["output_schema"]["properties"]
    assert first["publish_platform"] == "xiaohongshu"
    assert hint in calls[1][-1]["content"]


def test_a_title_still_wrong_after_the_retry_is_rejected_not_saved(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(provider, "verify_writing_package", lambda _: {})
    bad = dumped(publish_title="冬天手干到起皮的姐妹一定要试试这支樱花香护手霜")
    result, receipt = provider.plan_writing(
        service(tmp_path, [bad, bad], []),
        "fact_draft",
        inputs(publish_platform="xiaohongshu"),
    )
    assert result["validation_error"] == "VIDEO_WRITING_EVIDENCE_INVALID"
    assert result["validation_issue"]["kind"] == "publish_title_length"
    assert len(receipt["attempts"]) == 2


def test_requests_from_before_v3_are_not_asked_for_a_title(tmp_path, monkeypatch):
    monkeypatch.setattr(provider, "verify_writing_package", lambda _: {})
    calls = []
    old = WritingStructureDraft.model_validate(DATA["accepted_draft"])
    result, _ = provider.plan_writing(
        service(tmp_path, [old.model_dump_json()], calls), "fact_draft", inputs()
    )
    assert not result.get("validation_error")
    assert not any(
        "publish_title" in r for r in json.loads(calls[0][1]["content"])["rules"]
    )


# ------------------------------------------------------- library / API ------


@pytest.fixture
def flow(video, monkeypatch):
    """A project with reference, teardown and facts saved; drafts from a fake."""
    client, auth, ws, user, settings = video
    settings.video_writing_workflow_enabled = True
    settings.video_script_planning_enabled = True
    monkeypatch.setattr("app.video_writing_routes.verify_writing_package", lambda _: {})
    ref = reference()
    state = {"draft": draft()}

    class FakeWriting:
        calls = []

        def plan(self, kind, task_inputs):
            self.calls.append((kind, task_inputs))
            if kind == "ref_analysis":
                return {"analysis": DATA["analysis"]}, {}
            d = state["draft"].model_copy(deep=True)
            text = validate_draft(d, ref, facts(), analysis())
            return {
                "draft": d.model_dump(mode="json"),
                "text": text,
                "shape_check": {"verdict": "PASS"},
            }, {}

    fake = FakeWriting()
    client.app.state.video_assistance_provider = fake
    url = base(ws)
    pid = str(uuid4())
    body = payload("原草稿")
    body["content"]["references"][0].update(
        id=str(ref.reference_id), original_text=ref.original_text
    )
    client.put(f"{url}/projects/{pid}", json=body).raise_for_status()
    rid = (
        client.post(
            f"{url}/writing-documents/reference",
            json={
                "request_id": str(uuid4()),
                "project_id": pid,
                "expected_revision": 1,
                "reference_id": str(ref.reference_id),
            },
        )
        .raise_for_status()
        .json()["id"]
    )
    fid = (
        client.post(
            f"{url}/writing-documents/facts",
            json={
                "request_id": str(uuid4()),
                "project_id": pid,
                "body": DATA["facts"],
            },
        )
        .raise_for_status()
        .json()["id"]
    )
    task = client.post(
        f"{url}/writing-tasks",
        json={
            "request_id": str(uuid4()),
            "project_id": pid,
            "expected_revision": 1,
            "kind": "ref_analysis",
            "reference_document_id": rid,
        },
    ).json()
    aid = (
        client.post(
            f"{url}/writing-documents/result",
            json={"request_id": str(uuid4()), "task_id": task["id"]},
        )
        .raise_for_status()
        .json()["id"]
    )

    def write(platform="xiaohongshu", variant=0):
        job = client.post(
            f"{url}/writing-tasks",
            json={
                "request_id": str(uuid4()),
                "project_id": pid,
                "expected_revision": 1,
                "kind": "fact_draft",
                "reference_document_id": rid,
                "analysis_document_id": aid,
                "facts_document_id": fid,
                "draft_mode": "structure",
                "variant": variant,
                "platform": platform,
            },
        )
        assert job.status_code == 200, job.text
        return job.json()["id"]

    return SimpleNamespace(
        client=client,
        url=url,
        pid=pid,
        user=user,
        ws=ws,
        write=write,
        state=state,
        fake=fake,
    )


def save(flow, task_id, request_id=None):
    saved = flow.client.post(
        f"{flow.url}/writing-documents/result",
        json={"request_id": request_id or task_id, "task_id": task_id},
    )
    assert saved.status_code == 200, saved.text
    doc = saved.json()
    assert "library_entry_id" not in doc  # the document response is unchanged
    with flow.client.app.state.session_factory() as session:
        entry = session.scalar(
            select(VideoScriptLibraryEntry).where(
                VideoScriptLibraryEntry.writing_document_id == doc["id"]
            )
        )
    return {**doc, "library_entry_id": entry.id if entry else None}


def listed(flow, **params):
    page = flow.client.get(f"{flow.url}/script-library", params=params)
    assert page.status_code == 200, page.text
    return page.json()


def test_a_saved_draft_is_in_the_library_once_with_all_three_parts(flow):
    task = flow.write("xiaohongshu")
    platform = flow.fake.calls[-1][1]["publish_platform"]
    assert platform == "xiaohongshu"
    saved = save(flow, task)
    entry_id = saved["library_entry_id"]
    # Saved again (page refresh, the manual hook re-reading, another request id)
    assert save(flow, task)["library_entry_id"] == entry_id
    # A second document for the same task (new request id) is still one entry:
    # the key is the task (run + version), not the document.
    save(flow, task, str(uuid4()))
    page = listed(flow)
    assert page["total"] == 1 and len(listed(flow)["items"]) == 1
    item = page["items"][0]
    assert item["id"] == entry_id and item["source"] == "manual"
    assert item["platform"] == "xiaohongshu"
    assert item["publish_title"] == GOOD_TITLE
    assert item["publish_body"] == GOOD_BODY
    assert "樱花香护手霜" in item["script"]
    assert item["display_title"] == GOOD_TITLE
    assert item["script_chars"] > 20 and item["script_seconds"] >= 5
    assert (
        item["benchmark_refs"][0]["reference_document_id"]
        == saved["reference_document_id"]
    )


def test_auto_runs_are_keyed_by_run_and_version(flow):
    task = flow.write("douyin")
    from app.video_writing_contracts import SaveWritingResult
    from app.video_writing_routes import store_result

    request = SimpleNamespace(app=flow.client.app)
    workspace = SimpleNamespace(
        workspace_id=flow.ws,
        principal=SimpleNamespace(user_id=flow.user),
        role="owner",
    )
    ids = set()
    for _ in range(2):  # a resumed run saves the same version again
        with flow.client.app.state.session_factory() as session:
            saved = store_result(
                SaveWritingResult(request_id=task, task_id=task),
                request,  # type: ignore[arg-type]
                workspace,  # type: ignore[arg-type]
                session,
                library_source="auto_writing",
                library_key="auto:run-1:v1",
            )
            ids.add(saved["library_entry_id"])
    # The manual page reading the same finished task does not add a copy.
    ids.add(save(flow, task)["library_entry_id"])
    assert len(ids) == 1
    [item] = listed(flow)["items"]
    assert item["source"] == "auto_writing" and item["platform"] == "douyin"
    with flow.client.app.state.session_factory() as session:
        row = session.scalar(select(VideoScriptLibraryEntry))
        assert row.dedupe_key == "auto:run-1:v1"


def test_batch_by_ids_keeps_order_and_names_what_is_missing(flow):
    first = save(flow, flow.write(variant=0))["library_entry_id"]
    second = save(flow, flow.write(variant=1))["library_entry_id"]
    third = save(flow, flow.write(variant=2))["library_entry_id"]
    unknown = str(uuid4())
    page = listed(flow, ids=f"{third},{first},{unknown},{second}")
    assert [i["id"] for i in page["items"]] == [third, first, second]
    assert page["missing_ids"] == [unknown]
    with flow.client.app.state.session_factory() as session:
        doc = session.get(VideoScriptLibraryEntry, second).writing_document_id
    by_doc = listed(flow, documents=f"{doc},{uuid4()}")
    assert [i["id"] for i in by_doc["items"]] == [second]
    assert (
        flow.client.get(
            f"{flow.url}/script-library",
            params={"ids": ",".join(["a"] * 1 + [str(uuid4()) for _ in range(51)])},
        ).status_code
        == 422
    )
    assert listed(flow, limit=2)["total"] == 3
    assert len(listed(flow, limit=2)["items"]) == 2


def test_editing_is_a_new_version_of_the_same_entry(flow):
    entry = save(flow, flow.write())["library_entry_id"]
    url = f"{flow.url}/script-library/{entry}"
    change = {
        "expected_revision": 1,
        "publish_title": "手干星人看过来",
        "publish_body": "樱花香护手霜。#护手霜 #冬季 #好物",
        "script": "冬天手干？试试樱花香护手霜。",
    }
    updated = flow.client.put(url, json=change)
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2 and updated.json()["id"] == entry
    assert flow.client.put(url, json=change).json()["revision"] == 2  # repeated save
    stale = flow.client.put(url, json={**change, "script": "另一处的改动。"})
    assert stale.status_code == 409
    assert listed(flow)["total"] == 1
    assert flow.client.get(url).json()["publish_title"] == "手干星人看过来"
    with flow.client.app.state.session_factory() as session:
        row = session.get(VideoScriptLibraryEntry, entry)
        assert row.history[0]["publish_title"] == GOOD_TITLE
    assert flow.client.delete(url).json()["deleted"] is True
    assert flow.client.get(url).status_code == 404
    assert listed(flow)["total"] == 0
    assert listed(flow, ids=entry)["missing_ids"] == [entry]


def test_a_revised_draft_updates_its_entry(flow):
    saved = save(flow, flow.write())
    with flow.client.app.state.session_factory() as session:
        workspace = SimpleNamespace(
            workspace_id=flow.ws, principal=SimpleNamespace(user_id=flow.user)
        )
        revised = SimpleNamespace(
            id=saved["reference_document_id"],  # any real document id
            body={"text": "改过的口播。", "draft": {"publish_title": "改过的标题"}},
        )
        row = library.follow_revision(session, workspace, saved["id"], revised)  # type: ignore[arg-type]
        assert row is not None and row.revision == 2
    [item] = listed(flow)["items"]
    assert item["id"] == saved["library_entry_id"]
    assert item["script"] == "改过的口播。" and item["publish_title"] == "改过的标题"
    assert item["publish_body"] == GOOD_BODY


def test_search_and_platform_filter(flow):
    save(flow, flow.write("xiaohongshu", 0))
    flow.state["draft"] = draft(
        publish_title="一支护手霜过冬",
        publish_body="手不干了，冬天放心出门。#护手霜 #冬天 #日常",
    )
    save(flow, flow.write("douyin", 1))
    assert listed(flow, platform="douyin")["total"] == 1
    assert listed(flow, platform="xiaohongshu")["total"] == 1
    assert [i["publish_title"] for i in listed(flow, q="过冬")["items"]] == [
        "一支护手霜过冬"
    ]
    assert listed(flow, q="#冬季护手")["total"] == 1  # 正文关键字
    assert listed(flow, q="100%")["total"] == 0


def test_old_library_copies_without_title_show_and_are_never_duplicated(video):
    client, auth, ws, user, settings = video
    url = base(ws)
    pid = str(uuid4())
    body = payload("冬天手干怎么办？试试这支护手霜。真的很好用。", action="library")
    body["content"]["draft"]["name"] = "未命名视频"
    assert client.put(f"{url}/projects/{pid}", json=body).status_code == 200
    named = payload("第二条文案。", revision=1, action="library")
    assert client.put(f"{url}/projects/{pid}", json=named).status_code == 200
    first = client.get(f"{url}/script-library").json()
    again = client.get(f"{url}/script-library").json()
    assert first["total"] == again["total"] == 2
    untitled = next(i for i in first["items"] if i["publish_title"] == "")
    assert untitled["display_title"] == "冬天手干怎么办"
    assert untitled["publish_body"] == "" and untitled["platform"] == ""
    assert untitled["source"] == "manual"
    detail = client.get(f"{url}/script-library/{untitled['id']}")
    assert detail.status_code == 200 and detail.json()["script"].startswith("冬天手干")
    titled = next(i for i in first["items"] if i["publish_title"])
    assert titled["publish_title"] == "演示产品"
    # Deleting a mirrored copy keeps it deleted on the next read.
    client.delete(f"{url}/script-library/{untitled['id']}").raise_for_status()
    assert client.get(f"{url}/script-library").json()["total"] == 1


def test_a_manual_entry_is_created_once_per_request(video):
    client, auth, ws, user, settings = video
    url = base(ws)
    body = {
        "request_id": str(uuid4()),
        "platform": "douyin",
        "publish_title": "自己写的",
        "publish_body": "",
        "script": "自己写的口播稿。",
    }
    one = client.post(f"{url}/script-library", json=body).json()
    two = client.post(f"{url}/script-library", json=body).json()
    assert one["id"] == two["id"]
    assert client.get(f"{url}/script-library").json()["total"] == 1
    assert (
        client.post(f"{url}/script-library", json={**body, "script": " "}).status_code
        == 422
    )


def test_a_concurrent_first_read_returns_the_winners_row_not_an_error():
    """The second of two first reads hits the unique legacy id and re-reads."""
    from sqlalchemy.exc import IntegrityError

    winner = SimpleNamespace(id="winner")

    class RacingSession:
        def __init__(self):
            self.found = [None, winner]  # before insert: none; after the loss: it
            self.rolled_back = False

        def scalar(self, _query):
            return self.found.pop(0)

        def add(self, _row):
            pass

        def commit(self):
            raise IntegrityError(
                "INSERT", {}, Exception("uq_video_script_library_legacy")
            )

        def rollback(self):
            self.rolled_back = True

    session = RacingSession()
    workspace = SimpleNamespace(
        workspace_id="w", principal=SimpleNamespace(user_id="u")
    )
    row = library.insert_once(
        session,  # type: ignore[arg-type]
        workspace,  # type: ignore[arg-type]
        SimpleNamespace(id="loser"),  # type: ignore[arg-type]
        VideoScriptLibraryEntry.legacy_version_id == "v1",
    )
    assert row is winner and session.rolled_back


def test_mirroring_failure_does_not_take_the_library_down(video, monkeypatch):
    client, auth, ws, user, settings = video
    url = base(ws)
    created = client.post(
        f"{url}/script-library",
        json={"request_id": str(uuid4()), "script": "已经在新库里的文案。"},
    )
    assert created.status_code == 200
    pid = str(uuid4())
    body = payload("还没镜像的旧文案。", action="library")
    assert client.put(f"{url}/projects/{pid}", json=body).status_code == 200

    def broken(*_args, **_kwargs):
        raise IntegrityError("INSERT", {}, Exception("boom"))

    from sqlalchemy.exc import IntegrityError

    monkeypatch.setattr(library, "insert_once", broken)
    page = client.get(f"{url}/script-library")
    assert page.status_code == 200
    assert [i["script"] for i in page.json()["items"]] == ["已经在新库里的文案。"]
    monkeypatch.undo()
    assert client.get(f"{url}/script-library").json()["total"] == 2  # mirrored later


def test_an_old_version_is_stored_once_by_its_document(flow):
    """「存入文案库」on a version written before auto-ingest: one entry per
    document, whatever request id, click count or reload; removed then stored
    again comes back; someone else's or a missing document is refused."""
    doc = save(flow, flow.write("xiaohongshu"))
    with flow.client.app.state.session_factory() as session:  # 改版前：没入库
        session.delete(session.get(VideoScriptLibraryEntry, doc["library_entry_id"]))
        session.commit()
    assert listed(flow, documents=doc["id"])["items"] == []
    body = {
        "script": "旧版本的口播稿。",
        "platform": "xiaohongshu",
        "writing_document_id": doc["id"],
        "source": "auto_writing",
    }
    url = f"{flow.url}/script-library"
    first = flow.client.post(url, json={**body, "request_id": str(uuid4())})
    assert first.status_code == 200, first.text
    again = flow.client.post(url, json={**body, "request_id": str(uuid4())}).json()
    assert again["id"] == first.json()["id"]
    [item] = listed(flow, documents=doc["id"])["items"]
    assert item["writing_document_id"] == doc["id"]
    assert item["source"] == "auto_writing" and item["platform"] == "xiaohongshu"
    assert item["project_id"] == flow.pid and item["benchmark_refs"]
    assert listed(flow)["total"] == 1

    flow.client.delete(f"{url}/{item['id']}").raise_for_status()
    back = flow.client.post(url, json={**body, "request_id": str(uuid4())}).json()
    assert back["id"] == item["id"] and listed(flow)["total"] == 1

    missing = flow.client.post(
        url,
        json={**body, "request_id": str(uuid4()), "writing_document_id": str(uuid4())},
    )
    assert missing.status_code == 404
    # A document that is not a draft (the reference) cannot be stored.
    with flow.client.app.state.session_factory() as session:
        ref_id = session.get(VideoWritingDocument, doc["id"]).reference_document_id
    refused = flow.client.post(
        url, json={**body, "request_id": str(uuid4()), "writing_document_id": ref_id}
    )
    assert refused.status_code == 404


def test_an_auto_saved_version_is_not_stored_twice(flow):
    doc = save(flow, flow.write("douyin"))
    stored = flow.client.post(
        f"{flow.url}/script-library",
        json={
            "request_id": str(uuid4()),
            "script": "别的字",
            "platform": "douyin",
            "writing_document_id": doc["id"],
        },
    ).json()
    assert stored["id"] == doc["library_entry_id"]
    assert listed(flow)["total"] == 1
