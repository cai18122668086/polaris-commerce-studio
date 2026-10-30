"""Durable support records; every balance change also has an immutable ledger."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type


class CustomerSupportRecord(TimestampMixin, Base):
    __tablename__ = "customer_support_profiles"
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), primary_key=True
    )
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class CreditAdjustmentRecord(TimestampMixin, Base):
    __tablename__ = "admin_credit_adjustments"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "actor_user_id",
            "request_key",
            name="uq_admin_credit_adjustment_request",
        ),
        CheckConstraint(
            "credits > 0 AND kind IN ('gift','compensation')",
            name="ck_admin_credit_adjustment_terms",
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT")
    )
    ledger_entry_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ledger_entries.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )


class SupportCaseRecord(TimestampMixin, Base):
    __tablename__ = "customer_support_cases"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "request_key", name="uq_customer_support_request"
        ),
        CheckConstraint(
            "status IN ('open','in_progress','resolved')", name="ck_support_case_status"
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), index=True
    )
    issue: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # Historical staff records remain private; customer requests retain their creator.
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    request_key: Mapped[str | None] = mapped_column(String(128))


class ManualRefundRecord(TimestampMixin, Base):
    __tablename__ = "manual_credit_refunds"
    __table_args__ = (
        UniqueConstraint("purchase_id", "request_key", name="uq_manual_refund_request"),
        CheckConstraint(
            "amount_fen > 0 AND credits >= 0 "
            "AND status IN ('processing','completed','rejected')",
            name="ck_manual_refund_terms",
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    purchase_id: Mapped[str] = mapped_column(
        ForeignKey("credit_purchases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="processing", nullable=False
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    allocations: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    receipt_reference: Mapped[str | None] = mapped_column(String(500))
    result_note: Mapped[str | None] = mapped_column(String(500))
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_ledger_entry_id: Mapped[int] = mapped_column(
        ForeignKey("credit_ledger_entries.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    result_ledger_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_ledger_entries.id", ondelete="RESTRICT"), unique=True
    )
