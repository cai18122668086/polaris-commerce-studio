"""Immutable writing objects; an adoption links a draft to existing version history.

The script library (文案库) is the one mutable object here: each entry is what
the user will publish (title + body) and what the avatar will say (script).
Edits keep the same entry and bump ``revision``; earlier revisions stay in
``history``.
"""

from datetime import datetime

from sqlalchemy import (
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


class VideoWritingDocument(TimestampMixin, Base):
    __tablename__ = "video_writing_documents"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_writing_document_request",
        ),
        Index(
            "ix_video_writing_scope",
            "workspace_id",
            "owner_user_id",
            "project_id",
            "created_at",
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    kind: Mapped[str] = mapped_column(String(16))
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[dict] = mapped_column(json_type())
    body_sha256: Mapped[str] = mapped_column(String(64))
    rules_release: Mapped[str] = mapped_column(String(64))
    reference_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_writing_documents.id")
    )
    analysis_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_writing_documents.id")
    )
    facts_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_writing_documents.id")
    )
    assistance_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_assistance_tasks.id")
    )


class VideoWritingAdoption(TimestampMixin, Base):
    __tablename__ = "video_writing_adoptions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "request_id", name="uq_video_writing_adoption_request"
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("video_writing_documents.id"))
    script_version_id: Mapped[str] = mapped_column(
        ForeignKey("video_script_versions.id")
    )
    request_id: Mapped[str] = mapped_column(String(40))


class VideoScriptLibraryEntry(TimestampMixin, Base):
    __tablename__ = "video_script_library"
    __table_args__ = (
        # Idempotent ingestion: one entry per (run, version) or manual request.
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "dedupe_key",
            name="uq_video_script_library_dedupe",
        ),
        # A saved draft document is at most one entry, whichever path saved it.
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "writing_document_id",
            name="uq_video_script_library_document",
        ),
        UniqueConstraint("legacy_version_id", name="uq_video_script_library_legacy"),
        Index(
            "ix_video_script_library_scope",
            "workspace_id",
            "owner_user_id",
            "created_at",
        ),
        Index("ix_video_script_library_run", "workspace_id", "owner_user_id", "run_id"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(16))
    platform: Mapped[str] = mapped_column(String(16), default="")
    publish_title: Mapped[str] = mapped_column(String(80), default="")
    publish_body: Mapped[str] = mapped_column(Text, default="")
    script: Mapped[str] = mapped_column(Text)
    benchmark_refs: Mapped[list] = mapped_column(json_type(), default=list)
    dedupe_key: Mapped[str | None] = mapped_column(String(160))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("video_projects.id"))
    writing_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_writing_documents.id")
    )
    legacy_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_script_versions.id")
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    history: Mapped[list] = mapped_column(json_type(), default=list)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 第三轮：来自哪次爆款文案 run、哪个角度（展示与按批次分组用，可空）。
    run_id: Mapped[str | None] = mapped_column(String(40))
    angle: Mapped[dict | None] = mapped_column(json_type())
