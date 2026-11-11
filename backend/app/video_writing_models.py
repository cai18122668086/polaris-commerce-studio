"""Immutable writing objects; an adoption links a draft to existing version history."""

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
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
