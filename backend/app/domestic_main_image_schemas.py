from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SourceRole = Literal["primary", "detail", "back", "package", "structure"]


class DomesticMainImageSourceInput(BaseModel):
    asset_id: str = Field(min_length=1)
    role: SourceRole


class DomesticMainImageTaskCreate(BaseModel):
    product_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=120)
    product_information: str = Field(min_length=1, max_length=12_000)
    verified_attributes: dict[str, Any] = Field(default_factory=dict)
    verified_selling_points: list[str] = Field(default_factory=list, max_length=30)
    verified_scenes: list[str] = Field(default_factory=list, max_length=20)
    verified_offers: list[str] = Field(default_factory=list, max_length=20)
    verified_service_or_trust_facts: list[str] = Field(
        default_factory=list, max_length=20
    )
    sources: list[DomesticMainImageSourceInput] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def exactly_one_primary(self) -> DomesticMainImageTaskCreate:
        if sum(source.role == "primary" for source in self.sources) != 1:
            raise ValueError("exactly one source must be marked primary")
        if len({source.asset_id for source in self.sources}) != len(self.sources):
            raise ValueError("source assets must be unique")
        return self


class DomesticMainImageIdentityRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    identity_contract: dict[str, Any]


class DomesticMainImageAuthorizeRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    approval_text: str = Field(min_length=2, max_length=2_000)


class DomesticMainImageSourceResponse(BaseModel):
    asset_id: str
    evidence_id: str
    ordinal: int
    role: SourceRole
    sha256: str


class DomesticMainImagePlanRow(BaseModel):
    page_index: int
    page_role: str
    main_selling_point: str
    supporting_selling_points: list[str]
    visual_proof: str
    composition_and_subject: str
    reading_path_and_type_hierarchy: str
    non_repetition_reason: str
    commercial_closure: str


class DomesticMainImageTaskResponse(BaseModel):
    id: str
    workspace_id: str
    technical_status: str
    skill_state: str
    revision: int
    allowed_actions: list[str]
    skill_name: str
    skill_version: str
    skill_digest: str
    startup_git_commit: str
    provider_capability_status: str
    image_model: str | None
    image_model_version: str | None
    campaign_style_summary: str | None
    plan: list[DomesticMainImagePlanRow]
    generation_request_ready: bool
    generation_prompt_sha256: str | None
    reference_roles: list[str]
    edit_target_role: str | None
    last_error_code: str | None
    last_error_message: str | None
    sources: list[DomesticMainImageSourceResponse]
    created_at: datetime
    updated_at: datetime


class DomesticMainImageCapabilityResponse(BaseModel):
    skill_runtime: Literal["available", "unavailable"]
    planning: Literal["available", "unavailable"]
    image_provider: Literal["disabled", "unverified", "available"]
    paid_generation_allowed: bool
    reason_code: str | None
