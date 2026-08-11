"""Persistence owned only by the domestic main-image workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type


class DomesticMainImageTaskRecord(TimestampMixin, Base):
    __tablename__ = "domestic_main_image_tasks"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_main_image_task_revision"),
        UniqueConstraint(
            "workspace_id",
            "created_by_user_id",
            "create_idempotency_key",
            name="uq_main_image_task_create_idem",
        ),
        Index(
            "ix_main_image_tasks_workspace_created",
            "workspace_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    create_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    create_request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_status: Mapped[str] = mapped_column(
        String(24), default="RUNNING", nullable=False
    )
    skill_state: Mapped[str] = mapped_column(String(48), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    session_payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    raw_input: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    identity_contract: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    plan_payload: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    generation_request: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    skill_name: Mapped[str] = mapped_column(String(96), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(32), nullable=False)
    skill_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_file_inventory: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type(), nullable=False
    )
    source_zip_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    startup_git_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    image_model: Mapped[str | None] = mapped_column(String(96))
    image_model_version: Mapped[str | None] = mapped_column(String(96))
    provider_capability_status: Mapped[str] = mapped_column(
        String(32), default="UNVERIFIED", nullable=False
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(Text)


class DomesticMainImageSourceRecord(TimestampMixin, Base):
    __tablename__ = "domestic_main_image_sources"
    __table_args__ = (
        UniqueConstraint("task_id", "ordinal", name="uq_main_image_source_order"),
        UniqueConstraint(
            "task_id", "evidence_id", name="uq_main_image_source_evidence"
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("domestic_main_image_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_role: Mapped[str] = mapped_column(String(32), nullable=False)
    runtime_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    asset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class DomesticMainImageCommandRecord(TimestampMixin, Base):
    __tablename__ = "domestic_main_image_commands"
    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_main_image_command_seq"),
        Index("ix_main_image_commands_task", "task_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("domestic_main_image_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    command: Mapped[str] = mapped_column(String(48), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    committed_revision: Mapped[int | None] = mapped_column(Integer)
    command_input: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    argv: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False)
    stdout: Mapped[str] = mapped_column(Text, nullable=False)
    stderr: Mapped[str] = mapped_column(Text, nullable=False)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    session_before_sha256: Mapped[str | None] = mapped_column(String(64))
    session_after_sha256: Mapped[str | None] = mapped_column(String(64))
    transition_committed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class DomesticMainImageGenerationRecord(TimestampMixin, Base):
    __tablename__ = "domestic_main_image_generations"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_idempotency_key",
            name="uq_main_image_generation_provider_idem",
        ),
        UniqueConstraint(
            "task_id",
            "page_index",
            "generation_token_sha256",
            "attempt",
            "operation",
            name="uq_main_image_generation_operation",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("domestic_main_image_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    generation_token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(96), nullable=False)
    model_version: Mapped[str] = mapped_column(String(96), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_prompt_sha256: Mapped[str | None] = mapped_column(String(64))
    reference_asset_ids: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    reference_roles: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    reference_order: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    edit_target: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    provider_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    request_status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT")
    )
    cost_known: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cost_amount_micros: Mapped[int | None] = mapped_column(BigInteger)


class DomesticMainImagePageRecord(TimestampMixin, Base):
    __tablename__ = "domestic_main_image_pages"
    __table_args__ = (
        UniqueConstraint("task_id", "page_index", name="uq_main_image_task_page"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("domestic_main_image_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT")
    )
    accepted_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT")
    )
    display_status: Mapped[str] = mapped_column(
        String(48), default="WAITING", nullable=False
    )
    residual_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type(), default=list, nullable=False
    )
    audit_retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    candidate_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
