"""Consent retries/withdrawals serialize on the user, preserving earlier receipts."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, select

from app.models import ProcessingConsentRecord
from app.processing_consent import (
    NOTICE_HASH,
    POLICY_VERSION,
    record_consent,
    withdraw_consent,
)
from tests.test_credit_payments_postgres import (
    postgres_credits as postgres_credits,  # noqa: F401
)

CHOICE = {
    "policyVersion": POLICY_VERSION,
    "hongKongProcessing": True,
    "aiTraining": True,
}


def test_concurrent_acceptance_records_one_current_receipt(postgres_credits):
    factory, _ = postgres_credits
    gate = Barrier(8)

    def accept():
        gate.wait(timeout=10)
        with factory() as session:
            record = record_consent(session, "usr_test", CHOICE, source="account")
            session.commit()
            return record.id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = [
            future.result(timeout=30)
            for future in [pool.submit(accept) for _ in range(8)]
        ]
    assert len(set(ids)) == 1
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(ProcessingConsentRecord))
            == 1
        )
        assert session.get(ProcessingConsentRecord, ids[0]).notice_sha256 == NOTICE_HASH


def test_reacceptance_after_withdrawal_retains_the_original_receipt(postgres_credits):
    factory, _ = postgres_credits
    with factory() as session:
        first = record_consent(session, "usr_test", CHOICE, source="account")
        original = first.id
        session.commit()
    with factory() as session:
        withdraw_consent(session, "usr_test")
        session.commit()
    with factory() as session:
        second = record_consent(session, "usr_test", CHOICE, source="account")
        session.commit()
        assert second.id != original
        assert session.get(ProcessingConsentRecord, original).withdrawn_at is not None
        assert (
            session.scalar(select(func.count()).select_from(ProcessingConsentRecord))
            == 2
        )
