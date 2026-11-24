"""Voice cloning holds credits on submit and settles when the voice is ready."""

import pytest
from sqlalchemy import select

from app import services
from app.models import CreditReservationRecord, WorkspaceCreditAccountRecord
from app.video_voice_models import VideoClonedVoiceRecord
from tests.test_video_generation import video_gen  # noqa: F401
from tests.test_video_voice_cloning import clone_env, create  # noqa: F401


@pytest.fixture
def priced(clone_env):  # noqa: F811
    client = clone_env[0]
    ws = client.get("/api/v1/workspaces").json()[0]["id"]
    services.set_quota_enabled(True)
    services.set_credit_enforcement_enabled(True)
    client.app.state.settings.video_credit_prices = {"voice_clone": 60}
    try:
        yield clone_env, ws
    finally:
        services.set_credit_enforcement_enabled(
            client.app.state.settings.workspace_credit_enforcement_enabled
        )


def fund(client, ws, credits):
    with client.app.state.session_factory() as session:
        session.get(WorkspaceCreditAccountRecord, ws).balance_credits = credits
        session.commit()


def state(client, ws):
    with client.app.state.session_factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, ws)
        holds = [
            (r.charge_action, r.status)
            for r in session.scalars(
                select(CreditReservationRecord).where(
                    CreditReservationRecord.owner_type == "video_voice"
                )
            )
        ]
        return (account.balance_credits, account.reserved_credits), holds


def test_voice_clone_settles_once_when_ready(priced):
    env, ws = priced
    client = env[0]
    fund(client, ws, 100)
    first = create(env)
    assert first.status_code == 200, first.text
    # Same sample again returns the original voice and never charges twice.
    assert create(env).json()["id"] == first.json()["id"]
    assert state(client, ws) == ((40, 0), [("voice_clone", "settled")])


def test_voice_clone_without_balance_stores_nothing(priced):
    env, ws = priced
    client, *_, state_ = env
    fund(client, ws, 59)
    rejected = create(env)
    assert rejected.status_code == 402, rejected.text
    assert rejected.json()["error"]["code"] == "BUDGET_LIMIT_EXCEEDED"
    assert state_["created"] == []
    with client.app.state.session_factory() as session:
        assert session.scalar(select(VideoClonedVoiceRecord.id)) is None
    media = client.app.state.settings.video_media_dir / "voice-clones"
    assert not any(path.is_file() for path in media.rglob("*"))
    assert state(client, ws) == ((59, 0), [])
