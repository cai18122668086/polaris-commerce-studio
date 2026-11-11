"""Versioned contracts: models refer to word IDs; only the compiler owns time."""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .video_studio_schemas import StrictVideoModel, VideoWritingOrigin


class NativeHighlightEdit(StrictVideoModel):
    beat_id: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=2, max_length=160)
    first_token_id: str = Field(min_length=1, max_length=120)
    last_token_id: str = Field(min_length=1, max_length=120)


class EditingHighlightChoice(StrictVideoModel):
    first_token_id: str
    last_token_id: str
    text: str
    start_ms: int


class EditingHighlightTarget(StrictVideoModel):
    beat_id: str
    path: str
    label: str
    current_text: str
    options: list[EditingHighlightChoice]


class NativeImageEdit(StrictVideoModel):
    beat_id: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=2, max_length=160)
    material_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EditingImageTarget(StrictVideoModel):
    beat_id: str
    path: str
    label: str
    current_material_id: UUID
    requires_transparency: bool


class NativeEffectEdit(StrictVideoModel):
    beat_id: str = Field(min_length=1, max_length=120)
    group_id: str = Field(min_length=1, max_length=40)


class EditingEffectChoice(StrictVideoModel):
    group_id: str
    name: str


class EditingEffectTarget(StrictVideoModel):
    beat_id: str
    choices: list[EditingEffectChoice]


class EditingMusicChoice(StrictVideoModel):
    asset_id: str
    name: str
    duration_seconds: float


class EditingMusicOptions(StrictVideoModel):
    original: EditingMusicChoice
    choices: list[EditingMusicChoice]


class NativeRenderEdits(StrictVideoModel):
    music: Literal["lower", "off"] | None = None
    music_track_id: str | None = Field(
        default=None,
        pattern=r"^bgm-[0-9a-f]{16}$",
        exclude_if=lambda value: value is None,
    )
    source_only_beat_ids: list[Annotated[str, Field(min_length=1, max_length=120)]] = (
        Field(default_factory=list, max_length=120)
    )

    highlight_edits: list[NativeHighlightEdit] = Field(
        default_factory=list, max_length=120, exclude_if=lambda value: not value
    )

    image_edits: list[NativeImageEdit] = Field(
        default_factory=list, max_length=120, exclude_if=lambda value: not value
    )
    effect_edits: list[NativeEffectEdit] = Field(
        default_factory=list, max_length=120, exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def checked_selection(self) -> Self:
        if (
            not self.music
            and not self.music_track_id
            and not self.source_only_beat_ids
            and not self.highlight_edits
            and not self.image_edits
            and not self.effect_edits
        ):
            raise ValueError("Select a music, segment, effect, highlight or image edit")
        if self.music == "off" and self.music_track_id:
            raise ValueError("A replacement track requires background music to be on")
        if len(set(self.source_only_beat_ids)) != len(self.source_only_beat_ids):
            raise ValueError("Select each segment at most once")
        keys = {(edit.beat_id, edit.path) for edit in self.highlight_edits}
        if len(keys) != len(self.highlight_edits) or any(
            beat_id in self.source_only_beat_ids for beat_id, _ in keys
        ):
            raise ValueError("Select each highlight once on an active segment")
        image_keys = {(edit.beat_id, edit.path) for edit in self.image_edits}
        if len(image_keys) != len(self.image_edits) or any(
            beat_id in self.source_only_beat_ids for beat_id, _ in image_keys
        ):
            raise ValueError("Select each image once on an active segment")
        effect_beats = {edit.beat_id for edit in self.effect_edits}
        if (
            len(effect_beats) != len(self.effect_edits)
            or effect_beats.intersection(self.source_only_beat_ids)
            or any(beat_id in effect_beats for beat_id, _ in image_keys)
        ):
            raise ValueError("Choose one replacement effect on an active text segment")
        self.source_only_beat_ids = sorted(self.source_only_beat_ids)
        self.highlight_edits.sort(key=lambda edit: (edit.beat_id, edit.path))
        self.image_edits.sort(key=lambda edit: (edit.beat_id, edit.path))
        self.effect_edits.sort(key=lambda edit: edit.beat_id)
        return self


class EditingExportConfirmation(StrictVideoModel):
    preview_artifact_id: UUID
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EditingPreviewBase(EditingExportConfirmation):
    task_id: UUID


class EditingCarriedRevision(StrictVideoModel):
    planning_task_id: UUID
    preview_base: EditingPreviewBase
    protected_beat_ids: list[str]


class EditingOptions(StrictVideoModel):
    mode: Literal["subtitles", "transcript", "native_plan"] = "subtitles"
    language: Literal["zh", "en", "auto"] = "zh"
    # Explicit website binding to a bundled font, independent of old episodes.
    caption_font_id: Literal["font-d1961be1161ea1be"] = "font-d1961be1161ea1be"
    source_subtitles: Literal["none", "present", "unknown"] = "unknown"
    transcript_revision_id: UUID | None = None
    native_plan_id: UUID | None = None
    native_edits: NativeRenderEdits | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    delivery: Literal["preview_first"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    preview_base: EditingPreviewBase | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def matching_plan_mode(self) -> Self:
        if (self.mode == "native_plan") != (self.native_plan_id is not None):
            raise ValueError("Native mode needs exactly one saved native plan")
        if self.native_plan_id and self.transcript_revision_id:
            raise ValueError("Saved native plans use their own frozen transcript")
        if self.native_edits and not self.native_plan_id:
            raise ValueError("User edits require a frozen native plan")
        if self.delivery and not self.native_plan_id:
            raise ValueError("Preview confirmation requires a frozen native plan")
        if self.preview_base and self.delivery != "preview_first":
            raise ValueError("An earlier preview can only start a new preview")
        return self


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


class EditingMotionCounts(StrictVideoModel):
    distinct_groups: int = Field(ge=0)
    occurrences: int = Field(ge=0)


class EditingArtifactResponse(StrictVideoModel):
    id: str
    role: str
    mime: str
    sha256: str
    bytes: int
    duration_ms: int | None
    url: str


class EditingWorkResponse(StrictVideoModel):
    task_id: str
    project_id: str
    project_title: str
    created_at: datetime
    mode: Literal["subtitles", "native_plan"]
    final: EditingArtifactResponse


class EditingWorksResponse(StrictVideoModel):
    items: list[EditingWorkResponse]
    next_before: str | None


class EditingTemplateSample(StrictVideoModel):
    template_id: str
    task_id: str
    motion_counts: EditingMotionCounts
    final: EditingArtifactResponse


class EditingSourceUploadResponse(StrictVideoModel):
    id: UUID
    project_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0)


class EditingSourceOrigin(StrictVideoModel):
    kind: Literal["upload_asset", "generation_task"]
    confirmed_version_id: str | None
    generation_task_id: str | None
    media_sha256: str
    script_sha256: str | None
    writing_origin: VideoWritingOrigin | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class EditingSourceFrame(StrictVideoModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    supports_native_portrait: bool


class EditingLayoutFinding(StrictVideoModel):
    shot_index: int = Field(ge=0)
    group_id: str
    beat_id: str | None = None
    first_ms: int = Field(ge=0)
    finding_count: int = Field(gt=0)


EditingReviewDecision = Literal["unreviewed", "accepted", "needs_changes"]


class EditingFilmAssessment(StrictVideoModel):
    semantic: EditingReviewDecision
    timing: EditingReviewDecision
    visual: EditingReviewDecision
    listening: EditingReviewDecision
    note: str = Field(max_length=1000)


class EditingFilmReview(StrictVideoModel):
    final_artifact_id: UUID
    final_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment: EditingFilmAssessment
    recorded_at: AwareDatetime


class EditingFilmReviewWrite(StrictVideoModel):
    final_artifact_id: UUID
    final_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment: EditingFilmAssessment
    expected_revision: int = Field(ge=0)


class EditingTaskResponse(StrictVideoModel):
    id: str
    project_id: str
    source_id: str
    status: Literal[
        "queued", "running", "awaiting_review", "completed", "failed", "cancelled"
    ]
    stage: str
    revision: int
    attempts: int
    error_code: str | None
    cancel_requested: bool
    created_at: datetime
    library_release: str
    options: EditingOptions
    review: dict[str, str]
    manual_review: EditingFilmReview | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    artifacts: list[EditingArtifactResponse]
    source_origin: EditingSourceOrigin | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    motion_counts: EditingMotionCounts | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    source_frame: EditingSourceFrame | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    layout_findings: list[EditingLayoutFinding] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    carried_revision: EditingCarriedRevision | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


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


class EditingNativeBeatResponse(StrictVideoModel):
    id: str
    group_id: str
    relation: str
    text: str
    reason: str
    source_only_available: bool
    dependency_blocker: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    question_gloss: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class EditingOverlaySlot(StrictVideoModel):
    group_id: str
    purpose: str
    layer: Literal["scene", "overlay"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    native_branch: Literal["question", "input-A", "input-B"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    binding: str | None = Field(default=None, exclude_if=lambda value: value is None)


class EditingOverlayTemplate(StrictVideoModel):
    id: str
    name: str
    slots: list[EditingOverlaySlot]


class EditingNativePlanResponse(StrictVideoModel):
    id: str
    project_id: str
    source_id: str
    base_task_id: str
    base_transcript_artifact_id: str
    library_release: str
    origin: Literal["operator_candidate", "tengli_gateway"]
    state: Literal["semantic_contract_validated"]
    audience_question: str
    beats: list[EditingNativeBeatResponse]
    warnings: list[str]
    missing_materials: list[str]
    text_status: str
    source_subtitles: Literal["none", "present"]
    caption_font_id: str
    choice_snapshot_sha256: str
    semantic_review: Literal["unreviewed"] = "unreviewed"
    render_available: bool = Field(
        description=(
            "Whether the plan can use the render workflow. Active beats with a "
            "dependency_blocker require adjustment or restored originals."
        )
    )
    continuous_preview_available: bool
    music_edit_available: bool
    highlight_edit_available: bool = False
    image_edit_available: bool = False
    overlay_template: EditingOverlayTemplate | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    created_at: datetime


class EditingPlanningTaskCreate(StrictVideoModel):
    request_id: UUID
    mode: Literal["prepare", "generate"] = "prepare"
    prepared_task_id: UUID | None = None
    auto_preview: bool = Field(default=False, exclude_if=lambda value: not value)
    material_ids: list[UUID] | None = Field(
        default=None, max_length=24, exclude_if=lambda value: value is None
    )
    template_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def prepared_execution(self) -> Self:
        if (self.mode == "generate") != (self.prepared_task_id is not None):
            raise ValueError("Model execution needs exactly one prepared request")
        if self.auto_preview and self.mode != "generate":
            raise ValueError("Automatic preview requires an explicit model submission")
        if self.template_id is not None and self.mode != "prepare":
            raise ValueError("Template is frozen when preparing the planning request")
        if self.material_ids is not None and (
            self.mode != "prepare"
            or len(set(self.material_ids)) != len(self.material_ids)
        ):
            raise ValueError("Only preparation accepts distinct project material IDs")
        return self


class EditingPlanningPreviewBatchCreate(StrictVideoModel):
    planning_task_ids: list[UUID] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def distinct_tasks(self) -> Self:
        if len(set(self.planning_task_ids)) != len(self.planning_task_ids):
            raise ValueError("Batch preview requires distinct planning tasks")
        return self


class EditingPlanningPreviewBatchItem(StrictVideoModel):
    planning_task_id: UUID
    task: EditingTaskResponse | None = None
    error_code: str | None = None
    error_message: str | None = None


class EditingPlanningSpan(StrictVideoModel):
    beat_id: str
    group_id: str
    text: str
    first_token_id: str
    last_token_id: str
    start_ms: int
    end_ms: int
    timing_review: Literal["unreviewed"] = "unreviewed"


class EditingImageResultImport(StrictVideoModel):
    request_id: UUID
    job_id: str = Field(min_length=1, max_length=40)
    asset_id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=400)


class EditingFeedbackObservation(StrictVideoModel):
    label: str = Field(min_length=1, max_length=16)
    likes: int = Field(ge=0, le=999_999_999, strict=True)
    source_ref: str = Field(min_length=1, max_length=400)
    observed_at: AwareDatetime
    attests_observation: Literal[True]

    @field_validator("label", "source_ref")
    @classmethod
    def one_line(cls, value: str) -> str:
        result = value.strip()
        if not result or not result.isprintable():
            raise ValueError("Evidence needs a label and a one-line source reference")
        return result

    @field_validator("observed_at", mode="before")
    @classmethod
    def explicit_time(cls, value: object) -> object:
        if isinstance(value, datetime) or isinstance(value, str) and "T" in value:
            return value
        raise ValueError("Evidence needs an ISO 8601 observation timestamp")

    @field_validator("attests_observation", mode="before")
    @classmethod
    def explicit_attestation(cls, value: object) -> bool:
        if value is not True:
            raise ValueError("The project owner must attest the observation")
        return True

    @field_validator("observed_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class EditingMaterialResponse(StrictVideoModel):
    id: str
    asset_id: str
    label: str
    description: str
    kind: Literal["image", "video"]
    mime: str
    sha256: str
    bytes: int
    width: int
    height: int
    duration_ms: int | None
    source_job_id: str | None
    source_asset_id: str | None
    feedback_observation: EditingFeedbackObservation | None = None
    url: str


class EditingMaterialsResponse(StrictVideoModel):
    items: list[EditingMaterialResponse]
    next_offset: int | None


class EditingFeedbackWordMatch(StrictVideoModel):
    first_token_id: str
    last_token_id: str


class EditingTemplateImageRequirement(StrictVideoModel):
    group_id: str
    required_distinct_images: int
    selected_distinct_images: int
    transparent_image_ids: list[str] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    native_image_slot_ids: dict[str, list[str]] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    feedback_word_matches: dict[str, list[EditingFeedbackWordMatch]] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    role_action_word_matches: dict[str, list[str]] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class EditingPlanningTaskResponse(StrictVideoModel):
    id: str
    project_id: str
    source_id: str
    base_task_id: str
    base_transcript_artifact_id: str
    base_transcript_sha256: str
    library_release: str
    choice_snapshot_sha256: str
    prepared_task_id: str | None
    mode: Literal["prepare", "generate"]
    model: str
    gateway_host: str | None
    status: Literal["queued", "running", "prepared", "completed", "failed", "cancelled"]
    stage: str
    revision: int
    attempts: int
    cancel_requested: bool
    error_code: str | None
    created_at: datetime
    execution_available: bool
    call_state: Literal["not_submitted", "intent_saved", "response_saved"]
    request_sha256: str | None
    request_bytes: int | None
    catalog_group_count: int | None
    max_output_tokens: int = 5000
    text_status: str | None
    semantic: "SemanticPlan | None"
    motion_counts: EditingMotionCounts | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    aligned_spans: list[EditingPlanningSpan] = Field(default_factory=list)
    semantic_origin: Literal["tengli_gateway"] | None
    semantic_review: Literal["unreviewed"] = "unreviewed"
    native_render_state: Literal["not_compiled", "preview_requested"] = "not_compiled"
    preview_task_id: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    auto_preview: bool = Field(default=False, exclude_if=lambda value: not value)
    auto_preview_error_code: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    auto_preview_available: bool = Field(
        default=False, exclude_if=lambda value: not value
    )
    unavailable_template_group_ids: list[str] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    excluded_template_group_ids: list[str] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    available_template_group_count: int | None = Field(
        default=None, exclude_if=lambda value: value is None, ge=0
    )
    project_image_requirements: list[EditingTemplateImageRequirement] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    overlay_template: EditingOverlayTemplate | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    artifacts: list[EditingArtifactResponse]


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


class SemanticRelationItem(StrictVideoModel):
    id: str = Field(min_length=1, max_length=80)
    first_token_id: str
    last_token_id: str
    asset_ids: list[str] = Field(default_factory=list, max_length=20)
    native_text_paths: list[str] = Field(default_factory=list, max_length=30)
    native_media_paths: list[str] = Field(default_factory=list, max_length=20)


class BilingualContrastGloss(StrictVideoModel):
    before: str = Field(min_length=1, max_length=24, pattern=r"^[A-Z]+(?:[ -][A-Z]+)*$")
    after: str = Field(min_length=1, max_length=24, pattern=r"^[A-Z]+(?:[ -][A-Z]+)*$")


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
    relation_items: list[SemanticRelationItem] = Field(
        default_factory=list, max_length=20
    )
    question_gloss: str | None = Field(
        default=None,
        min_length=1,
        max_length=24,
        pattern=r"^[A-Z][A-Z '?-]{0,23}$",
        exclude_if=lambda value: value is None,
    )
    translation_gloss: BilingualContrastGloss | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class SemanticPlan(StrictVideoModel):
    schema_version: Literal["tengli.semantic-plan/1"] = "tengli.semantic-plan/1"
    audience_question: str = Field(min_length=1, max_length=500)
    argument_outline: list[str] = Field(min_length=1, max_length=50)
    chapter_start_token_ids: list[str] = Field(
        default_factory=list, max_length=10, exclude_if=lambda value: not value
    )
    style_reason: str = Field(min_length=1, max_length=1000)
    beats: list[SemanticBeat] = Field(min_length=1, max_length=60)
    missing_materials: list[str] = Field(default_factory=list, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=40)


EditingPlanningTaskResponse.model_rebuild()
