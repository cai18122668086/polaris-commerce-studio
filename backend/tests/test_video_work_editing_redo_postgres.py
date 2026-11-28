"""B5 换模板重剪 and the batch editing routes on PostgreSQL.

The SQLite route tests of ``test_video_work_editing`` run again here against a
real server (row locks, JSON columns and the queue estimate only behave for
real there), plus concurrent redo clicks that must build exactly one round.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.main import create_app
from app.video_editing_task_models import EditingPlanningTaskRecord
from app.video_work_editing_models import VideoWorkEditingRunRecord
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_projects import EMAIL, base
from tests.test_video_work_editing import (  # noqa: F401  (collected again on PG)
    OTHER_TEMPLATE,
    drive_to_render,
    finish_renders,
    finished_batch,
    poll,
    test_a_failed_redo_keeps_the_finished_work_and_its_video,
    test_batch_queues_beyond_two_and_finishes_every_item,
    test_batch_redo_takes_every_finished_item_and_checks_credits_once,
    test_redo_is_refused_whole_when_credits_cannot_cover_it,
    test_redo_needs_an_edited_item_of_the_owner,
    test_redo_one_item_with_another_template_keeps_the_old_cut,
    test_repeated_clicks_and_polls_never_create_or_charge_twice,
    test_repeated_redo_clicks_build_one_round_and_pay_once,
)


@pytest.fixture
def postgres_url():
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
    schema = "editing_redo_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        yield url.update_query_dict({"options": f"-csearch_path={schema}"})
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def video(tmp_path, postgres_url):
    """``tests.test_video_projects.video`` on a PostgreSQL schema of its own."""
    auth = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
    settings = external_settings(tmp_path)
    settings.database_url = postgres_url.render_as_string(hide_password=False)
    with TestClient(create_app(settings, auth)) as client:
        assert client.app.state.session_factory.kw["bind"].dialect.name == "postgresql"
        user = client.get("/api/v1/me").json()["id"]
        ws = client.get("/api/v1/workspaces").json()[0]["id"]
        yield client, auth, ws, user, settings
        client.app.state.session_factory.kw["bind"].dispose()


def test_concurrent_redo_clicks_build_exactly_one_round_on_postgres(
    video, tmp_path, monkeypatch
):
    client, ws, settings, factory, semantic, batch = finished_batch(
        video, tmp_path, monkeypatch, count=2
    )
    item_id = poll(client, ws, batch)["editing"][0]["item_id"]
    same = str(uuid4())
    calls = [
        (f"/work-items/{item_id}/editing-redo", same),
        (f"/work-items/{item_id}/editing-redo", same),
        (f"/work-items/{item_id}/editing-redo", None),
        (f"/work-batches/{batch['id']}/editing-redo", None),
        (f"/work-batches/{batch['id']}/editing-redo", None),
        (f"/work-items/{item_id}/editing-redo", None),
    ]

    def click(call):
        path, request_id = call
        return client.post(
            base(ws) + path,
            json={
                "request_id": request_id or str(uuid4()),
                "template_id": OTHER_TEMPLATE,
            },
        )

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        responses = list(pool.map(click, calls))
    assert [r.status_code for r in responses] == [200] * len(calls), [
        r.text for r in responses if r.status_code != 200
    ]
    with factory() as session:
        runs = session.scalars(select(VideoWorkEditingRunRecord)).all()
        # Every item was re-edited at most once, whatever won the race.
        assert {run.attempt for run in runs} <= {1, 2}
        assert all(
            len(run.options.get("history") or []) == run.attempt - 1 for run in runs
        )
        target = session.get(VideoWorkEditingRunRecord, item_id)
        assert target.attempt == 2
    paid = generates_on(factory)
    drive_to_render(client, ws, batch, factory, settings, semantic)
    finish_renders(factory)
    poll(client, ws, batch)
    redone = sum(1 for run in runs if run.attempt == 2)
    # Both new cuts may share one paid planning when their requests are identical.
    assert paid < generates_on(factory) <= paid + redone


def generates_on(factory):
    with factory() as session:
        return session.scalar(
            select(func.count())
            .select_from(EditingPlanningTaskRecord)
            .where(EditingPlanningTaskRecord.mode == "generate")
        )
