"""固定形象 persona：一个形象 + 一个声音的可复用搭配（契约 C3）。

形象与声音只保存 id（不建外键），被删除或失效时 persona 仍可读取、标为不可用。
"""

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import TimestampMixin, json_type


class VideoPersonaRecord(TimestampMixin, Base):
    __tablename__ = "video_personas"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_persona_request",
        ),
        UniqueConstraint(
            "workspace_id", "owner_user_id", "name", name="uq_video_persona_name"
        ),
        Index("ix_video_persona_scope", "workspace_id", "owner_user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(30))
    avatar_id: Mapped[str] = mapped_column(String(80))
    voice_id: Mapped[str] = mapped_column(String(80))
    # 创建时的名称快照：依赖对象被删除后仍能告诉用户原来搭配的是什么。
    avatar_name: Mapped[str] = mapped_column(String(120))
    voice_name: Mapped[str] = mapped_column(String(120))
    # 声音参数（emotion / language），与口播草稿字段同名。
    voice_settings: Mapped[dict] = mapped_column(json_type(), default=dict)
