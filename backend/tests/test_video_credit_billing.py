"""Video actions hold, settle and release workspace credits like image jobs."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app import services
from app import video_credit_billing as video_credits
from app.models import (
    CreditLedgerEntryRecord,
    CreditReservationRecord,
    WorkspaceCreditAccountRecord,
)
from app.video_assistance_models import VideoAssistanceRecord
from app.video_editing_task_models import EditingPlanningTaskRecord, EditingTaskRecord
from app.video_generation_models import VideoGenerationRecord
from app.video_voice_models import VideoClonedVoiceRecord
from tests.test_video_generation import request_body, video_gen  # noqa: F401


@pytest.fixture
def billing(video_gen):  # noqa: F811
    client = video_gen[0]
    # Each test opts into the prices it exercises; defaults are pinned elsewhere.
    client.app.state.settings.video_credit_prices = {}
    workspace = client.get("/api/v1/workspaces").json()[0]["id"]
    services.set_quota_enabled(True)
    services.set_credit_enforcement_enabled(True)
    try:
        yield (*video_gen, workspace)
    finally:
        services.set_quota_enabled(True)
        services.set_credit_enforcement_enabled(
            client.app.state.settings.workspace_credit_enforcement_enabled
        )


def prices(client, **values):
    client.app.state.settings.video_credit_prices = values


def set_balance(client, workspace, credits):
    """Only before the first hold: lots are derived from the balance once."""
    with client.app.state.session_factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, workspace)
        account.balance_credits = credits
        session.commit()


def account(client, workspace):
    with client.app.state.session_factory() as session:
        row = session.get(WorkspaceCreditAccountRecord, workspace)
        return row.balance_credits, row.reserved_credits


def holds(client, owner_id=None):
    with client.app.state.session_factory() as session:
        query = select(CreditReservationRecord).where(
            CreditReservationRecord.owner_type.is_not(None)
        )
        if owner_id:
            query = query.where(CreditReservationRecord.owner_id == owner_id)
        rows = session.scalars(query.order_by(CreditReservationRecord.created_at))
        return [(r.charge_action, r.status, r.settled_credits) for r in rows]


def ledger(client, workspace):
    with client.app.state.session_factory() as session:
        rows = session.scalars(
            select(CreditLedgerEntryRecord)
            .where(
                CreditLedgerEntryRecord.workspace_id == workspace,
                CreditLedgerEntryRecord.reservation_id.is_not(None),
            )
            .order_by(CreditLedgerEntryRecord.id)
        )
        return [
            (r.entry_type, r.delta_balance_credits, r.delta_reserved_credits)
            for r in rows
        ]


def test_unpriced_video_action_is_not_charged(billing):
    client, _, _, root, pid, _, workspace = billing
    before = account(client, workspace)
    r = client.post(root + "/generation-tasks", json=request_body(pid))
    assert r.status_code == 200, r.text
    assert client.get(root + "/generation-tasks").json()[0]["status"] == "completed"
    assert holds(client) == []
    assert account(client, workspace) == before


def test_lipsync_holds_on_submit_and_settles_once_on_success(billing):
    client, _, _, root, pid, _, workspace = billing
    set_balance(client, workspace, 1000)
    prices(client, lipsync=30)
    body = request_body(pid)
    r = client.post(root + "/generation-tasks", json=body)
    assert r.status_code == 200, r.text
    assert client.get(root + "/generation-tasks").json()[0]["status"] == "completed"
    assert holds(client) == [("lipsync", "settled", 30)]
    assert account(client, workspace) == (970, 0)
    # Replaying the same request (frontend "再次确认") never charges again.
    assert client.post(root + "/generation-tasks", json=body).status_code == 200
    assert holds(client) == [("lipsync", "settled", 30)]
    assert account(client, workspace) == (970, 0)
    assert ledger(client, workspace) == [("reserve", 0, 30), ("settle", -30, -30)]
    with client.app.state.session_factory() as session:
        entry = session.scalars(
            select(CreditLedgerEntryRecord).where(
                CreditLedgerEntryRecord.entry_type == "settle"
            )
        ).one()
        assert entry.job_id is None and "数字人口播" in (entry.description or "")


def test_insufficient_balance_rejects_before_creating_the_task(billing):
    client, _, provider, root, pid, _, workspace = billing
    set_balance(client, workspace, 10)
    prices(client, lipsync=30)
    r = client.post(root + "/generation-tasks", json=request_body(pid))
    assert r.status_code == 402
    assert "BUDGET_LIMIT_EXCEEDED" in r.text and "积分不足" in r.text
    assert client.get(root + "/generation-tasks").json() == []
    assert provider.posts == []
    assert holds(client) == []
    assert account(client, workspace) == (10, 0)


def test_failed_generation_releases_and_resume_charges_once(billing):
    client, _, provider, root, pid, _, workspace = billing
    set_balance(client, workspace, 1000)
    prices(client, lipsync=30)
    download = provider.download

    def broken(*args, **kwargs):
        if args[1].name == "result.mp4":
            from app.errors import ApiError

            raise ApiError(502, "VIDEO_PROVIDER_REJECTED", "fixture failure")
        return download(*args, **kwargs)

    provider.download = broken
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "failed"
    assert holds(client) == [("lipsync", "released", 0)]
    assert account(client, workspace) == (1000, 0)
    assert job["can_resume"] and job["stage"] == "downloading_video"
    provider.download = download
    resumed = client.post(root + f"/generation-tasks/{job['id']}/resume")
    assert resumed.status_code == 200
    assert client.get(root + "/generation-tasks").json()[0]["status"] == "completed"
    assert holds(client) == [
        ("lipsync", "released", 0),
        ("lipsync", "settled", 30),
    ]
    assert account(client, workspace) == (970, 0)


def test_transient_failure_keeps_hold_for_automatic_recovery(billing):
    client, _, provider, root, pid, _, workspace = billing
    set_balance(client, workspace, 1000)
    prices(client, lipsync=30)
    download = provider.download

    def broken(*args, **kwargs):
        if args[1].name == "result.mp4":
            from app.errors import ApiError

            raise ApiError(502, "VIDEO_MEDIA_DOWNLOAD_FAILED", "fixture interrupted")
        return download(*args, **kwargs)

    provider.download = broken
    client.post(root + "/generation-tasks", json=request_body(pid))
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "failed"
    assert holds(client) == [("lipsync", "active", 0)]
    assert account(client, workspace) == (1000, 30)
    provider.download = download
    resumed = client.post(root + f"/generation-tasks/{job['id']}/resume")
    assert resumed.status_code == 200
    assert holds(client) == [("lipsync", "settled", 30)]
    assert account(client, workspace) == (970, 0)


def h3(client, root):
    r = client.post(
        root + "/generation-tasks",
        json={
            "request_id": str(uuid4()),
            "kind": "h3_template",
            "avatar_id": "self-presenter-female-v1",
        },
    )
    assert r.status_code == 200, r.text
    return client.get(root + "/generation-tasks").json()[0]


def test_template_motion_and_registration_are_billed_as_two_steps(billing):
    client, _, _, root, _, _, workspace = billing
    set_balance(client, workspace, 1000)
    prices(client, avatar_motion=50, avatar_register=20)
    job = h3(client, root)
    assert job["status"] == "awaiting_review"
    assert holds(client) == [("avatar_motion", "settled", 50)]
    approve = root + f"/generation-tasks/{job['id']}/approve-template"
    assert client.post(approve).status_code == 200
    assert client.post(approve).status_code == 200
    assert holds(client) == [
        ("avatar_motion", "settled", 50),
        ("avatar_register", "settled", 20),
    ]
    assert account(client, workspace) == (930, 0)


def test_rejected_template_pays_motion_only(billing):
    client, _, _, root, _, _, workspace = billing
    set_balance(client, workspace, 1000)
    prices(client, avatar_motion=50, avatar_register=20)
    job = h3(client, root)
    reject = root + f"/generation-tasks/{job['id']}/reject-template"
    assert client.post(reject).status_code == 200
    assert holds(client) == [("avatar_motion", "settled", 50)]
    assert account(client, workspace) == (950, 0)


def test_registration_needs_balance_before_approval(billing):
    client, _, provider, root, _, _, workspace = billing
    set_balance(client, workspace, 60)
    prices(client, avatar_motion=50, avatar_register=20)
    job = h3(client, root)
    approve = root + f"/generation-tasks/{job['id']}/approve-template"
    r = client.post(approve)
    assert r.status_code == 402 and "BUDGET_LIMIT_EXCEEDED" in r.text
    current = client.get(root + "/generation-tasks").json()[0]
    assert current["status"] == "awaiting_review"
    assert len(provider.posts) == 1
    assert account(client, workspace) == (10, 0)


def test_tracking_only_mode_never_rejects_or_deducts(billing):
    client, _, _, root, pid, _, workspace = billing
    services.set_credit_enforcement_enabled(False)
    set_balance(client, workspace, 10)
    prices(client, lipsync=30)
    r = client.post(root + "/generation-tasks", json=request_body(pid))
    assert r.status_code == 200, r.text
    assert holds(client) == [("lipsync", "settled", 30)]
    assert account(client, workspace) == (10, 0)
    assert ledger(client, workspace) == [("reserve", 0, 0), ("settle", 0, 0)]


# --- Task kinds whose workers run outside the request -----------------------


def seed(session, record):
    session.add(record)
    session.flush()
    return record


def editing_task(workspace, user, status="queued"):
    return EditingTaskRecord(
        id=str(uuid4()),
        workspace_id=workspace,
        owner_user_id=user,
        project_id=str(uuid4()),
        source_id=str(uuid4()),
        request_id=str(uuid4()),
        request_hash="a" * 64,
        library_release="fixture",
        status=status,
    )


def planning_task(workspace, user, status="queued", **fields):
    return EditingPlanningTaskRecord(
        id=str(uuid4()),
        workspace_id=workspace,
        owner_user_id=user,
        project_id=str(uuid4()),
        source_id=str(uuid4()),
        base_task_id=str(uuid4()),
        base_transcript_artifact_id=str(uuid4()),
        base_transcript_sha256="b" * 64,
        request_id=str(uuid4()),
        request_hash="c" * 64,
        library_release="fixture",
        mode="generate",
        model="fixture",
        status=status,
        **fields,
    )


@pytest.fixture
def raw_session(billing):
    client, _, _, _, _, user, workspace = billing
    set_balance(client, workspace, 1000)
    prices(
        client,
        editing_planning=40,
        editing_render=25,
        writing_generate=5,
        benchmark_search=3,
        voice_clone=60,
    )
    factory = client.app.state.session_factory
    with factory() as session:
        yield client, session, factory, workspace, user


def test_planning_cancel_and_timeout_release_and_retry_charges_once(raw_session):
    client, session, factory, workspace, user = raw_session
    settings = client.app.state.settings
    cancelled = seed(session, planning_task(workspace, user))
    timed_out = seed(session, planning_task(workspace, user, status="running"))
    for row in (cancelled, timed_out):
        video_credits.hold(
            session, settings, workspace, "editing_planning", "video_planning", row.id
        )
    session.commit()
    assert account(client, workspace) == (1000, 80)
    cancelled.status = "cancelled"
    timed_out.status, timed_out.error_code = (
        "failed",
        "EDITING_PLAN_TIME_LIMIT_EXCEEDED",
    )
    session.commit()
    # Neither worker reports back: the maintenance sweep resolves both.
    assert video_credits.sweep(factory) == 2
    assert account(client, workspace) == (1000, 0)
    # Retry: a fresh hold, and a repeated retry request reuses it.
    session.expire_all()
    timed_out.status = "queued"
    for _ in range(2):
        video_credits.hold(
            session,
            settings,
            workspace,
            "editing_planning",
            "video_planning",
            timed_out.id,
        )
    session.commit()
    timed_out.status = "completed"
    session.commit()
    video_credits.reconcile_owner(session, "video_planning", timed_out.id)
    video_credits.reconcile_owner(session, "video_planning", timed_out.id)
    session.commit()
    assert holds(client, timed_out.id) == [
        ("editing_planning", "released", 0),
        ("editing_planning", "settled", 40),
    ]
    assert account(client, workspace) == (960, 0)
    # A settled action is never held again for the same task.
    assert (
        video_credits.hold(
            session,
            settings,
            workspace,
            "editing_planning",
            "video_planning",
            timed_out.id,
        ).status
        == "settled"
    )
    session.commit()
    assert account(client, workspace) == (960, 0)


def test_planning_preview_render_follows_the_linked_editing_task(raw_session):
    client, session, factory, workspace, user = raw_session
    settings = client.app.state.settings
    ok = seed(session, planning_task(workspace, user, status="completed"))
    broken = seed(session, planning_task(workspace, user, status="completed"))
    auto_failed = seed(session, planning_task(workspace, user, status="completed"))
    for row in (ok, broken, auto_failed):
        video_credits.hold(
            session, settings, workspace, "editing_render", "video_planning", row.id
        )
    ok_task = seed(session, editing_task(workspace, user, "running"))
    bad_task = seed(session, editing_task(workspace, user, "running"))
    ok.result = {"preview_task_id": ok_task.id}
    broken.result = {"preview_task_id": bad_task.id}
    auto_failed.result = {"auto_preview_error_code": "EDITING_DISABLED"}
    session.commit()
    assert video_credits.sweep(factory) == 1  # auto preview never submitted
    ok_task.status = "awaiting_review"
    bad_task.status = "cancelled"
    session.commit()
    assert video_credits.reconcile_editing(session, ok_task.id) == 1
    assert video_credits.reconcile_editing(session, bad_task.id) == 1
    session.commit()
    assert holds(client, ok.id) == [("editing_render", "settled", 25)]
    assert holds(client, broken.id) == [("editing_render", "released", 0)]
    assert holds(client, auto_failed.id) == [("editing_render", "released", 0)]
    assert account(client, workspace) == (975, 0)


def test_assistance_and_voice_outcomes(raw_session):
    client, session, factory, workspace, user = raw_session
    settings = client.app.state.settings
    writing = seed(
        session,
        VideoAssistanceRecord(
            id=str(uuid4()),
            workspace_id=workspace,
            owner_user_id=user,
            project_id=str(uuid4()),
            request_id=str(uuid4()),
            request_hash="d" * 64,
            kind="fact_draft",
            inputs={},
        ),
    )
    search = seed(
        session,
        VideoAssistanceRecord(
            id=str(uuid4()),
            workspace_id=workspace,
            owner_user_id=user,
            project_id=str(uuid4()),
            request_id=str(uuid4()),
            request_hash="e" * 64,
            kind="benchmark_search",
            inputs={},
        ),
    )
    voice_id = "cv-voice-" + uuid4().hex
    video_credits.hold(
        session, settings, workspace, "writing_generate", "video_assistance", writing.id
    )
    video_credits.hold(
        session, settings, workspace, "benchmark_search", "video_assistance", search.id
    )
    video_credits.hold(
        session, settings, workspace, "voice_clone", "video_voice", voice_id
    )
    session.commit()
    assert account(client, workspace) == (1000, 68)
    writing.status = "completed"
    search.status = "failed"
    session.commit()
    # The voice row was never stored (e.g. deleted); its hold is returned.
    assert session.get(VideoClonedVoiceRecord, voice_id) is None
    assert video_credits.sweep(factory) == 3
    assert holds(client, writing.id) == [("writing_generate", "settled", 5)]
    assert holds(client, search.id) == [("benchmark_search", "released", 0)]
    assert holds(client, voice_id) == [("voice_clone", "released", 0)]
    assert account(client, workspace) == (995, 0)
    assert video_credits.sweep(factory) == 0


def test_pending_tasks_keep_their_hold(raw_session):
    client, session, factory, workspace, user = raw_session
    row = seed(session, editing_task(workspace, user, "running"))
    video_credits.hold(
        session,
        client.app.state.settings,
        workspace,
        "editing_render",
        "video_editing",
        row.id,
    )
    session.commit()
    assert video_credits.sweep(factory) == 0
    assert holds(client, row.id) == [("editing_render", "active", 0)]
    assert account(client, workspace) == (1000, 25)
    assert session.scalar(select(VideoGenerationRecord.id).limit(1)) is None
