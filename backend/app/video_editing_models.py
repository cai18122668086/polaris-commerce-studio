from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type


class VideoEditingHandoffRecord(TimestampMixin, Base):
    __tablename__ = "video_editing_handoffs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_editing_request",
        ),
        Index(
            "ix_video_editing_scope",
            "workspace_id",
            "owner_user_id",
            "generation_task_id",
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    generation_task_id: Mapped[str] = mapped_column(
        ForeignKey("video_generations.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(24), default="created")
    revision: Mapped[int] = mapped_column(default=0)
    events: Mapped[list] = mapped_column(json_type(), default=list)
    result_reference: Mapped[str | None] = mapped_column(String(1000))
