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


class EditingMaterialRecord(TimestampMixin, Base):
    __tablename__ = "video_editing_materials"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "owner_user_id",
            "request_id",
            name="uq_editing_material_request",
        ),
        Index(
            "ix_editing_material_project",
            "project_id",
            "workspace_id",
            "owner_user_id",
            "created_at",
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    request_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(16))
    mime: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column()
    label: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(400))
    width: Mapped[int] = mapped_column()
    height: Mapped[int] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column()
    source_job_id: Mapped[str | None] = mapped_column(String(40))
    source_asset_id: Mapped[str | None] = mapped_column(String(40))


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


class EditingTranscriptRevisionRecord(TimestampMixin, Base):
    __tablename__ = "video_editing_transcript_revisions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_editing_transcript_request",
        ),
        Index("ix_video_editing_transcript_source", "source_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("video_editing_sources.id"))
    base_task_id: Mapped[str] = mapped_column(ForeignKey("video_editing_tasks.id"))
    base_transcript_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("video_editing_artifacts.id")
    )
    base_transcript_sha256: Mapped[str] = mapped_column(String(64))
    parent_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_editing_transcript_revisions.id")
    )
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    corrected_text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))
    text_status: Mapped[str] = mapped_column(String(24))
    details: Mapped[dict] = mapped_column(json_type(), default=dict)


class EditingLibraryNoteRecord(TimestampMixin, Base):
    __tablename__ = "video_editing_library_notes"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_editing_library_note_request",
        ),
        UniqueConstraint(
            "project_id",
            "owner_user_id",
            "library_release",
            "target_kind",
            "target_id",
            "sequence",
            name="uq_editing_library_note_sequence",
        ),
        Index(
            "ix_editing_library_note_project",
            "workspace_id",
            "owner_user_id",
            "project_id",
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    library_release: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    target_kind: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[str] = mapped_column(String(160))
    sequence: Mapped[int] = mapped_column()
    choice: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    parent_note_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_editing_library_notes.id")
    )
    details: Mapped[dict] = mapped_column(json_type(), default=dict)


class EditingNativePlanRecord(TimestampMixin, Base):
    __tablename__ = "video_editing_native_plans"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_editing_native_plan_request",
        ),
        Index(
            "ix_editing_native_plan_project",
            "workspace_id",
            "owner_user_id",
            "project_id",
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("video_editing_sources.id"))
    base_task_id: Mapped[str] = mapped_column(ForeignKey("video_editing_tasks.id"))
    base_transcript_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("video_editing_artifacts.id")
    )
    base_transcript_sha256: Mapped[str] = mapped_column(String(64))
    library_release: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(24))
    semantic: Mapped[dict] = mapped_column(json_type())
    semantic_sha256: Mapped[str] = mapped_column(String(64))
    recipes: Mapped[dict] = mapped_column(json_type())
    recipes_sha256: Mapped[str] = mapped_column(String(64))
    choice_snapshot: Mapped[dict] = mapped_column(json_type())
    details: Mapped[dict] = mapped_column(json_type(), default=dict)


class EditingPlanningTaskRecord(TimestampMixin, Base):
    __tablename__ = "video_editing_planning_tasks"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_editing_planning_request",
        ),
        UniqueConstraint("prepared_task_id", name="uq_editing_prepared_execution"),
        Index("ix_editing_planning_queue", "status", "lease_until"),
        Index(
            "ix_editing_planning_project", "workspace_id", "owner_user_id", "project_id"
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("video_editing_sources.id"))
    base_task_id: Mapped[str] = mapped_column(ForeignKey("video_editing_tasks.id"))
    base_transcript_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("video_editing_artifacts.id")
    )
    base_transcript_sha256: Mapped[str] = mapped_column(String(64))
    prepared_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_editing_planning_tasks.id")
    )
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    library_release: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    revision: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=0)
    owner_token: Mapped[str | None] = mapped_column(String(40))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    snapshot: Mapped[dict] = mapped_column(json_type(), default=dict)
    checkpoint: Mapped[dict] = mapped_column(json_type(), default=dict)
    result: Mapped[dict] = mapped_column(json_type(), default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))


class EditingPlanningAttemptRecord(Base):
    __tablename__ = "video_editing_planning_attempts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("video_editing_planning_tasks.id"), index=True
    )
    number: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
