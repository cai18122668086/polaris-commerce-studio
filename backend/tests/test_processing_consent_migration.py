"""The consent table preserves accounts, tasks and frozen credit prices."""

import importlib.util
from copy import deepcopy
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select

from app import services
from app.models import (
    CreditLedgerEntryRecord,
    ProcessingConsentRecord,
    UserRecord,
    WorkspaceCreditAccountRecord,
)
from tests.test_customer_credit_billing import WORKSPACE, seed_job


def test_processing_consent_migration_keeps_existing_financial_and_identity_records(
    client,
):
    with client.app.state.session_factory() as session:
        job, _ = seed_job(
            session,
            kind="detail_pack",
            count=2,
            configuration={"settings": {"detail_speed": "fast"}},
        )
        reservation = services.reserve_image_credits(session, WORKSPACE, job)
        session.commit()
        original = (
            reservation.reserved_credits,
            deepcopy(reservation.pricing_snapshot),
            session.get(WorkspaceCreditAccountRecord, WORKSPACE).balance_credits,
            session.get(UserRecord, "usr_test").auth_subject,
            session.scalar(select(func.count()).select_from(CreditLedgerEntryRecord)),
        )
        engine = session.get_bind()
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261030_0034_processing_consents.py"
    )
    spec = importlib.util.spec_from_file_location("processing_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        ProcessingConsentRecord.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(ProcessingConsentRecord))
            == 0
        )
        session.add(
            reservation
        )  # Reload the frozen reservation from the migrated database.
        session.refresh(reservation)
        assert original == (
            reservation.reserved_credits,
            reservation.pricing_snapshot,
            session.get(WorkspaceCreditAccountRecord, WORKSPACE).balance_credits,
            session.get(UserRecord, "usr_test").auth_subject,
            session.scalar(select(func.count()).select_from(CreditLedgerEntryRecord)),
        )
