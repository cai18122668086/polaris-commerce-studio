from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .domain import (
    AssetLifecycleStatus,
    AssetMediaKind,
    AssetOriginKind,
    AttemptStatus,
    CreditReservationStatus,
    IdempotencyStatus,
    JobItemStatus,
    JobStatus,
    JobType,
    MembershipRole,
    MembershipStatus,
    OutboxStatus,
    PlanValidationStatus,
    UsageCompleteness,
    UserStatus,
    WorkspaceStatus,
)

IDENTITY_TYPE = BigInteger().with_variant(Integer(), "sqlite")


def json_type() -> JSON:
    return JSON().with_variant(postgresql.JSONB(), "postgresql")


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class UserRecord(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("auth_provider", "auth_subject", name="uq_users_auth"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    auth_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    auth_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email_normalized: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(
        String(16), default=UserStatus.ACTIVE.value, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceRecord(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=WorkspaceStatus.ACTIVE.value, nullable=False, index=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceMemberRecord(TimestampMixin, Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        String(16), default=MembershipRole.MEMBER.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default=MembershipStatus.ACTIVE.value, nullable=False
    )


class WorkspaceLimitRecord(TimestampMixin, Base):
    __tablename__ = "workspace_limits"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    storage_quota_bytes: Mapped[int] = mapped_column(
        BigInteger, default=10 * 1024 * 1024 * 1024, nullable=False
    )
    max_active_jobs: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    daily_provider_cost_limit_micros: Mapped[int] = mapped_column(
        BigInteger, default=10_000_000, nullable=False
    )
    monthly_provider_cost_limit_micros: Mapped[int] = mapped_column(
        BigInteger, default=100_000_000, nullable=False
    )
    max_upload_bytes: Mapped[int] = mapped_column(
        BigInteger, default=20 * 1024 * 1024, nullable=False
    )


class AssetRecord(Base):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("byte_size > 0", name="ck_assets_byte_size_positive"),
        CheckConstraint("width IS NULL OR width > 0", name="ck_assets_width_positive"),
        CheckConstraint(
            "height IS NULL OR height > 0", name="ck_assets_height_positive"
        ),
        UniqueConstraint("workspace_id", "id", name="uq_assets_workspace_id"),
        UniqueConstraint(
            "storage_provider",
            "storage_bucket",
            "object_key",
            "object_version",
            name="uq_assets_storage_object",
        ),
        Index(
            "ix_assets_workspace_created",
            "workspace_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    media_kind: Mapped[str] = mapped_column(
        String(16), default=AssetMediaKind.IMAGE.value, nullable=False
    )
    origin_kind: Mapped[str] = mapped_column(
        String(16), default=AssetOriginKind.UPLOAD.value, nullable=False
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(16), default=AssetLifecycleStatus.PENDING.value, nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    object_version: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    etag: Mapped[str | None] = mapped_column(String(255))
    asset_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        MutableDict.as_mutable(json_type()),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Compatibility aliases used only by the Phase 1 migration/backfill.
    @property
    def filename(self) -> str:
        return self.original_filename


class JobRecord(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_jobs_progress"),
        CheckConstraint(
            "expected_item_count >= 0", name="ck_jobs_expected_count_nonnegative"
        ),
        CheckConstraint(
            "succeeded_item_count >= 0 AND failed_item_count >= 0",
            name="ck_jobs_result_counts_nonnegative",
        ),
        CheckConstraint(
            "succeeded_item_count + failed_item_count <= expected_item_count",
            name="ck_jobs_result_counts_bounded",
        ),
        CheckConstraint(
            "actual_cost_micros IS NULL OR actual_cost_micros >= 0",
            name="ck_jobs_actual_cost_nonnegative",
        ),
        CheckConstraint(
            "api_request_count >= 0",
            name="ck_jobs_api_request_count_nonnegative",
        ),
        CheckConstraint(
            """
            (
                status IN ('partial', 'completed', 'failed', 'cancelled')
                AND finished_at IS NOT NULL
                AND (
                    (
                        status = 'completed'
                        AND succeeded_item_count = expected_item_count
                        AND failed_item_count = 0
                    )
                    OR (
                        status = 'partial'
                        AND succeeded_item_count > 0
                        AND succeeded_item_count < expected_item_count
                    )
                    OR (status = 'failed' AND succeeded_item_count = 0)
                    OR status = 'cancelled'
                )
            )
            OR (
                status NOT IN ('partial', 'completed', 'failed', 'cancelled')
                AND finished_at IS NULL
            )
            """,
            name="ck_jobs_terminal_consistency",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_jobs_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "root_job_id"],
            ["jobs.workspace_id", "jobs.id"],
            name="fk_jobs_workspace_root_job",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "retry_of_job_id"],
            ["jobs.workspace_id", "jobs.id"],
            name="fk_jobs_workspace_retry_of_job",
        ),
        Index("ix_jobs_workspace_created", "workspace_id", "created_at", "id"),
        Index(
            "ix_jobs_workspace_status_created",
            "workspace_id",
            "status",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_jobs_workspace_type_status_created",
            "workspace_id",
            "type",
            "status",
            "created_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[str] = mapped_column(
        String(32), default=JobType.LOCAL_EDIT.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default=JobStatus.DRAFT.value, nullable=False
    )
    stage: Mapped[str | None] = mapped_column(String(32))
    display_name: Mapped[str | None] = mapped_column(String(160))
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(json_type()),
        default=dict,
        nullable=False,
    )
    configuration_schema: Mapped[str] = mapped_column(
        String(32), default="v1", nullable=False
    )
    prompt_version: Mapped[str] = mapped_column(
        String(64), default="phase1.1-mock", nullable=False
    )
    strategy_version: Mapped[str] = mapped_column(
        String(64), default="phase1.1-mock", nullable=False
    )
    release_version: Mapped[str] = mapped_column(
        String(64), default="phase1.1", nullable=False
    )
    root_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True
    )
    retry_of_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True
    )
    retry_scope: Mapped[str | None] = mapped_column(String(16))
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expected_item_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    succeeded_item_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    failed_item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    estimated_cost_min_micros: Mapped[int | None] = mapped_column(BigInteger)
    estimated_cost_max_micros: Mapped[int | None] = mapped_column(BigInteger)
    actual_cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    estimated_credits: Mapped[int | None] = mapped_column(BigInteger)
    actual_credits: Mapped[int | None] = mapped_column(BigInteger)
    usage_completeness: Mapped[str] = mapped_column(
        String(16), default=UsageCompleteness.NONE.value, nullable=False
    )
    api_request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobItemRecord(TimestampMixin, Base):
    __tablename__ = "job_items"
    __table_args__ = (
        UniqueConstraint("job_id", "item_key", name="uq_job_items_key"),
        UniqueConstraint("job_id", "ordinal", name="uq_job_items_ordinal"),
        UniqueConstraint(
            "workspace_id", "job_id", "id", name="uq_job_items_workspace_job_id"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["jobs.workspace_id", "jobs.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), nullable=False)
    job_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    item_key: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=JobItemStatus.PENDING.value, nullable=False
    )
    stage: Mapped[str | None] = mapped_column(String(32))
    quality: Mapped[str | None] = mapped_column(String(16))
    configuration: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(json_type()),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_job_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_items.id"), nullable=True
    )
    result_source: Mapped[str | None] = mapped_column(String(16))
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobAssetRecord(Base):
    __tablename__ = "job_assets"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_job_assets_ordinal"),
        Index(
            "uq_job_assets_role_ordinal",
            "job_id",
            "job_item_id",
            "direction",
            "role",
            "ordinal",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["jobs.workspace_id", "jobs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "asset_id"],
            ["assets.workspace_id", "assets.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "job_id", "job_item_id"],
            ["job_items.workspace_id", "job_items.job_id", "job_items.id"],
            name="fk_job_assets_workspace_job_item",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(IDENTITY_TYPE, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(40), nullable=False)
    job_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    job_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_items.id", ondelete="CASCADE")
    )
    asset_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_deliverable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validation: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(json_type()),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class JobPlanRecord(Base):
    __tablename__ = "job_plans"
    __table_args__ = (
        UniqueConstraint("job_id", "revision", name="uq_job_plans_revision"),
        ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["jobs.workspace_id", "jobs.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), nullable=False)
    job_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(32), default="v1", nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(
        String(16), default=PlanValidationStatus.PENDING.value, nullable=False
    )
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type(), default=list, server_default=text("'[]'"), nullable=False
    )
    validator_version: Mapped[str] = mapped_column(
        String(64), default="phase1.1", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobAttemptRecord(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        CheckConstraint(
            "attempt_no > 0",
            name="ck_job_attempts_attempt_no_positive",
        ),
        UniqueConstraint("job_item_id", "attempt_no", name="uq_job_attempt_no"),
        UniqueConstraint(
            "provider", "provider_idempotency_key", name="uq_attempt_provider_idem"
        ),
        UniqueConstraint(
            "workspace_id",
            "job_id",
            "job_item_id",
            "id",
            name="uq_job_attempts_workspace_job_item_id",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["jobs.workspace_id", "jobs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "job_id", "job_item_id"],
            ["job_items.workspace_id", "job_items.job_id", "job_items.id"],
            name="fk_job_attempts_workspace_job_item",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), nullable=False)
    job_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    job_item_id: Mapped[str] = mapped_column(
        ForeignKey("job_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=AttemptStatus.CLAIMED.value, nullable=False
    )
    lease_token: Mapped[str] = mapped_column(String(64), nullable=False)
    leased_by: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    provider_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AmazonSuiteReviewAttemptRecord(TimestampMixin, Base):
    __tablename__ = "amazon_suite_review_attempts"
    __table_args__ = (
        CheckConstraint(
            "review_round > 0",
            name="ck_amazon_suite_review_round_positive",
        ),
        CheckConstraint(
            "actual_cost_micros IS NULL OR actual_cost_micros >= 0",
            name="ck_amazon_suite_review_actual_cost_nonnegative",
        ),
        CheckConstraint(
            "estimated_cost_micros IS NULL OR estimated_cost_micros >= 0",
            name="ck_amazon_suite_review_estimated_cost_nonnegative",
        ),
        UniqueConstraint(
            "job_id",
            "review_round",
            "output_asset_set_hash",
            name="uq_amazon_suite_review_job_round_output",
        ),
        UniqueConstraint(
            "provider",
            "provider_idempotency_key",
            name="uq_amazon_suite_review_provider_idem",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["jobs.workspace_id", "jobs.id"],
            name="fk_amazon_suite_review_workspace_job",
            ondelete="CASCADE",
        ),
        Index(
            "ix_amazon_suite_review_job_status_lease",
            "workspace_id",
            "job_id",
            "status",
            "lease_expires_at",
        ),
        Index(
            "ix_amazon_suite_review_provider_request",
            "provider",
            "provider_request_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(40), nullable=False)
    job_id: Mapped[str] = mapped_column(String(40), nullable=False)
    review_round: Mapped[int] = mapped_column(Integer, nullable=False)
    output_asset_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="claimed", server_default=text("'claimed'"), nullable=False
    )
    lease_token: Mapped[str] = mapped_column(String(64), nullable=False)
    leased_by: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    raw_usage: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(json_type()),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    normalized_usage: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(json_type()),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    actual_cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    estimated_cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_call_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageEventRecord(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint(
            "estimated_cost_micros IS NULL OR estimated_cost_micros >= 0",
            name="ck_usage_estimated_cost",
        ),
        CheckConstraint(
            "actual_cost_micros IS NULL OR actual_cost_micros >= 0",
            name="ck_usage_actual_cost",
        ),
        UniqueConstraint("attempt_id", name="uq_usage_events_attempt_id"),
        ForeignKeyConstraint(
            ["workspace_id", "job_id", "job_item_id", "attempt_id"],
            [
                "job_attempts.workspace_id",
                "job_attempts.job_id",
                "job_attempts.job_item_id",
                "job_attempts.id",
            ],
            name="fk_usage_events_workspace_job_item_attempt",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(IDENTITY_TYPE, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_item_id: Mapped[str] = mapped_column(
        ForeignKey("job_items.id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("job_attempts.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cached_tokens: Mapped[int | None] = mapped_column(BigInteger)
    input_image_count: Mapped[int | None] = mapped_column(Integer)
    output_image_count: Mapped[int | None] = mapped_column(Integer)
    quality: Mapped[str | None] = mapped_column(String(16))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    usage_reported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw_usage: Mapped[dict[str, Any]] = mapped_column(
        json_type(), default=dict, server_default=text("'{}'"), nullable=False
    )
    pricing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    estimated_cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    actual_cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class IdempotencyRequestRecord(TimestampMixin, Base):
    __tablename__ = "idempotency_requests"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "method",
            "route_template",
            "idempotency_key",
            name="uq_idempotency_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    route_template: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=IdempotencyStatus.IN_PROGRESS.value, nullable=False
    )
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(40))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class OutboxEventRecord(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_claim",
            "available_at",
            "created_at",
            postgresql_where=text("status IN ('pending', 'failed')"),
            sqlite_where=text("status IN ('pending', 'failed')"),
        ),
        Index(
            "ix_outbox_events_reclaim",
            "locked_at",
            "created_at",
            postgresql_where=text("status = 'publishing' AND locked_at IS NOT NULL"),
            sqlite_where=text("status = 'publishing' AND locked_at IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=OutboxStatus.PENDING.value, nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class WorkspaceCreditAccountRecord(TimestampMixin, Base):
    __tablename__ = "workspace_credit_accounts"
    __table_args__ = (
        CheckConstraint("balance_credits >= 0", name="ck_credit_balance_nonnegative"),
        CheckConstraint("reserved_credits >= 0", name="ck_credit_reserved_nonnegative"),
        CheckConstraint(
            "reserved_credits <= balance_credits", name="ck_credit_reserved_bounded"
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    balance_credits: Mapped[int] = mapped_column(
        BigInteger, default=10_000, nullable=False
    )
    reserved_credits: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CreditReservationRecord(TimestampMixin, Base):
    __tablename__ = "credit_reservations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_credit_reservations_workspace_id",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["jobs.workspace_id", "jobs.id"],
            name="fk_credit_reservations_workspace_job",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    reserved_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settled_credits: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=CreditReservationStatus.ACTIVE.value, nullable=False
    )


class CreditLedgerEntryRecord(Base):
    __tablename__ = "credit_ledger_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "reservation_id"],
            ["credit_reservations.workspace_id", "credit_reservations.id"],
            name="fk_credit_ledger_workspace_reservation",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["jobs.workspace_id", "jobs.id"],
            name="fk_credit_ledger_workspace_job",
        ),
        Index(
            "uq_credit_ledger_settlement_reservation",
            "reservation_id",
            unique=True,
            postgresql_where=text(
                "entry_type = 'settle' AND reservation_id IS NOT NULL"
            ),
            sqlite_where=text("entry_type = 'settle' AND reservation_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(IDENTITY_TYPE, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reservation_id: Mapped[str | None] = mapped_column(
        ForeignKey("credit_reservations.id", ondelete="SET NULL")
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    entry_type: Mapped[str] = mapped_column(String(24), nullable=False)
    delta_balance_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delta_reserved_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_after_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(IDENTITY_TYPE, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(40))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(
        json_type(), default=dict, server_default=text("'{}'"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

class AnnouncementRecord(TimestampMixin, Base):
    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_announcements_status",
        ),
        CheckConstraint(
            "kind IN ('info', 'success', 'warning', 'maintenance')",
            name="ck_announcements_kind",
        ),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at",
            name="ck_announcements_valid_window",
        ),
        Index(
            "ix_announcements_public_order",
            "status",
            "is_pinned",
            "published_at",
        ),
        Index("ix_announcements_schedule", "status", "starts_at", "ends_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(320))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    link_url: Mapped[str | None] = mapped_column(String(2048))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
