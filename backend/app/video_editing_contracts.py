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
    transcript_revision_id: UUID | None = None


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
    parent_transcript_sha256: str | None = None
    text_revision_id: str | None = None
    text_status: Literal["automatic", "user_corrected", "operator_candidate"] = (
        "automatic"
    )

    @model_validator(mode="after")
    def stable_measured_ids(self) -> Self:
        ids = {token.id: i for i, token in enumerate(self.tokens)}
        if len(ids) != len(self.tokens):
            raise ValueError("Each recorded token occurrence needs a unique ID")
        if any(t.end_ms > self.duration_ms for t in self.tokens):
            raise ValueError("Word clock exceeds the actual source duration")
        if any(
            a.start_ms > b.start_ms
            for a, b in zip(self.tokens, self.tokens[1:], strict=False)
        ):
            raise ValueError("Recorded tokens must remain in source order")
        utterance_ids = set()
        for utterance in self.utterances:
            if utterance.id in utterance_ids or not utterance.token_ids:
                raise ValueError("Utterance IDs/ranges must be unique and nonempty")
            utterance_ids.add(utterance.id)
            if any(t not in ids for t in utterance.token_ids):
                raise ValueError("Utterance references an unknown recorded token")
            positions = [ids[t] for t in utterance.token_ids]
            if positions != list(range(positions[0], positions[-1] + 1)):
                raise ValueError("Utterance must cover consecutive source occurrences")
            if (
                utterance.start_ms != self.tokens[positions[0]].start_ms
                or utterance.end_ms != self.tokens[positions[-1]].end_ms
            ):
                raise ValueError("Utterance bounds must come from measured words")
        return self


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


class EditingTranscriptRevisionCreate(StrictVideoModel):
    request_id: UUID
    base_transcript_artifact_id: UUID
    parent_revision_id: UUID | None = None
    corrected_text: str = Field(min_length=1, max_length=20000)
    text_status: Literal["operator_candidate", "user_corrected"] = "operator_candidate"
    attests_spoken_text: bool = False

    @model_validator(mode="after")
    def explicit_review(self) -> Self:
        if not self.corrected_text.strip():
            raise ValueError("Correction must contain recorded speech")
        if self.attests_spoken_text != (self.text_status == "user_corrected"):
            raise ValueError(
                "User-corrected status requires explicit spoken-text review"
            )
        return self


class EditingTranscriptRevisionResponse(StrictVideoModel):
    id: str
    source_id: str
    base_task_id: str
    base_transcript_artifact_id: str
    base_transcript_sha256: str
    parent_revision_id: str | None
    corrected_text: str
    text_sha256: str
    text_status: Literal["operator_candidate", "user_corrected"]
    timing_review: Literal["unreviewed"] = "unreviewed"
    changes: list[dict]
    created_at: datetime


class EditingLibraryNoteCreate(StrictVideoModel):
    request_id: UUID
    target_kind: Literal["group", "bundled_asset", "external_resource"]
    target_id: str = Field(min_length=1, max_length=160)
    choice: Literal["consider", "avoid", "clear"]
    reason: str = Field(min_length=1, max_length=1000)
    parent_note_id: UUID | None = None

    @model_validator(mode="after")
    def meaningful_reason(self) -> Self:
        if not self.reason.strip():
            raise ValueError("Record the current project selection reason")
        return self


class EditingLibraryNoteResponse(StrictVideoModel):
    id: str
    project_id: str
    library_release: str
    target_kind: Literal["group", "bundled_asset", "external_resource"]
    target_id: str
    target_name: str
    choice: Literal["consider", "avoid", "clear"]
    reason: str
    sequence: int
    parent_note_id: str | None
    created_at: datetime
    scope: Literal["project_selection_memo"] = "project_selection_memo"


class EditingLibraryNotesResponse(StrictVideoModel):
    items: list[EditingLibraryNoteResponse]
    total: int
    next_offset: int | None


class LibraryChoice(StrictVideoModel):
    note_id: str
    target_kind: Literal["group", "bundled_asset", "external_resource"]
    target_id: str
    target_name: str
    sequence: int = Field(ge=1)
    choice: Literal["consider", "avoid", "clear"]
    reason: str = Field(min_length=1, max_length=1000)


class LibraryChoiceSnapshot(StrictVideoModel):
    schema_version: Literal["tengli.library-choice-snapshot/1"] = (
        "tengli.library-choice-snapshot/1"
    )
    scope: Literal["project_selection_memo"] = "project_selection_memo"
    project_id: UUID
    library_release: str
    notes: list[LibraryChoice] = Field(max_length=1028)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")


class NativeTextAnchor(StrictVideoModel):
    path: str = Field(min_length=1, max_length=200)
    first_token_id: str
    last_token_id: str
    punctuation: Literal["preserve", "omit_sentence_punctuation"] = "preserve"


class NativeEventAnchor(StrictVideoModel):
    path: str = Field(min_length=1, max_length=200)
    token_id: str
    edge: Literal["start", "end"]


class NativeMediaAnchor(StrictVideoModel):
    path: str = Field(min_length=1, max_length=200)
    asset_id: str = Field(min_length=1, max_length=100)


class SemanticBeat(StrictVideoModel):
    """No time values, file paths or executable template; allowlisted pointers only."""

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
    locked_by_user: Literal[False] = False
    native_text: list[NativeTextAnchor] = Field(default_factory=list, max_length=50)
    native_events: list[NativeEventAnchor] = Field(default_factory=list, max_length=80)
    native_media: list[NativeMediaAnchor] = Field(default_factory=list, max_length=30)


class SemanticPlan(StrictVideoModel):
    schema_version: Literal["tengli.semantic-plan/1"] = "tengli.semantic-plan/1"
    audience_question: str = Field(min_length=1, max_length=500)
    argument_outline: list[str] = Field(min_length=1, max_length=50)
    style_reason: str = Field(min_length=1, max_length=1000)
    beats: list[SemanticBeat] = Field(min_length=1, max_length=60)
    missing_materials: list[str] = Field(default_factory=list, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=40)
