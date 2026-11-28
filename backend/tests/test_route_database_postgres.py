"""Guard for the CI job that reruns the v3 route tests on PostgreSQL: when
POLARIS_TEST_ROUTE_DATABASE_URL is set, the shared client must really talk to
PostgreSQL in its own schema (otherwise the job silently tests SQLite)."""

import os

import pytest
from sqlalchemy import text

pytest_plugins = ["tests.test_video_projects"]

# Same name as conftest.ROUTE_POSTGRES_ENV.
ROUTE_POSTGRES_ENV = "POLARIS_TEST_ROUTE_DATABASE_URL"


def _require_route_postgres():
    if not os.environ.get(ROUTE_POSTGRES_ENV):
        pytest.skip(f"set {ROUTE_POSTGRES_ENV} to rerun route tests on PostgreSQL")


def test_external_auth_video_client_also_uses_postgres(video):
    # Most v3 route tests use this fixture, which builds its own SQLite
    # Settings; the conftest engine hook must still move it to PostgreSQL.
    _require_route_postgres()
    _assert_isolated_postgres(video[0].app.state.engine)


def test_route_client_uses_an_isolated_postgres_schema(client):
    _require_route_postgres()
    _assert_isolated_postgres(client.app.state.engine)


def _assert_isolated_postgres(engine):
    assert engine.dialect.name == "postgresql"
    with engine.connect() as connection:
        schema = connection.execute(text("SELECT current_schema()")).scalar_one()
        assert schema.startswith("route_")
        assert connection.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = 'video_work_items'"
            ),
            {"s": schema},
        ).scalar_one() == 1
