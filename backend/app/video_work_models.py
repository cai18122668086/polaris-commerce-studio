"""Work batches and work items: one item is one video headed for publishing.

Contract C2 of the video v3 pipeline. Talking (W2) creates the batch and its
items; editing (W3) and finishing (W5) write their own columns later. Cross-line
references are plain ids validated by the routes so every line can migrate on
its own.
"""

from sqlalchemy import (
    CheckConstraint,
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

BATCH_SOURCES = ("talking", "editing_upload")
DRIVE_MODES = ("text", "audio", "uploaded_video")
STAGES = ("talking", "editing", "finishing", "done")
STATUSES = ("pending", "queued", "running", "succeeded", "failed", "canceled")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


class VideoWorkBatchRecord(TimestampMixin, Base):
    __tablename__ = "video_work_batches"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_work_batch_request",
        ),
        Index(
            "ix_video_work_batches_scope", "workspace_id", "owner_user_id", "created_at"
        ),
        CheckConstraint(
            _in("source", BATCH_SOURCES), name="ck_video_work_batch_source"
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    source: Mapped[str] = mapped_column(String(24))
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))


class VideoWorkItemRecord(TimestampMixin, Base):
    __tablename__ = "video_work_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "position", name="uq_video_work_item_position"),
        Index(
            "ix_video_work_items_scope",
            "workspace_id",
            "owner_user_id",
            "stage",
            "created_at",
        ),
        CheckConstraint(
            _in("drive_mode", DRIVE_MODES), name="ck_video_work_item_drive"
        ),
        CheckConstraint(_in("stage", STAGES), name="ck_video_work_item_stage"),
        CheckConstraint(_in("status", STATUSES), name="ck_video_work_item_status"),
        CheckConstraint("version >= 1", name="ck_video_work_item_version"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("video_work_batches.id", ondelete="RESTRICT"), index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    position: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    script_document_id: Mapped[str | None] = mapped_column(String(40))
    publish_title: Mapped[str] = mapped_column(Text, default="")
    publish_body: Mapped[str] = mapped_column(Text, default="")
    script_text: Mapped[str] = mapped_column(Text, default="")
    persona_id: Mapped[str | None] = mapped_column(String(80))
    avatar_id: Mapped[str | None] = mapped_column(String(80))
    voice_id: Mapped[str | None] = mapped_column(String(80))
    drive_mode: Mapped[str] = mapped_column(String(24))
    audio_file_id: Mapped[str | None] = mapped_column(String(40))
    generation_task_id: Mapped[str | None] = mapped_column(String(40), index=True)
    source_video_ref: Mapped[dict | None] = mapped_column(json_type())
    editing_task_id: Mapped[str | None] = mapped_column(String(40), index=True)
    cover_asset_id: Mapped[str | None] = mapped_column(String(80))
    stage: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    # Earlier task ids replaced by a retry, oldest first: {"generation": [...]}.
    history: Mapped[dict] = mapped_column(json_type(), default=dict)
