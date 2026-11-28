from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type


class VideoAssistanceRecord(TimestampMixin, Base):
    __tablename__ = "video_assistance_tasks"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_assistance_request",
        ),
        Index(
            "ix_video_assistance_scope",
            "workspace_id",
            "owner_user_id",
            "project_id",
            "created_at",
        ),
        Index("ix_video_assistance_kind_status", "kind", "status"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    provider_task_id: Mapped[str | None] = mapped_column(String(160))
    inputs: Mapped[dict] = mapped_column(json_type())
    result: Mapped[dict] = mapped_column(json_type(), default=dict)
    receipt: Mapped[dict] = mapped_column(json_type(), default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    # 第三轮 F 线：爆款文案 run 的执行租约（其他 kind 为空）。
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
