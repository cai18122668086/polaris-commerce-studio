"""第三轮 D 线：勾选入库（batch）、批量删除、按批次/来源筛选、开关下不自动入库."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.models import WorkspaceMemberRecord, utc_now
from app.video_assistance_models import VideoAssistanceRecord
from app.video_writing_models import VideoScriptLibraryEntry, VideoWritingDocument
from tests.test_auth_external import verified_identity
from tests.test_video_projects import EMAIL
from tests.test_video_script_library import listed
from tests.test_video_work_items import batch_body, item

pytest_plugins = ["tests.test_video_projects", "tests.test_video_script_library"]


def turn_on(flow, users=None):
    settings = flow.client.app.state.settings
    settings.video_writing_brief_v2 = True
    settings.video_writing_brief_v2_users = ",".join(users or [flow.user])


def saved_doc(flow, platform="douyin", variant=0):
    """A checked draft saved as a document (the auto flow saves every one)."""
    task = flow.write(platform, variant)
    saved = flow.client.post(
        f"{flow.url}/writing-documents/result",
        json={"request_id": task, "task_id": task},
    )
    assert saved.status_code == 200, saved.text
    return saved.json()["id"]


def library_count(flow):
    with flow.client.app.state.session_factory() as session:
        return session.scalar(
            select(func.count()).where(VideoScriptLibraryEntry.deleted_at.is_(None))
        )


def store(flow, ids, **extra):
    return flow.client.post(
        f"{flow.url}/script-library/batch", json={"document_ids": ids, **extra}
    )


def fake_run(flow, drafts, query="家具店", brief=None, created_at=None):
    run_id = str(uuid4())
    with flow.client.app.state.session_factory() as session:
        row = VideoAssistanceRecord(
            id=run_id,
            workspace_id=flow.ws,
            owner_user_id=flow.user,
            project_id=flow.pid,
            request_id=str(uuid4()),
            request_hash="x",
            kind="auto_writing",
            status="completed",
            stage="done",
            inputs={"query": query},
            result={
                "drafts": drafts,
                "request": {"query": query},
                **({"brief": brief} if brief else {}),
            },
        )
        if created_at is not None:
            row.created_at = created_at
        session.add(row)
        session.commit()
    return run_id


def as_other_user(video, ws):
    client, auth = video[0], video[1]
    auth.identity = verified_identity(primary_user_id="library-other", email=EMAIL)
    other = client.get("/api/v1/me").json()["id"]
    with client.app.state.session_factory() as session:
        if session.get(WorkspaceMemberRecord, (ws, other)) is None:
            session.add(
                WorkspaceMemberRecord(
                    workspace_id=ws, user_id=other, role="owner", status="active"
                )
            )
            session.commit()
    return other


# ------------------------------------------------------------- the switch ----


def test_switch_off_keeps_putting_every_saved_draft_into_the_library(flow):
    saved_doc(flow)
    assert library_count(flow) == 1
    # On, but this user is not on the list: still the old behaviour.
    turn_on(flow, users=["usr_somebody_else"])
    saved_doc(flow, variant=1)
    assert library_count(flow) == 2
    # The list without the switch means nothing.
    settings = flow.client.app.state.settings
    settings.video_writing_brief_v2 = False
    settings.video_writing_brief_v2_users = flow.user
    saved_doc(flow, variant=2)
    assert library_count(flow) == 3


def test_switch_on_saves_the_document_but_not_into_the_library(flow):
    turn_on(flow)
    doc = saved_doc(flow)
    assert library_count(flow) == 0
    from app.video_writing_contracts import SaveWritingResult
    from app.video_writing_routes import store_result

    # The auto flow calling store_result directly (old keyword arguments) too.
    task = flow.write("douyin", 1)
    from types import SimpleNamespace

    workspace = SimpleNamespace(
        workspace_id=flow.ws, principal=SimpleNamespace(user_id=flow.user), role="owner"
    )
    with flow.client.app.state.session_factory() as session:
        result = store_result(
            SaveWritingResult(request_id=task, task_id=task),
            SimpleNamespace(app=flow.client.app),  # type: ignore[arg-type]
            workspace,  # type: ignore[arg-type]
            session,
            library_source="auto_writing",
            library_key="auto:run-x:v1",
        )
    assert "library_entry_id" not in result
    assert library_count(flow) == 0
    # Ticked afterwards: in the library once.
    stored = store(flow, [doc])
    assert stored.status_code == 200, stored.text
    assert stored.json()["created"] == 1 and library_count(flow) == 1


# ------------------------------------------------------------------ batch ----


def test_batch_is_idempotent_in_order_and_survives_a_refresh(flow):
    turn_on(flow)
    docs = [saved_doc(flow, variant=i) for i in range(3)]
    first = store(flow, [docs[2], docs[0], docs[1], docs[0]])
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["created"] == 3 and body["restored"] == 0
    assert [i["writing_document_id"] for i in body["items"]] == [
        docs[2],
        docs[0],
        docs[1],
    ]
    again = store(flow, docs).json()
    assert again["created"] == 0
    assert {i["id"] for i in again["items"]} == {i["id"] for i in body["items"]}
    assert library_count(flow) == 3
    # 刷新后：结果页按文稿 id 找回「已在文案库」。
    found = listed(flow, documents=",".join(docs))
    assert {i["writing_document_id"] for i in found["items"]} == set(docs)


def test_a_foreign_or_unknown_document_refuses_the_whole_batch(flow, video):
    turn_on(flow)
    mine = saved_doc(flow)
    unknown = str(uuid4())
    refused = store(flow, [mine, unknown])
    assert refused.status_code == 404
    error = refused.json()["error"]
    assert error["code"] == "VIDEO_WRITING_DOCUMENT_NOT_FOUND"
    assert error["details"]["missing_ids"] == [unknown]
    assert library_count(flow) == 0
    # Not a draft (the reference document) is refused the same way.
    with flow.client.app.state.session_factory() as session:
        ref = session.get(VideoWritingDocument, mine).reference_document_id
    assert store(flow, [ref]).status_code == 404
    # Another user of the same workspace cannot store my document.
    as_other_user(video, flow.ws)
    other = store(flow, [mine])
    assert other.status_code == 404
    assert library_count(flow) == 0


def test_too_many_or_malformed_ids_are_refused(flow):
    too_many = store(flow, [str(uuid4()) for _ in range(101)])
    assert too_many.status_code == 422
    assert too_many.json()["error"]["code"] == "VIDEO_SCRIPT_LIBRARY_TOO_MANY"
    bad = store(flow, ["../etc"])
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "VIDEO_SCRIPT_LIBRARY_BAD_ID"
    assert store(flow, []).status_code == 422


def test_drafts_of_a_run_carry_run_id_angle_and_the_run_key(flow):
    turn_on(flow)
    one, two, kept = (saved_doc(flow, variant=i) for i in range(3))
    run_id = fake_run(
        flow,
        [
            {
                "key": "douyin-v1",
                "platform": "douyin",
                "document_id": one,
                "angle": {"id": "a1", "name": "老板带看镇店款", "genre": "单品特写"},
            },
            {"key": "douyin-v2", "platform": "douyin", "document_id": two},
            {
                "key": "douyin-v3",
                "platform": "douyin",
                "document_id": None,
                "dropped_document_id": kept,
                "angle": {"id": "a3", "name": "三句话介绍我的店"},
            },
        ],
    )
    # Without run_id (found through the project) and with it.
    a = store(flow, [one]).json()["items"][0]
    b, c = store(flow, [two, kept], run_id=run_id).json()["items"]
    assert a["run_id"] == run_id and a["source"] == "auto_writing"
    assert a["angle"] == {"id": "a1", "name": "老板带看镇店款"}
    assert b["run_id"] == run_id and b["angle"] is None
    assert c["angle"]["name"] == "三句话介绍我的店"
    with flow.client.app.state.session_factory() as session:
        keys = set(session.scalars(select(VideoScriptLibraryEntry.dedupe_key)).all())
    assert keys == {
        f"auto:{run_id}:douyin-v1",
        f"auto:{run_id}:douyin-v2",
        f"auto:{run_id}:douyin-v3",
    }


def test_single_create_and_batch_share_one_entry_per_document(flow):
    turn_on(flow)
    first, second = saved_doc(flow), saved_doc(flow, variant=1)
    url = f"{flow.url}/script-library"

    def single(doc, script="改过的口播稿"):
        response = flow.client.post(
            url,
            json={
                "request_id": str(uuid4()),
                "script": script,
                "platform": "douyin",
                "writing_document_id": doc,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    # 单条先存（结果页改过再存）→ batch 返回同一条、不新建。
    made = single(first)
    batch = store(flow, [first]).json()
    assert batch["created"] == 0 and batch["items"][0]["id"] == made["id"]
    assert batch["items"][0]["script"] == "改过的口播稿"
    # batch 先存 → 单条返回原条目、不新建。
    stored = store(flow, [second]).json()["items"][0]
    assert single(second, "别的字")["id"] == stored["id"]
    assert library_count(flow) == 2


def test_a_deleted_entry_stored_again_comes_back(flow):
    turn_on(flow)
    doc = saved_doc(flow)
    entry = store(flow, [doc]).json()["items"][0]
    deleted = flow.client.post(
        f"{flow.url}/script-library/batch-delete", json={"ids": [entry["id"]]}
    )
    assert deleted.json()["deleted"] == 1 and library_count(flow) == 0
    back = store(flow, [doc]).json()
    assert back["created"] == 0 and back["restored"] == 1
    assert back["items"][0]["id"] == entry["id"] and library_count(flow) == 1


# ----------------------------------------------------------- batch delete ----


def test_batch_delete_removes_only_my_entries_in_one_request(flow, video):
    turn_on(flow)
    docs = [saved_doc(flow, variant=i % 4) for i in range(8)]
    mine = [i["id"] for i in store(flow, docs).json()["items"]]
    assert len(set(mine)) == 8
    me_identity = video[1].identity
    other = as_other_user(video, flow.ws)
    theirs = flow.client.post(
        f"{flow.url}/script-library",
        json={"request_id": str(uuid4()), "script": "别人的稿子"},
    ).json()["id"]
    # The other user cannot delete mine.
    refused = flow.client.post(
        f"{flow.url}/script-library/batch-delete", json={"ids": mine[:2]}
    ).json()
    assert refused == {"deleted": 0, "ids": [], "missing_ids": mine[:2]}
    video[1].identity = me_identity
    unknown = str(uuid4())
    done = flow.client.post(
        f"{flow.url}/script-library/batch-delete",
        json={"ids": [*mine, theirs, unknown]},
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["deleted"] == 8 and body["ids"] == mine
    assert body["missing_ids"] == [theirs, unknown]
    assert listed(flow)["total"] == 0
    with flow.client.app.state.session_factory() as session:
        row = session.get(VideoScriptLibraryEntry, theirs)
        assert row.deleted_at is None and row.owner_user_id == other
    # Deleting again is a no-op, not an error.
    again = flow.client.post(
        f"{flow.url}/script-library/batch-delete", json={"ids": mine[:3]}
    ).json()
    assert again["deleted"] == 0 and again["missing_ids"] == mine[:3]


# ------------------------------------------------------ filters and groups ----


def test_filters_by_run_and_source_and_groups_newest_first_older_last(flow):
    turn_on(flow)
    old_doc = saved_doc(flow, "xiaohongshu", 0)
    old_manual = store(flow, [old_doc]).json()["items"][0]  # no run: 更早的
    a1, a2, b1 = (saved_doc(flow, variant=i) for i in (1, 2, 3))
    earlier = fake_run(
        flow,
        [
            {"key": "douyin-v1", "platform": "douyin", "document_id": a1},
            {"key": "douyin-v2", "platform": "douyin", "document_id": a2},
        ],
        query="家具店老板推荐一家很长很长很长很长很长的名字的店",
        created_at=utc_now() - timedelta(hours=2),
    )
    later = fake_run(
        flow,
        [{"key": "xiaohongshu-v1", "platform": "xiaohongshu", "document_id": b1}],
        brief={"category": "欧式真皮家具"},
    )
    store(flow, [a1, a2, b1])
    assert {i["id"] for i in listed(flow, run_id="none")["items"]} == {old_manual["id"]}
    assert listed(flow, run_id=earlier)["total"] == 2
    assert listed(flow, source="auto_writing")["total"] == 3
    assert listed(flow, source="manual")["total"] == 1
    assert (
        flow.client.get(
            f"{flow.url}/script-library", params={"run_id": "bad id!"}
        ).status_code
        == 422
    )
    groups = flow.client.get(f"{flow.url}/script-library/runs").json()["groups"]
    assert [g["run_id"] for g in groups] == [later, earlier, None]
    assert groups[0]["label"] == "欧式真皮家具" and groups[0]["count"] == 1
    assert groups[0]["platforms"] == ["xiaohongshu"]
    assert groups[1]["label"].endswith("…") and len(groups[1]["label"]) == 21
    assert groups[1]["count"] == 2
    assert groups[2] == {
        "run_id": None,
        "created_at": None,
        "label": "更早的",
        "count": 1,
        "platforms": ["xiaohongshu"],
    }


def test_old_entries_without_run_id_are_listed_and_grouped_as_older(flow):
    # Switch off: the old auto-ingest key still names its run.
    saved_doc(flow)
    with flow.client.app.state.session_factory() as session:
        row = session.scalar(select(VideoScriptLibraryEntry))
        row.run_id = None  # an entry from before this change
        session.commit()
    [entry] = listed(flow)["items"]
    assert entry["run_id"] is None and entry["angle"] is None
    assert entry["used_for_talking"] is False
    groups = flow.client.get(f"{flow.url}/script-library/runs").json()["groups"]
    assert [(g["label"], g["count"]) for g in groups] == [("更早的", 1)]


def test_entries_used_by_a_talking_item_are_marked(flow):
    turn_on(flow)
    first, second = (
        i["id"]
        for i in store(flow, [saved_doc(flow), saved_doc(flow, variant=1)]).json()[
            "items"
        ]
    )
    made = flow.client.post(
        f"{flow.url}/work-batches",
        json=batch_body(item("第一条", script_document_id=first)),
    )
    assert made.status_code == 200, made.text
    marks = {i["id"]: i["used_for_talking"] for i in listed(flow)["items"]}
    assert marks == {first: True, second: False}
    one = flow.client.get(f"{flow.url}/script-library/{first}").json()
    assert one["used_for_talking"] is True
