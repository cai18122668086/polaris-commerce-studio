"""Editing has its own ownership, attempts and artifacts; handoff v1 is unchanged."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type


class EditingSourceRecord(TimestampMixin, Base):
    __tablename__ = "video_editing_sources"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    confirmed_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_script_versions.id")
    )
    generation_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_generations.id")
    )
    kind: Mapped[str] = mapped_column(String(24))
    media_path: Mapped[str] = mapped_column(Text)
    media_sha256: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(json_type(), default=dict)


class EditingTaskRecord(TimestampMixin, Base):
    __tablename__ = "video_editing_tasks"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_editing_task_request",
        ),
        Index("ix_video_editing_task_queue", "status", "lease_until"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("video_editing_sources.id"))
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    library_release: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    revision: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=0)
    owner_token: Mapped[str | None] = mapped_column(String(40))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    options: Mapped[dict] = mapped_column(json_type(), default=dict)
    checkpoint: Mapped[dict] = mapped_column(json_type(), default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))


class EditingAttemptRecord(Base):
    __tablename__ = "video_editing_attempts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("video_editing_tasks.id"), index=True
    )
    number: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))


class EditingArtifactRecord(TimestampMixin, Base):
    __tablename__ = "video_editing_artifacts"
    __table_args__ = (
        UniqueConstraint("task_id", "role", name="uq_video_editing_artifact_role"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("video_editing_tasks.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(24))
    path: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column()
    validation: Mapped[dict] = mapped_column(json_type(), default=dict)
