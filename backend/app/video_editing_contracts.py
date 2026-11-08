"""Versioned contracts: models refer to word IDs; only the compiler owns time."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from .video_studio_schemas import StrictVideoModel


class EditingOptions(StrictVideoModel):
    mode: Literal["subtitles"] = "subtitles"
    language: Literal["zh", "en", "auto"] = "zh"
    # Explicit website binding to a bundled font, independent of old episodes.
    caption_font_id: Literal["font-d1961be1161ea1be"] = "font-d1961be1161ea1be"
    source_subtitles: Literal["none", "present", "unknown"] = "unknown"


class EditingTaskCreate(StrictVideoModel):
    request_id: UUID
    generation_task_id: UUID | None = None
    source_id: UUID | None = None
    options: EditingOptions = Field(default_factory=EditingOptions)

    @model_validator(mode="after")
    def one_source(self) -> Self:
        if (self.generation_task_id is None) == (self.source_id is None):
            raise ValueError(
                "Choose exactly one existing generation or uploaded source"
            )
        return self


class TranscriptToken(StrictVideoModel):
    id: str
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def positive_range(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("Recognized word needs a positive measured interval")
        return self


class TranscriptUtterance(StrictVideoModel):
    id: str
    text: str
    token_ids: list[str]
    start_ms: int
    end_ms: int


class Transcript(StrictVideoModel):
    schema_version: Literal["tengli.transcript/1"] = "tengli.transcript/1"
    audio_sha256: str
    source_sha256: str
    duration_ms: int
    provider: str
    model: str
    model_sha256: str | None = None
    recognizer_version: str | None = None
    processing_version: str = "word-clock/1"
    raw_result_sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)
    timing_adjustments: list[dict] = Field(default_factory=list)
    language: str
    tokens: list[TranscriptToken]
    utterances: list[TranscriptUtterance]
    reference_text: str | None = None
    reference_matches: bool | None = None
    differences: list[dict] = Field(default_factory=list)
    timing_review: Literal["unreviewed", "reviewed"] = "unreviewed"


class EditingArtifactResponse(StrictVideoModel):
    id: str
    role: str
    mime: str
    sha256: str
    bytes: int
    duration_ms: int | None
    url: str


class EditingTaskResponse(StrictVideoModel):
    id: str
    project_id: str
    source_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    stage: str
    revision: int
    attempts: int
    error_code: str | None
    cancel_requested: bool
    created_at: datetime
    library_release: str
    options: EditingOptions
    review: dict[str, str]
    artifacts: list[EditingArtifactResponse]


class SemanticBeat(StrictVideoModel):
    """Reserved for phase 2: no seconds, code, paths or executable template."""

    id: str
    first_token_id: str
    last_token_id: str
    emphasis_token_ids: list[str] = Field(default_factory=list)
    relation: Literal[
        "explanation",
        "parallel",
        "contrast",
        "cause",
        "sequence",
        "summary",
        "condition",
        "negation",
        "transformation",
        "amount",
        "question",
        "call_to_action",
    ]
    group_id: str
    asset_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=1000)
    locked_by_user: bool = False


class SemanticPlan(StrictVideoModel):
    schema_version: Literal["tengli.semantic-plan/1"] = "tengli.semantic-plan/1"
    audience_question: str = Field(min_length=1, max_length=500)
    argument_outline: list[str] = Field(min_length=1, max_length=50)
    style_reason: str = Field(min_length=1, max_length=1000)
    beats: list[SemanticBeat] = Field(min_length=1, max_length=60)
    missing_materials: list[str] = Field(default_factory=list, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=40)
