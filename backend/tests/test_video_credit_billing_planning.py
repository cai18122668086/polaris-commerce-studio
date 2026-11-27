"""Paid smart-edit planning holds credits through the real routes and worker."""

import pytest
from sqlalchemy import select

from app import services
from app import video_credit_billing as video_credits
from app import video_editing_planning_worker as worker
from app.models import CreditReservationRecord, WorkspaceCreditAccountRecord
from app.video_editing_task_models import EditingPlanningTaskRecord, EditingTaskRecord
from tests.test_video_editing_planning_tasks import (
    Provider,
    create,
    enable_fixture,
    prepare,
    setup,
)
from tests.test_video_editing_planning_tasks import (
    test_auto_preview_continues_one_saved_model_submission as auto_preview_flow,
)
from tests.test_video_projects import base, video  # noqa: F401


@pytest.fixture
def enforced():
    services.set_quota_enabled(True)
    services.set_credit_enforcement_enabled(True)
    try:
        yield
    finally:
        services.set_credit_enforcement_enabled(False)


def state(client, ws):
    with client.app.state.session_factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, ws)
        rows = session.scalars(
            select(CreditReservationRecord)
            .where(CreditReservationRecord.owner_type == "video_planning")
            .order_by(CreditReservationRecord.created_at)
        )
        return (
            (account.balance_credits, account.reserved_credits),
            [(r.charge_action, r.status) for r in rows],
        )


def test_paid_planning_holds_settles_and_cancel_releases(
    video,  # noqa: F811
    tmp_path,
    monkeypatch,
    enforced,
):
    client, _, ws, settings, _, task, semantic = setup(video, tmp_path, monkeypatch)
    with client.app.state.session_factory() as session:
        session.get(WorkspaceCreditAccountRecord, ws).balance_credits = 1000
        session.commit()
    client.app.state.settings.video_credit_prices = {"editing_planning": 40}
    settings.video_credit_prices = {"editing_planning": 40}
    prepared = prepare(client, ws, settings, task)
    assert state(client, ws) == ((1000, 0), [])  # preparation is free
    enable_fixture(settings)
    submitted = create(client, ws, task["id"], "generate", prepared["id"])
    assert submitted.status_code == 200, submitted.text
    replay = create(client, ws, task["id"], "generate", prepared["id"])
    assert replay.json()["id"] == submitted.json()["id"]
    assert state(client, ws) == ((1000, 40), [("editing_planning", "active")])
    factory = client.app.state.session_factory
    worker.process(submitted.json()["id"], settings, factory, Provider(semantic))
    assert video_credits.sweep(factory) == 1
    assert state(client, ws) == ((960, 0), [("editing_planning", "settled")])

    # A second paid plan cancelled while queued returns its hold at once.
    second = prepare(client, ws, settings, task)
    # Same request again on purpose: the user confirmed a paid re-plan.
    queued = create(client, ws, task["id"], "generate", second["id"], replan=True)
    assert queued.status_code == 200, queued.text
    url = base(ws) + "/editing-planning-tasks/" + queued.json()["id"]
    assert client.post(url + "/cancel").json()["status"] == "cancelled"
    assert state(client, ws) == (
        (960, 0),
        [("editing_planning", "settled"), ("editing_planning", "released")],
    )
    # Retrying it holds again exactly once.
    assert client.post(url + "/retry").status_code == 200
    assert state(client, ws)[0] == (960, 40)


def test_paid_planning_needs_balance_and_creates_nothing_without_it(
    video,  # noqa: F811
    tmp_path,
    monkeypatch,
    enforced,
):
    client, _, ws, settings, _, task, _ = setup(video, tmp_path, monkeypatch)
    with client.app.state.session_factory() as session:
        session.get(WorkspaceCreditAccountRecord, ws).balance_credits = 30
        session.commit()
    client.app.state.settings.video_credit_prices = {"editing_planning": 40}
    settings.video_credit_prices = {"editing_planning": 40}
    prepared = prepare(client, ws, settings, task)
    enable_fixture(settings)
    rejected = create(client, ws, task["id"], "generate", prepared["id"])
    assert rejected.status_code == 402, rejected.text
    assert rejected.json()["error"]["code"] == "BUDGET_LIMIT_EXCEEDED"
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(
                select(EditingPlanningTaskRecord.id).where(
                    EditingPlanningTaskRecord.mode == "generate"
                )
            )
            is None
        )
    assert state(client, ws) == ((30, 0), [])


@pytest.mark.parametrize("outcome", ["immediate", "blocked"])
def test_auto_preview_holds_render_up_front_and_follows_the_preview(
    video,  # noqa: F811
    tmp_path,
    monkeypatch,
    enforced,
    outcome,
):
    table = {"editing_planning": 40, "editing_render": 25}
    monkeypatch.setattr(video_credits, "price_for", lambda _s, a: table.get(a))
    client, _, ws, _, _ = video
    factory = client.app.state.session_factory
    with factory() as session:
        session.get(WorkspaceCreditAccountRecord, ws).balance_credits = 1000
        session.commit()
    auto_preview_flow(video, tmp_path, monkeypatch, outcome)
    # One click held both steps; the worker's own preview submit reused the hold.
    assert state(client, ws)[0] == (1000, 65)
    with factory() as session:
        planning = session.scalars(
            select(EditingPlanningTaskRecord).where(
                EditingPlanningTaskRecord.mode == "generate"
            )
        ).one()
        preview = planning.result.get("preview_task_id")
        if preview:
            task = session.get(EditingTaskRecord, preview)
            task.status = "awaiting_review"
            session.commit()
    video_credits.sweep(factory)
    balance, holds = state(client, ws)
    assert holds.count(("editing_planning", "settled")) == 1
    if outcome == "blocked":
        assert holds == [
            ("editing_planning", "settled"),
            ("editing_render", "released"),
        ]
        assert balance == (960, 0)
    else:
        assert holds == [
            ("editing_planning", "settled"),
            ("editing_render", "settled"),
        ]
        assert balance == (935, 0)
