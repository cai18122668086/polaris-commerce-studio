"""Batch editing (W3): queue limit, no double charge, restart recovery, retry."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app import video_editing_planning_preview as planning_preview
from app import video_editing_planning_worker as worker
from app import video_editing_task_routes as task_routes
from app import video_work_editing as editing
from app.errors import ApiError
from app.video_editing_task_models import (
    EditingArtifactRecord,
    EditingPlanningTaskRecord,
    EditingTaskRecord,
)
from app.video_work_editing_models import VideoWorkEditingRunRecord
from app.video_work_models import VideoWorkItemRecord
from tests.test_video_editing_planning_tasks import Provider, enable_fixture, setup
from tests.test_video_projects import base

pytest_plugins = ["tests.test_video_projects"]
TEMPLATE = "label-compare-v1"


def prepare_world(video, tmp_path, monkeypatch, count=3):
    client, _, ws, settings, source, task, semantic = setup(
        video, tmp_path, monkeypatch
    )
    enable_fixture(settings)
    settings.video_editing_native_plan_enabled = True
    factory = client.app.state.session_factory
    # As in the planning auto-preview tests: isolate the queue handoff from the
    # native catalog and recipes.
    monkeypatch.setattr(worker.planner, "validate_template_plan", lambda *a, **k: None)
    candidate = SimpleNamespace(
        id=str(uuid4()),
        source_id=source,
        details={"source_subtitles": "none"},
        recipes={"design": {"caption_font_id": "font-d1961be1161ea1be"}},
    )
    monkeypatch.setattr(planning_preview, "gateway_candidate", lambda *a: candidate)
    monkeypatch.setattr(task_routes, "admit_render_plan", lambda *args: None)

    # The recognition itself is covered by the editing worker tests: every
    # item's recognition resolves to the fixture's finished transcript.
    def recognized(body, settings_, workspace, session, **_):
        return session.get(EditingTaskRecord, task["id"]), False

    monkeypatch.setattr(editing, "persist_editing_task", recognized)

    # Rendering needs the media worker: a confirmed export is simulated.
    def exported(session, settings_, workspace, row, preview_id, sha):
        row.status, row.stage = "completed", "completed"
        session.commit()
        return row

    monkeypatch.setattr(editing, "confirm_export_task", exported)
    batch = client.post(
        base(ws) + "/work-batches",
        json={
            "request_id": str(uuid4()),
            "source": "editing_upload",
            "items": [
                {
                    "drive_mode": "uploaded_video",
                    "source_video_ref": {"kind": "upload", "id": source},
                }
                for _ in range(count)
            ],
        },
    )
    assert batch.status_code == 200, batch.text
    return client, ws, settings, factory, semantic, batch.json()


def submit(client, ws, batch, request_id=None, **extra):
    return client.post(
        base(ws) + f"/work-batches/{batch['id']}/editing",
        json={
            "request_id": request_id or str(uuid4()),
            "template_id": TEMPLATE,
            **extra,
        },
    )


def poll(client, ws, batch):
    response = client.get(base(ws) + f"/work-batches/{batch['id']}/editing")
    assert response.status_code == 200, response.text
    return response.json()


def phases(view):
    return [row["phase"] for row in view["editing"]]


def generates(factory):
    with factory() as session:
        return session.scalar(
            select(func.count())
            .select_from(EditingPlanningTaskRecord)
            .where(EditingPlanningTaskRecord.mode == "generate")
        )


def run_planning(factory, settings, semantic, mode):
    with factory() as session:
        ids = session.scalars(
            select(EditingPlanningTaskRecord.id).where(
                EditingPlanningTaskRecord.mode == mode,
                EditingPlanningTaskRecord.status == "queued",
            )
        ).all()
    for task_id in ids:
        worker.process(task_id, settings, factory, Provider(semantic))


def finish_renders(factory, status="awaiting_review"):
    """The worker finished the render: a preview awaits confirmation."""
    with factory() as session:
        for run in session.scalars(
            select(VideoWorkEditingRunRecord).where(
                VideoWorkEditingRunRecord.phase == "rendering"
            )
        ):
            row = session.get(EditingTaskRecord, run.render_task_id)
            if row.status == status:
                continue
            row.status = status
            if not session.scalar(
                select(EditingArtifactRecord).where(
                    EditingArtifactRecord.task_id == row.id,
                    EditingArtifactRecord.role == "preview",
                )
            ):
                session.add(
                    EditingArtifactRecord(
                        id=str(uuid4()),
                        task_id=row.id,
                        role="preview",
                        path="preview.mp4",
                        mime="video/mp4",
                        sha256="p" * 64,
                        bytes=1,
                        duration_ms=21000,
                    )
                )
        session.commit()


def drive_to_render(client, ws, batch, factory, settings, semantic):
    poll(client, ws, batch)  # recognition done -> free check queued
    run_planning(factory, settings, semantic, "prepare")
    poll(client, ws, batch)  # checked -> paid planning queued
    run_planning(factory, settings, semantic, "generate")
    return poll(client, ws, batch)  # planned -> render linked


def test_batch_queues_beyond_two_and_finishes_every_item(video, tmp_path, monkeypatch):
    client, ws, settings, factory, semantic, batch = prepare_world(
        video, tmp_path, monkeypatch
    )
    view = submit(client, ws, batch).json()
    assert phases(view) == ["transcribing", "transcribing", "queued"]
    third = view["editing"][2]
    assert third["queue_position"] == 1
    # Honest estimate: the shared worker runs one task at a time for everyone;
    # the third item waits behind the two recognitions already queued.
    assert third["queue_ahead"] is not None
    assert third["estimate_minutes"] >= editing.BASE_MINUTES
    queue = client.get(base(ws) + "/editing-queue").json()
    assert queue["tasks_ahead"] >= 0 and queue["minutes_per_item"] == 6
    items = {i["id"]: i for i in view["batch"]["items"]}
    assert [items[i]["status"] for i in view["batch"]["item_ids"]] == [
        "running",
        "running",
        "queued",
    ]
    view = drive_to_render(client, ws, batch, factory, settings, semantic)
    assert phases(view)[:2] == ["rendering", "rendering"]
    # Two items with byte-identical requests share one paid planning.
    assert generates(factory) == 1
    finish_renders(factory)
    view = poll(client, ws, batch)
    assert phases(view) == ["done", "done", "transcribing"]
    done = {i["id"]: i for i in view["batch"]["items"]}
    first = done[view["batch"]["item_ids"][0]]
    assert first["stage"] == "finishing" and first["status"] == "pending"
    assert first["editing_task_id"] == view["editing"][0]["render_task_id"]
    view = drive_to_render(client, ws, batch, factory, settings, semantic)
    finish_renders(factory)
    assert phases(poll(client, ws, batch)) == ["done", "done", "done"]
    assert generates(factory) == 1


def test_repeated_clicks_and_polls_never_create_or_charge_twice(
    video, tmp_path, monkeypatch
):
    client, ws, settings, factory, semantic, batch = prepare_world(
        video, tmp_path, monkeypatch, count=1
    )
    request_id = str(uuid4())
    first = submit(client, ws, batch, request_id).json()
    assert phases(first) == ["transcribing"]
    again = submit(client, ws, batch, request_id).json()
    other_tab = submit(client, ws, batch).json()
    # Repeats only advance the same run (recognition was already finished).
    assert phases(again) == phases(other_tab) == ["preparing"]
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(VideoWorkEditingRunRecord))
            == 1
        )
    drive_to_render(client, ws, batch, factory, settings, semantic)
    for _ in range(3):
        poll(client, ws, batch)
        submit(client, ws, batch)
    assert generates(factory) == 1


def test_api_restart_while_queued_still_finishes_via_sweep(
    video, tmp_path, monkeypatch
):
    client, ws, settings, factory, semantic, batch = prepare_world(
        video, tmp_path, monkeypatch, count=3
    )
    submit(client, ws, batch)
    # The API restarts: nobody polls any more. Only the sweep moves the batch.
    for _ in range(4):
        editing.sweep_once(factory, settings)
        run_planning(factory, settings, semantic, "prepare")
        editing.sweep_once(factory, settings)
        run_planning(factory, settings, semantic, "generate")
        editing.sweep_once(factory, settings)
        finish_renders(factory)
        editing.sweep_once(factory, settings)
    with factory() as session:
        runs = session.scalars(select(VideoWorkEditingRunRecord)).all()
        assert sorted(run.phase for run in runs) == ["done", "done", "done"]
        assert {
            item.stage for item in session.scalars(select(VideoWorkItemRecord))
        } == {"finishing"}
    assert generates(factory) == 1


def test_one_failed_render_retries_alone_and_for_free(video, tmp_path, monkeypatch):
    client, ws, settings, factory, semantic, batch = prepare_world(
        video, tmp_path, monkeypatch, count=2
    )
    submit(client, ws, batch)
    drive_to_render(client, ws, batch, factory, settings, semantic)
    with factory() as session:
        run = session.scalars(
            select(VideoWorkEditingRunRecord).order_by(
                VideoWorkEditingRunRecord.created_at
            )
        ).first()
        failing = run.item_id
        task = session.get(EditingTaskRecord, run.render_task_id)
        task.status, task.error_code = "failed", "EDITING_NATIVE_EXPORT_FAILED"
        session.commit()
    view = poll(client, ws, batch)
    row = next(r for r in view["editing"] if r["item_id"] == failing)
    assert row["phase"] == "failed" and row["can_retry"]
    assert "免费重试" in row["error"]
    paid = generates(factory)
    retried = client.post(base(ws) + f"/work-items/{failing}/editing-retry")
    assert retried.status_code == 200, retried.text
    row = next(r for r in retried.json()["editing"] if r["item_id"] == failing)
    assert row["phase"] == "rendering" and row["error"] is None
    with factory() as session:
        assert session.get(EditingTaskRecord, row["render_task_id"]).status == "queued"
    assert generates(factory) == paid  # no second paid planning


def test_batch_is_refused_whole_when_credits_cannot_cover_it(
    video, tmp_path, monkeypatch
):
    client, ws, settings, factory, semantic, batch = prepare_world(
        video, tmp_path, monkeypatch, count=3
    )

    def short(session, settings_, workspace_id, count):
        raise ApiError(
            402, "BUDGET_LIMIT_EXCEEDED", f"{count} 条剪辑需要 {count * 20} 积分"
        )

    monkeypatch.setattr(editing, "check_batch_credits", short)
    refused = submit(client, ws, batch)
    assert refused.status_code == 402
    assert "3 条剪辑需要 60 积分" in refused.json()["error"]["message"]
    with factory() as session:
        assert not session.scalars(select(VideoWorkEditingRunRecord)).all()


def test_credit_check_prices_planning_plus_render_per_item(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(editing, "credit_enforcement_enabled", lambda _: True)
    monkeypatch.setattr(
        editing.video_credits, "price_for", lambda _settings, action: 10
    )
    account = SimpleNamespace(balance_credits=50, reserved_credits=0)

    class Session:
        def get(self, *_):
            return account

        def commit(self):
            pass

    import app.credit_memberships as memberships

    monkeypatch.setattr(memberships, "refresh", lambda *_: account)
    editing.check_batch_credits(Session(), None, "ws", 2)  # 40 <= 50
    with pytest.raises(ApiError) as refused:
        editing.check_batch_credits(Session(), None, "ws", 3)  # 60 > 50
    assert refused.value.code == "BUDGET_LIMIT_EXCEEDED"


def test_awaiting_preview_is_confirmed_automatically(video, tmp_path, monkeypatch):
    client, ws, settings, factory, semantic, batch = prepare_world(
        video, tmp_path, monkeypatch, count=1
    )
    confirmed = []
    fake = editing.confirm_export_task

    def spy(session, settings_, workspace, row, preview_id, sha):
        confirmed.append((row.id, sha))
        return fake(session, settings_, workspace, row, preview_id, sha)

    monkeypatch.setattr(editing, "confirm_export_task", spy)
    submit(client, ws, batch)
    view = drive_to_render(client, ws, batch, factory, settings, semantic)
    render = view["editing"][0]["render_task_id"]
    assert view["batch"]["items"][0]["editing_task_id"] == render
    finish_renders(factory)
    view = poll(client, ws, batch)
    assert phases(view) == ["done"] and confirmed == [(render, "p" * 64)]
    poll(client, ws, batch)
    assert len(confirmed) == 1  # done items are never confirmed again


def test_a_talking_result_is_never_edited_as_a_copy(video, tmp_path, monkeypatch):
    """视频库里选到的口播结果若属于口播批次的条目，必须沿用那条条目（文案不丢）。"""
    client, ws, settings, factory, semantic, _ = prepare_world(
        video, tmp_path, monkeypatch, count=1
    )
    from app.video_generation_models import VideoGenerationRecord
    from app.video_work_models import VideoWorkBatchRecord
    from tests.test_video_work_items import generation

    with factory() as session:
        owner = session.scalars(select(VideoWorkBatchRecord)).first().owner_user_id
    job_id = generation(client, ws, owner)
    with factory() as session:
        job = session.get(VideoGenerationRecord, job_id)
        job.status = "completed"
        session.commit()
    talking = client.post(
        base(ws) + "/work-batches",
        json={
            "request_id": str(uuid4()),
            "source": "talking",
            "items": [{"script_text": "口播稿", "avatar_id": "a", "voice_id": "v"}],
        },
    ).json()
    with factory() as session:
        item = session.get(VideoWorkItemRecord, talking["item_ids"][0])
        item.generation_task_id = job_id
        item.source_video_ref = {"kind": "talking", "id": job_id}
        session.commit()
        session.refresh(item)
        session.expunge(item)
    owners = client.get(
        base(ws) + "/editing-source-owners", params={"generation_ids": job_id}
    ).json()
    assert owners == [
        {"generation_task_id": job_id, "batch_id": talking["id"], "item_id": item.id}
    ]
    # B9: refused when the copy batch is created (not only at submit), so no
    # empty direct-editing batch is left behind.
    refused = client.post(
        base(ws) + "/work-batches",
        json={
            "request_id": str(uuid4()),
            "source": "editing_upload",
            "items": [
                {
                    "drive_mode": "uploaded_video",
                    "source_video_ref": {"kind": "library", "id": job_id},
                }
            ],
        },
    )
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert error["code"] == "VIDEO_WORK_SOURCE_HAS_ITEM"
    assert error["details"]["batch_id"] == talking["id"]


def test_a_broken_plan_is_retried_afresh_not_revalidated(video, tmp_path, monkeypatch):
    """模型输出不合规时，免费重核同一份响应只会再失败：重试走新一轮编排。"""
    client, ws, settings, factory, semantic, batch = prepare_world(
        video, tmp_path, monkeypatch, count=1
    )
    submit(client, ws, batch)
    poll(client, ws, batch)
    run_planning(factory, settings, semantic, "prepare")
    poll(client, ws, batch)
    with factory() as session:
        run = session.scalars(select(VideoWorkEditingRunRecord)).one()
        generated = session.get(EditingPlanningTaskRecord, run.generate_task_id)
        generated.status, generated.error_code = (
            "failed",
            "EDITING_PLAN_CONTRACT_INVALID",
        )
        session.commit()
        item_id, first_generate = run.item_id, run.generate_task_id
    view = poll(client, ws, batch)
    assert "重新编排" in view["editing"][0]["error"]
    retried = client.post(base(ws) + f"/work-items/{item_id}/editing-retry").json()
    assert retried["editing"][0]["phase"] in {"transcribing", "preparing"}
    poll(client, ws, batch)
    run_planning(factory, settings, semantic, "prepare")
    poll(client, ws, batch)
    with factory() as session:
        run = session.get(VideoWorkEditingRunRecord, item_id)
        assert run.attempt == 2 and run.generate_task_id not in (None, first_generate)


def test_a_failing_queue_estimate_never_breaks_submit_or_the_batch_view(
    video, tmp_path, monkeypatch
):
    client, ws, settings, factory, semantic, batch = prepare_world(
        video, tmp_path, monkeypatch
    )

    def broken(session, before):
        session.execute(select(func.count()).select_from(EditingTaskRecord))
        raise RuntimeError("queue estimate exploded")

    monkeypatch.setattr(editing, "_worker_queue", broken)
    response = submit(client, ws, batch)
    assert response.status_code == 200, response.text
    view = response.json()
    assert phases(view) == ["transcribing", "transcribing", "queued"]
    third = view["editing"][2]
    assert third["queue_position"] == 1
    assert third["estimate_minutes"] >= editing.BASE_MINUTES
    # Polling advances the pipeline; the view itself must still answer 200.
    assert phases(poll(client, ws, batch))[2] == "queued"
    queue = client.get(base(ws) + "/editing-queue")
    assert queue.status_code == 200, queue.text
    assert queue.json()["tasks_ahead"] == 0 and queue.json()["minutes_ahead"] == 0


# --------------------------------------------------------------- B5 换模板重剪

OTHER_TEMPLATE = "roll-compare-v2"


def add_finals(factory):
    """The export wrote its final video (the fake export only flips the status)."""
    with factory() as session:
        for run in session.scalars(
            select(VideoWorkEditingRunRecord).where(
                VideoWorkEditingRunRecord.phase == "done"
            )
        ):
            if not session.scalar(
                select(EditingArtifactRecord).where(
                    EditingArtifactRecord.task_id == run.render_task_id,
                    EditingArtifactRecord.role == "final",
                )
            ):
                session.add(
                    EditingArtifactRecord(
                        id=str(uuid4()),
                        task_id=run.render_task_id,
                        role="final",
                        path="final.mp4",
                        mime="video/mp4",
                        sha256="f" * 64,
                        bytes=1,
                        duration_ms=21000,
                    )
                )
        session.commit()


def finished_batch(video, tmp_path, monkeypatch, count=1):
    world = prepare_world(video, tmp_path, monkeypatch, count=count)
    client, ws, settings, factory, semantic, batch = world
    submit(client, ws, batch)
    for _ in range(count):
        drive_to_render(client, ws, batch, factory, settings, semantic)
        finish_renders(factory)
        poll(client, ws, batch)
    assert phases(poll(client, ws, batch)) == ["done"] * count
    add_finals(factory)
    return world


def redo(client, ws, path, request_id=None, template=OTHER_TEMPLATE, **extra):
    return client.post(
        base(ws) + path,
        json={
            "request_id": request_id or str(uuid4()),
            "template_id": template,
            **extra,
        },
    )


def transcripts_made(calls):
    return sum(1 for body in calls if body.options.mode == "transcript")


def test_redo_one_item_with_another_template_keeps_the_old_cut(
    video, tmp_path, monkeypatch
):
    client, ws, settings, factory, semantic, batch = finished_batch(
        video, tmp_path, monkeypatch
    )
    old = poll(client, ws, batch)["editing"][0]
    item_id = old["item_id"]
    recognized = editing.persist_editing_task
    calls = []
    monkeypatch.setattr(
        editing,
        "persist_editing_task",
        lambda body, *a, **k: (calls.append(body), recognized(body, *a, **k))[1],
    )
    paid = generates(factory)
    response = redo(client, ws, f"/work-items/{item_id}/editing-redo")
    assert response.status_code == 200, response.text
    row = response.json()["editing"][0]
    # Back in the pipeline with the new template; the recognition is reused.
    assert row["attempt"] == 2 and row["template_id"] == OTHER_TEMPLATE
    assert row["phase"] == "transcribing" and row["final_url"] is None
    assert transcripts_made(calls) == 0
    [kept] = row["history"]
    assert kept["attempt"] == 1 and kept["template_id"] == TEMPLATE
    assert kept["final_url"] and kept["final_url"].endswith(
        old["final_url"].rsplit("/", 1)[1]
    )
    item = response.json()["batch"]["items"][0]
    assert item["stage"] == "editing" and item["status"] in {"queued", "running"}
    assert item["editing_task_id"] is None
    assert item["history"]["editing"] == [old["render_task_id"]]
    assert item["video_updated_at"] is None
    view = drive_to_render(client, ws, batch, factory, settings, semantic)
    assert view["editing"][0]["render_task_id"] != old["render_task_id"]
    finish_renders(factory)
    poll(client, ws, batch)
    add_finals(factory)
    view = poll(client, ws, batch)
    row, item = view["editing"][0], view["batch"]["items"][0]
    assert row["phase"] == "done" and row["final_url"] != old["final_url"]
    assert len(row["history"]) == 1
    assert (
        item["stage"] == "finishing"
        and item["editing_task_id"] == row["render_task_id"]
    )
    # Finishing reads these two to say 「视频已更新，可重新生成封面」.
    assert item["editing_attempt"] == 2 and item["video_updated_at"]
    assert generates(factory) == paid + 1  # one new paid planning, no more
    assert transcripts_made(calls) == 0


def test_repeated_redo_clicks_build_one_round_and_pay_once(
    video, tmp_path, monkeypatch
):
    client, ws, settings, factory, semantic, batch = finished_batch(
        video, tmp_path, monkeypatch
    )
    item_id = poll(client, ws, batch)["editing"][0]["item_id"]
    checks = []
    real_check = editing.check_batch_credits
    monkeypatch.setattr(
        editing,
        "check_batch_credits",
        lambda s, st, w, count: (checks.append(count), real_check(s, st, w, count))[1],
    )
    request_id = str(uuid4())
    path = f"/work-items/{item_id}/editing-redo"
    first = redo(client, ws, path, request_id).json()["editing"][0]
    again = redo(client, ws, path, request_id).json()["editing"][0]
    other_tab = redo(client, ws, path).json()["editing"][0]  # still re-editing
    batch_too = redo(client, ws, f"/work-batches/{batch['id']}/editing-redo").json()
    assert first["attempt"] == again["attempt"] == other_tab["attempt"] == 2
    assert batch_too["editing"][0]["attempt"] == 2
    assert len(other_tab["history"]) == 1 and checks == [1]
    paid = generates(factory)
    drive_to_render(client, ws, batch, factory, settings, semantic)
    for _ in range(3):
        redo(client, ws, path, request_id)
        poll(client, ws, batch)
    assert generates(factory) == paid + 1
    with factory() as session:
        run = session.get(VideoWorkEditingRunRecord, item_id)
        assert run.attempt == 2 and len(run.options["history"]) == 1
    # Done again: the same request id still does nothing; a new click redoes.
    finish_renders(factory)
    poll(client, ws, batch)
    assert redo(client, ws, path, request_id).json()["editing"][0]["attempt"] == 2
    assert (
        redo(client, ws, path, template=TEMPLATE).json()["editing"][0]["attempt"] == 3
    )


def test_batch_redo_takes_every_finished_item_and_checks_credits_once(
    video, tmp_path, monkeypatch
):
    client, ws, settings, factory, semantic, batch = finished_batch(
        video, tmp_path, monkeypatch, count=2
    )
    checks = []
    monkeypatch.setattr(
        editing, "check_batch_credits", lambda s, st, w, count: checks.append(count)
    )
    view = redo(client, ws, f"/work-batches/{batch['id']}/editing-redo").json()
    assert [row["attempt"] for row in view["editing"]] == [2, 2]
    assert {row["template_id"] for row in view["editing"]} == {OTHER_TEMPLATE}
    assert checks == [2]
    view = drive_to_render(client, ws, batch, factory, settings, semantic)
    finish_renders(factory)
    assert phases(poll(client, ws, batch)) == ["done", "done"]


def test_redo_is_refused_whole_when_credits_cannot_cover_it(
    video, tmp_path, monkeypatch
):
    client, ws, settings, factory, semantic, batch = finished_batch(
        video, tmp_path, monkeypatch, count=2
    )

    def short(session, settings_, workspace_id, count):
        raise ApiError(402, "BUDGET_LIMIT_EXCEEDED", f"{count} 条剪辑需要积分")

    monkeypatch.setattr(editing, "check_batch_credits", short)
    refused = redo(client, ws, f"/work-batches/{batch['id']}/editing-redo")
    assert refused.status_code == 402
    assert [row["attempt"] for row in poll(client, ws, batch)["editing"]] == [1, 1]
    assert phases(poll(client, ws, batch)) == ["done", "done"]


def test_redo_needs_an_edited_item_of_the_owner(video, tmp_path, monkeypatch):
    client, ws, settings, factory, semantic, batch = prepare_world(
        video, tmp_path, monkeypatch, count=1
    )
    item_id = batch["item_ids"][0]
    never = redo(client, ws, f"/work-items/{item_id}/editing-redo")
    assert never.status_code == 409
    assert never.json()["error"]["code"] == "EDITING_NOT_STARTED"
    missing = redo(client, ws, f"/work-items/{uuid4()}/editing-redo")
    assert missing.status_code == 404
    unknown = redo(
        client, ws, f"/work-batches/{batch['id']}/editing-redo", item_ids=["nope"]
    )
    assert unknown.status_code == 404


def test_estimate_follows_the_source_length(monkeypatch):
    assert editing.item_minutes(None) == editing.MINUTES_PER_ITEM
    short, long = editing.item_minutes(13_000), editing.item_minutes(180_000)
    assert round(short, 1) == 4.5 and round(long, 1) == 36.5
    assert long > 7 * short / 1.0 - 1
