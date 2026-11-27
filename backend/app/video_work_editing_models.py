"""Editing runs of work items (W3): one row per item that entered batch editing.

The row freezes what the user chose for the item (template, music, supplement)
and where its pipeline is: recognition -> check -> paid planning -> render ->
export. Every task it creates has a request id derived from the item, attempt
and step, so a lost response, a reload or an API restart never creates (or
charges for) a second task.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type

EDITING_PHASES = (
    "queued",
    "transcribing",
    "preparing",
    "planning",
    "rendering",
    "done",
    "failed",
)
ACTIVE_PHASES = ("transcribing", "preparing", "planning", "rendering")


class VideoWorkEditingRunRecord(TimestampMixin, Base):
    __tablename__ = "video_work_editing_runs"
    __table_args__ = (
        Index(
            "ix_video_work_editing_runs_owner_phase",
            "owner_user_id",
            "phase",
            "created_at",
        ),
        Index("ix_video_work_editing_runs_phase", "phase", "created_at"),
        CheckConstraint(
            "phase IN (" + ", ".join(f"'{value}'" for value in EDITING_PHASES) + ")",
            name="ck_video_work_editing_run_phase",
        ),
        CheckConstraint("attempt >= 1", name="ck_video_work_editing_run_attempt"),
    )
    item_id: Mapped[str] = mapped_column(
        ForeignKey("video_work_items.id", ondelete="RESTRICT"), primary_key=True
    )
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("video_work_batches.id", ondelete="RESTRICT"), index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(40))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    template_id: Mapped[str] = mapped_column(String(64))
    # {"music": ..., "material_ids": [...], "supplement": {...} | None}
    options: Mapped[dict] = mapped_column(json_type(), default=dict)
    phase: Mapped[str] = mapped_column(String(16), default="queued")
    transcript_task_id: Mapped[str | None] = mapped_column(String(40))
    prepare_task_id: Mapped[str | None] = mapped_column(String(40))
    generate_task_id: Mapped[str | None] = mapped_column(String(40))
    render_task_id: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str | None] = mapped_column(Text)
