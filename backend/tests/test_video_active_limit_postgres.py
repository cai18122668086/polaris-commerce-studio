"""Per-user active video cap is atomic under concurrent submits (PostgreSQL)."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.errors import ApiError
from app.models import UserRecord, WorkspaceRecord
from app.video_generation import reserve_video_slot
from app.video_generation_models import VideoAvatarRecord, VideoGenerationRecord


@pytest.fixture
def postgres_factory():
    raw = os.environ.get("POLARIS_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set POLARIS_TEST_DATABASE_URL for isolated PostgreSQL tests")
    url = make_url(raw)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not url.database
        or not any(token in url.database.lower() for token in ("test", "ci"))
    ):
        raise pytest.UsageError("requires a local test/CI database")
    schema = "video_cap_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url.update_query_dict({"options": f"-csearch_path={schema}"})
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        Base.metadata.create_all(engine)
        with factory() as session:
            session.add(UserRecord(id="usr_v", auth_provider="test", auth_subject="v"))
            session.flush()
            session.add(
                WorkspaceRecord(id="ws_v", name="V", created_by_user_id="usr_v")
            )
            session.add(VideoAvatarRecord(id="av_v", source="test", name="A"))
            session.commit()
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _submit(factory, barrier):
    with factory() as session:
        barrier.wait()
        try:
            reserve_video_slot(session, "usr_v", 1)
        except ApiError as error:
            session.rollback()
            return error.code
        # Widen the race window between check and insert.
        time.sleep(0.3)
        session.add(
            VideoGenerationRecord(
                id=str(uuid4()),
                workspace_id="ws_v",
                owner_user_id="usr_v",
                avatar_id="av_v",
                request_id=str(uuid4()),
                request_hash="0" * 64,
                kind="template",
                status="queued",
                details={},
            )
        )
        session.commit()
        return "accepted"


def test_concurrent_submits_cannot_exceed_the_active_video_cap(postgres_factory):
    barrier = Barrier(4)
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: _submit(postgres_factory, barrier), range(4)))
    assert sorted(results) == ["USER_ACTIVE_VIDEO_LIMIT_REACHED"] * 3 + ["accepted"]
    with postgres_factory() as session:
        count = session.scalar(select(func.count()).select_from(VideoGenerationRecord))
        assert count == 1
