"""Guard for the CI job that reruns the v3 route tests on PostgreSQL: when
POLARIS_TEST_ROUTE_DATABASE_URL is set, the shared client must really talk to
PostgreSQL in its own schema (otherwise the job silently tests SQLite)."""

import os

import pytest
from sqlalchemy import text

# Same name as conftest.ROUTE_POSTGRES_ENV (tests is not a package).
ROUTE_POSTGRES_ENV = "POLARIS_TEST_ROUTE_DATABASE_URL"


def test_route_client_uses_an_isolated_postgres_schema(client):
    if not os.environ.get(ROUTE_POSTGRES_ENV):
        pytest.skip(f"set {ROUTE_POSTGRES_ENV} to rerun route tests on PostgreSQL")
    engine = client.app.state.engine
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
