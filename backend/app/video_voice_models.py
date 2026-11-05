"""Private, account-owned cloned voices and single-submit preview receipts."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type


class VideoClonedVoiceRecord(TimestampMixin, Base):
    __tablename__ = "video_cloned_voices"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "owner_user_id", "request_id", name="uq_video_clone_request"
        ),
        UniqueConstraint("prefix", name="uq_video_clone_prefix"),
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "sample_sha256",
            name="uq_video_clone_sample",
        ),
        Index("ix_video_clone_scope", "workspace_id", "owner_user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(30))
    prefix: Mapped[str] = mapped_column(String(10))
    model: Mapped[str] = mapped_column(String(80))
    provider_workspace: Mapped[str] = mapped_column(String(120))
    provider_voice_id: Mapped[str | None] = mapped_column(String(240))
    sample_path: Mapped[str] = mapped_column(Text)
    sample_sha256: Mapped[str] = mapped_column(String(64))
    consent_version: Mapped[str] = mapped_column(String(40))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    preview_status: Mapped[str] = mapped_column(String(24), default="not_created")
    error_code: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(json_type(), default=dict)
