from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictVideoModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator("created_at", "updated_at", mode="before", check_fields=False)
    @classmethod
    def utc_timestamp(cls, value: Any) -> Any:
        # SQLite drops tzinfo; these timestamps are always written in UTC.
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class VideoDraft(StrictVideoModel):
    name: str = Field(default="未命名视频", max_length=80)
    text: str = Field(default="", max_length=3000)
    avatarId: str = Field(default="female-020", max_length=80)
    voiceId: str = Field(default="", max_length=80)
    speed: float = Field(default=1, ge=0.5, le=1.5)
    emotion: Literal[
        "自然", "愉快", "温柔", "专业", "平静", "悲伤", "愤怒", "害怕", "厌恶", "惊讶"
    ] = "自然"
    language: str = Field(default="auto", max_length=40)
    quality: Literal["720P", "1080P"] = "1080P"
    drive: Literal["text", "audio"] = "text"
    audioAssetId: UUID | None = None


class VideoReference(StrictVideoModel):
    id: UUID
    kind: Literal["text", "url"]
    url: str = Field(default="", max_length=2048)
    original_text: str = Field(default="", max_length=6000)
    note: str = Field(default="", max_length=1000)

    @field_validator("url")
    @classmethod
    def safe_reference_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        if value:
            parts = urlsplit(value)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username
                or parts.password
            ):
                raise ValueError("Reference must be an http(s) URL without credentials")
        return value


class VideoMediaAssociation(StrictVideoModel):
    id: UUID
    kind: Literal["audio", "avatar_sample", "voice_sample"]
    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(max_length=120)
    size_bytes: int = Field(ge=0, le=100 * 1024 * 1024)
    # No blob URL, storage key or arbitrary remote asset can be injected here.
    availability: Literal["local_only"] = "local_only"


class VideoProjectContent(StrictVideoModel):
    draft: VideoDraft = Field(default_factory=VideoDraft)
    product_facts: str = Field(default="", max_length=6000)
    references: list[VideoReference] = Field(default_factory=list, max_length=50)
    media: list[VideoMediaAssociation] = Field(default_factory=list, max_length=50)


class VideoProjectWrite(StrictVideoModel):
    request_id: UUID
    expected_revision: int = Field(ge=0)
    content: VideoProjectContent
    action: Literal["save", "library", "demo"] = "save"
    restore_version_id: UUID | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class VideoWritingOrigin(StrictVideoModel):
    adoption_id: UUID
    draft_document_id: UUID
    reference_document_id: UUID
    analysis_document_id: UUID
    facts_document_id: UUID
    draft_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rules_release: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class VideoProjectResponse(StrictVideoModel):
    id: str
    workspace_id: str
    revision: int
    content: VideoProjectContent
    created_at: datetime
    updated_at: datetime
    writing_origin: VideoWritingOrigin | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class VideoVersionResponse(StrictVideoModel):
    id: str
    project_id: str
    kind: Literal["draft", "library", "confirmed"]
    snapshot: VideoProjectContent
    created_at: datetime
    writing_origin: VideoWritingOrigin | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class VideoTaskResponse(StrictVideoModel):
    id: str
    project_id: str
    confirmed_version_id: str
    status: Literal["demo"]
    snapshot: VideoProjectContent
    created_at: datetime


class VideoWriteResponse(StrictVideoModel):
    project: VideoProjectResponse
    version: VideoVersionResponse | None = None
    task: VideoTaskResponse | None = None


class VideoLegacyCopy(StrictVideoModel):
    id: str = Field(max_length=100)
    title: str = Field(max_length=80)
    text: str = Field(max_length=3000)
    date: str = Field(max_length=80)


class VideoLegacyWork(StrictVideoModel):
    id: str = Field(max_length=100)
    draft: VideoDraft
    date: str = Field(max_length=80)


class VideoLegacyImport(StrictVideoModel):
    request_id: UUID
    draft: VideoDraft
    copies: list[VideoLegacyCopy] = Field(default_factory=list, max_length=50)
    works: list[VideoLegacyWork] = Field(default_factory=list, max_length=30)
