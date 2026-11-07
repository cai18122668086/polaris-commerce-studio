from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type


class VideoAvatarRecord(TimestampMixin, Base):
    __tablename__ = "video_avatars"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(120))
    gender: Mapped[str] = mapped_column(String(12), default="未知")
    cover_path: Mapped[str | None] = mapped_column(Text)
    video_url: Mapped[str | None] = mapped_column(Text)
    provider_model_id: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(default=True)


class VideoGenerationRecord(TimestampMixin, Base):
    __tablename__ = "video_generations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_generation_request",
        ),
        Index(
            "ix_video_generation_scope", "workspace_id", "owner_user_id", "created_at"
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_projects.id", ondelete="RESTRICT")
    )
    confirmed_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_script_versions.id", ondelete="RESTRICT")
    )
    avatar_id: Mapped[str] = mapped_column(
        ForeignKey("video_avatars.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    provider_task_id: Mapped[str | None] = mapped_column(String(160))
    details: Mapped[dict] = mapped_column(json_type(), default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))


class VideoAudioRecord(TimestampMixin, Base):
    __tablename__ = "video_audio_files"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(80))


class VideoLipsyncAvatarRecord(TimestampMixin, Base):
    """One durable backup registration per owner and exact prepared model."""

    __tablename__ = "video_lipsync_avatars"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "model_id",
            name="uq_video_lipsync_avatar_model",
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    model_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(24))
    provider_task_id: Mapped[str | None] = mapped_column(String(160))
    avatar_code: Mapped[str | None] = mapped_column(String(160))
    error_code: Mapped[str | None] = mapped_column(String(80))
