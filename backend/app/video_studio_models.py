"""Owned video projects and append-only script/task history."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type, utc_now


class VideoProjectRecord(TimestampMixin, Base):
    __tablename__ = "video_projects"
    __table_args__ = (
        Index("ix_video_projects_scope", "workspace_id", "owner_user_id", "updated_at"),
        CheckConstraint("revision >= 1", name="ck_video_project_revision"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(json_type(), nullable=False)
    writing_origin: Mapped[dict | None] = mapped_column(json_type(), nullable=True)


class VideoScriptVersionRecord(Base):
    __tablename__ = "video_script_versions"
    __table_args__ = (
        Index("ix_video_versions_project", "project_id", "created_at"),
        CheckConstraint(
            "kind IN ('draft', 'library', 'confirmed')", name="ck_video_version_kind"
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot: Mapped[dict] = mapped_column(json_type(), nullable=False)
    writing_origin: Mapped[dict | None] = mapped_column(json_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class VideoTaskRecord(Base):
    __tablename__ = "video_tasks"
    __table_args__ = (
        CheckConstraint("status = 'demo'", name="ck_video_task_demo_only"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id", ondelete="RESTRICT"), index=True
    )
    confirmed_version_id: Mapped[str] = mapped_column(
        ForeignKey("video_script_versions.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="demo")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class VideoMutationRecord(Base):
    __tablename__ = "video_mutations"
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), primary_key=True
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
