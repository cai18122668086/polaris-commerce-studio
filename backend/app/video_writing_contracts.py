"""Reference evidence, editorial analysis and declared facts are different objects."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from .video_studio_schemas import StrictVideoModel, VideoWritingOrigin


class ReferenceSentence(StrictVideoModel):
    id: str
    text: str


class WritingReference(StrictVideoModel):
    reference_id: UUID
    original_text: str = Field(min_length=1, max_length=6000)
    source_url: str = ""
    source_note: str = ""
    source_project_revision: int | None = Field(default=None, ge=1)
    sentences: list[ReferenceSentence]
    visual_evidence: Literal["not_provided"] = "not_provided"
    interaction_evidence: Literal["not_provided"] = "not_provided"


class FactItem(StrictVideoModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    category: Literal["identity", "product", "story"]
    label: str = Field(min_length=1, max_length=100)
    value: str | None = Field(default=None, max_length=1000)
    status: Literal["user_declared", "unknown"] = "unknown"
    source_note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def known_value(self) -> Self:
        if self.status == "unknown" and self.value:
            raise ValueError("Unknown facts must not carry a usable value")
        if self.status == "user_declared" and not (self.value or "").strip():
            raise ValueError("Declared facts require a value")
        return self


class WritingFacts(StrictVideoModel):
    facts: list[FactItem] = Field(min_length=1, max_length=60)
    forbidden_terms: list[str] = Field(default_factory=list, max_length=100)
    restricted_claims: list[Literal["price", "net_quantity", "health_effect"]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({f.id for f in self.facts}) != len(self.facts):
            raise ValueError("Fact IDs must be unique")
        if any(not term.strip() or len(term) > 100 for term in self.forbidden_terms):
            raise ValueError("Forbidden terms must be nonempty and bounded")
        return self


class AnalysisSection(StrictVideoModel):
    id: str = Field(min_length=1, max_length=80)
    first_sentence_id: str
    last_sentence_id: str
    function: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=1, max_length=1200)


class SourceClaim(StrictVideoModel):
    sentence_id: str
    quote: str = Field(min_length=1, max_length=1000)
    category: Literal["identity", "product", "story", "promise", "rights"]
    handling: Literal["requires_user_fact", "must_replace", "do_not_copy"]
    reason: str = Field(min_length=1, max_length=600)


class WritingAnalysis(StrictVideoModel):
    schema_version: Literal["tengli.writing-analysis/1"] = "tengli.writing-analysis/1"
    topic: str = Field(min_length=1, max_length=300)
    hook_sentence_ids: list[str] = Field(min_length=1, max_length=10)
    sections: list[AnalysisSection] = Field(min_length=1, max_length=60)
    source_claims: list[SourceClaim] = Field(default_factory=list, max_length=100)
    reusable_structure: list[str] = Field(min_length=1, max_length=30)
    limitations: list[str] = Field(min_length=1, max_length=30)
    visual_review: Literal["not_provided"] = "not_provided"
    cross_account_comparison: Literal["not_provided"] = "not_provided"
    interaction_analysis: Literal["not_provided"] = "not_provided"


WritingDraftMode = Literal["structure", "shadow"]


class SpokenDraftLine(StrictVideoModel):
    text: str = Field(min_length=1, max_length=1500)
    fact_ids: list[str] = Field(default_factory=list, max_length=60)


class DraftSentence(SpokenDraftLine):
    reference_sentence_id: str
    rewritten_for: Literal["fact_replacement", "must_replace", "unchanged_structure"]


class FactReplacement(StrictVideoModel):
    category: Literal["identity", "product", "story"]
    original: str = Field(min_length=1, max_length=300)
    replacement: str = Field(min_length=1, max_length=1000)
    fact_id: str


class DraftContent(StrictVideoModel):
    title: str = Field(min_length=1, max_length=80)
    replacements: list[FactReplacement] = Field(default_factory=list, max_length=100)
    missing_facts: list[str] = Field(default_factory=list, max_length=60)
    warnings: list[str] = Field(default_factory=list, max_length=30)


class WritingDraft(DraftContent):
    schema_version: Literal["tengli.fact-mapped-draft/1"] = "tengli.fact-mapped-draft/1"
    sentences: list[DraftSentence] = Field(min_length=1, max_length=100)


class StructureDraftLine(SpokenDraftLine):
    analysis_section_id: str


class WritingStructureDraft(DraftContent):
    schema_version: Literal["tengli.structure-draft/1"] = "tengli.structure-draft/1"
    sentences: list[StructureDraftLine] = Field(min_length=1, max_length=100)


class WritingVersionSources(StrictVideoModel):
    origin: VideoWritingOrigin
    reference: WritingReference
    analysis: WritingAnalysis
    facts: WritingFacts
    draft: WritingDraft | WritingStructureDraft


class SaveWritingReference(StrictVideoModel):
    request_id: UUID
    project_id: UUID
    expected_revision: int = Field(ge=1)
    reference_id: UUID


class SaveWritingFacts(StrictVideoModel):
    request_id: UUID
    project_id: UUID
    body: WritingFacts


class WritingTaskRequest(StrictVideoModel):
    request_id: UUID
    project_id: UUID
    expected_revision: int = Field(ge=1)
    kind: Literal["ref_analysis", "fact_draft"]
    reference_document_id: UUID
    analysis_document_id: UUID | None = None
    facts_document_id: UUID | None = None
    draft_mode: WritingDraftMode | None = None
    target_duration_seconds: int | None = Field(default=None, ge=5, le=300)
    presentation: Literal["on_camera", "hands_only", "unspecified"] = "unspecified"

    @model_validator(mode="after")
    def duration_basis(self) -> Self:
        if self.kind == "ref_analysis" and (
            self.analysis_document_id
            or self.facts_document_id
            or self.target_duration_seconds is not None
            or self.draft_mode is not None
        ):
            raise ValueError("Reference analysis takes its source only")
        if (
            self.target_duration_seconds is not None
            and self.presentation == "unspecified"
        ):
            raise ValueError("A duration budget requires an explicit presentation type")
        return self


class SaveWritingResult(StrictVideoModel):
    request_id: UUID
    task_id: UUID


class ReviseWritingDraft(StrictVideoModel):
    request_id: UUID
    title: str = Field(min_length=1, max_length=80)
    sentences: list[DraftSentence | StructureDraftLine] = Field(
        min_length=1, max_length=100
    )


class ApplyWritingDraft(StrictVideoModel):
    request_id: UUID
    expected_revision: int = Field(ge=1)
