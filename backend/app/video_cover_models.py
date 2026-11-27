"""Cover candidates for finished short videos (成片步骤, W5)."""

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type


class VideoCoverCandidateRecord(TimestampMixin, Base):
    """One 3:4 cover: a real-frame or AI background plus the exact typeset title.

    A generate request creates two rows (``slot`` 0 = real frame, free;
    ``slot`` 1 = AI background, priced ``cover_generate``). A re-text creates
    one free row that reuses its ``parent_id``'s background.
    """

    __tablename__ = "video_cover_candidates"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "owner_user_id", "request_id", "slot",
            name="uq_video_cover_request_slot",
        ),
        Index("ix_video_cover_item", "workspace_id", "owner_user_id", "work_item_id", "created_at"),
        Index("ix_video_cover_source", "workspace_id", "owner_user_id", "source_kind", "source_id"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    slot: Mapped[int] = mapped_column(Integer, default=0)
    work_item_id: Mapped[str | None] = mapped_column(String(40))
    source_kind: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[str] = mapped_column(String(40))
    platform: Mapped[str] = mapped_column(String(16))
    cover_text: Mapped[str] = mapped_column(Text)
    highlight: Mapped[str | None] = mapped_column(Text)
    background: Mapped[str] = mapped_column(String(8))
    layout: Mapped[str | None] = mapped_column(String(16))
    round: Mapped[int] = mapped_column(Integer, default=0)
    parent_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error_code: Mapped[str | None] = mapped_column(String(80))
    params: Mapped[dict] = mapped_column(json_type(), default=dict)
    checks: Mapped[dict] = mapped_column(json_type(), default=dict)
    files: Mapped[dict] = mapped_column(json_type(), default=dict)
    receipt: Mapped[dict] = mapped_column(json_type(), default=dict)
