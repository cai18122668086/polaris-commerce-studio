"""AI 润色候选：定制形象前，用参考图编辑把用户照片润色成数字人可用的形象照。

一张候选一行，各自冻结 / 结算积分（7 积分 / 张，失败不扣）。
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


class VideoAvatarPolishRecord(TimestampMixin, Base):
    __tablename__ = "video_avatar_polishes"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            "slot",
            name="uq_video_avatar_polish_slot",
        ),
        Index(
            "ix_video_avatar_polish_scope",
            "workspace_id",
            "owner_user_id",
            "created_at",
        ),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    slot: Mapped[int] = mapped_column(Integer)
    # queued | running | ready | failed
    status: Mapped[str] = mapped_column(String(16), default="queued")
    description: Mapped[str] = mapped_column(String(200))
    source_path: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    result_path: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))
    consent_version: Mapped[str] = mapped_column(String(40))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 规格检查结果与内部回执（模型、耗时、提示词摘要），不返回给商家
    checks: Mapped[dict] = mapped_column(json_type(), default=dict)
    receipt: Mapped[dict] = mapped_column(json_type(), default=dict)
