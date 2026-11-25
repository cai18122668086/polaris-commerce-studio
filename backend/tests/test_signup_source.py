from dataclasses import replace
from datetime import timedelta

import pytest

from app.auth import signup_source
from app.models import UserRecord, UserSignupSourceRecord, utc_now
from tests.test_auth_external import verified_identity
from tests.test_growth_rewards import site  # noqa: F401  (pytest fixture)


def visit(site, subject, source=None, age=0):  # noqa: F811
    client, backend = site
    backend.identity = replace(
        verified_identity(primary_user_id=subject, email=subject + "@example.test"),
        joined_at=utc_now() - timedelta(days=age),
    )
    headers = {"X-Signup-Source": source} if source is not None else {}
    result = client.get("/api/v1/workspaces", headers=headers)
    assert result.status_code == 200, result.text


def recorded(site):  # noqa: F811
    client, _ = site
    with client.app.state.session_factory() as session:
        return {
            r.user_id: r.source
            for r in session.query(UserSignupSourceRecord).all()
        }


def user_id(site, subject):  # noqa: F811
    client, _ = site
    with client.app.state.session_factory() as session:
        return session.query(UserRecord).filter_by(auth_subject=subject).one().id


def test_new_account_keeps_the_link_it_came_from_once(site):  # noqa: F811
    visit(site, "fresh", "XHS-01")
    uid = user_id(site, "fresh")
    assert recorded(site) == {uid: "xhs-01"}
    # 之后再带别的来源访问，不改已经记下的来源
    visit(site, "fresh", "dy-02")
    assert recorded(site) == {uid: "xhs-01"}


def test_existing_accounts_and_bad_codes_are_not_recorded(site):  # noqa: F811
    visit(site, "plain")
    visit(site, "weird", "<script>")
    visit(site, "toolong", "a" * 31)
    assert recorded(site) == {}


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("xhs-01", "xhs-01"),
        (" DY_02 ", "dy_02"),
        ("mp", "mp"),
        ("", ""),
        ("-xhs", ""),
        ("xhs 01", ""),
        ("小红书", ""),
        ("a" * 30, "a" * 30),
        ("a" * 31, ""),
    ],
)
def test_signup_source_normalisation(raw, code):
    assert signup_source(raw) == code


def test_migration_creates_the_table_the_model_uses(site):  # noqa: F811
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    visit(site, "before")
    client, _ = site
    with client.app.state.session_factory() as session:
        engine = session.get_bind()
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261126_0054_user_signup_sources.py"
    )
    spec = importlib.util.spec_from_file_location("signup_source_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261125_0053"
    with engine.begin() as connection:
        UserSignupSourceRecord.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        columns = {c["name"] for c in inspect(connection).get_columns("user_signup_sources")}
    assert columns == {c.name for c in UserSignupSourceRecord.__table__.columns}
    visit(site, "after", "mp-01")
    assert recorded(site) == {user_id(site, "after"): "mp-01"}
