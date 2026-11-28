import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _unpriced_video_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests start with video actions unpriced and opt in to the prices they test.

    Production defaults (video_credit_prices.DEFAULT_PRICES) are pinned in
    test_video_credit_prices_defaults.py, which clears this override itself.
    """
    monkeypatch.setenv("POLARIS_VIDEO_CREDIT_PRICES", "{}")


@pytest.fixture(autouse=True)
def _fresh_planner_route_breaker() -> Iterator[None]:
    """The route circuit breaker is process-wide; isolate it per test."""
    from app.xinghe_agent import PLANNER_ROUTE_BREAKER

    PLANNER_ROUTE_BREAKER.reset()
    yield
    PLANNER_ROUTE_BREAKER.reset()


ROUTE_POSTGRES_ENV = "POLARIS_TEST_ROUTE_DATABASE_URL"


@pytest.fixture
def _route_database_url(tmp_path) -> Iterator[str]:
    """SQLite by default; a fresh PostgreSQL schema per test when
    POLARIS_TEST_ROUTE_DATABASE_URL points at a local test/CI database.

    CI runs the v3 route tests a second time this way, because SQLite accepts
    queries PostgreSQL rejects (GROUP BY, varchar lengths, aborted
    transactions, timezone-aware timestamps).
    """

    raw = os.environ.get(ROUTE_POSTGRES_ENV)
    if not raw:
        yield f"sqlite:///{tmp_path / 'test.db'}"
        return
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(raw)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not url.database
        or not any(token in url.database.lower() for token in ("test", "ci"))
    ):
        raise pytest.UsageError(
            f"{ROUTE_POSTGRES_ENV} requires a local test/CI database"
        )
    schema = "route_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = url.update_query_dict(
        {"options": f"-csearch_path={schema}", "application_name": schema}
    )
    try:
        yield scoped.render_as_string(hide_password=False)
    finally:
        with admin.begin() as connection:
            # The app engine is not disposed by TestClient; close its pooled
            # connections so they neither block the drop nor pile up.
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE application_name = :name AND pid <> pg_backend_pid()"
                ),
                {"name": schema},
            )
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture(autouse=True)
def _route_engines_on_postgres(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With POLARIS_TEST_ROUTE_DATABASE_URL set, every app engine a test builds
    from a SQLite URL (e.g. the external-auth ``video`` fixture's own
    Settings) uses this test's PostgreSQL schema instead."""

    if not os.environ.get(ROUTE_POSTGRES_ENV):
        return
    from app import database
    from app import main as app_main

    scoped: str = request.getfixturevalue("_route_database_url")
    real = database.build_database

    def build(database_url: str, **options: object):  # type: ignore[no-untyped-def]
        if database_url.startswith("sqlite"):
            database_url = scoped
        return real(database_url, **options)  # type: ignore[arg-type]

    monkeypatch.setattr(database, "build_database", build)
    monkeypatch.setattr(app_main, "build_database", build)


@pytest.fixture
def settings(tmp_path, _route_database_url) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        auth_mode="development",
        development_user_id="usr_test",
        development_workspace_id="ws_test",
        development_workspace_name="测试工作区",
        access_url_secret="test-access-url-secret",
        database_url=_route_database_url,
        auto_create_schema=True,
        storage_backend="local",
        storage_dir=tmp_path / "storage",
        aurora_work_root=tmp_path / "aurora-main-image",
        # Never let route tests read, overwrite, or delete the workstation's
        # human-authorized ecommerce browser profiles.
        ecommerce_session_dir=(
            tmp_path / "ecommerce-session" / "domestic-taobao-tmall"
        ),
        ecommerce_1688_session_dir=(
            tmp_path / "ecommerce-session" / "domestic-1688"
        ),
        ecommerce_jd_session_dir=(
            tmp_path / "ecommerce-session" / "domestic-jd"
        ),
        ecommerce_pinduoduo_session_dir=(
            tmp_path / "ecommerce-session" / "domestic-pinduoduo"
        ),
        ecommerce_login_enabled=True,
        ecommerce_login_transport="local_visible",
        auto_process_jobs=False,
        task_dispatcher="inline",
        mock_job_delay_seconds=0,
        workspace_credit_enforcement_enabled=True,
        max_upload_bytes=2 * 1024 * 1024,
        max_image_pixels=2_000_000,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
