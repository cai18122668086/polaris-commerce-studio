from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import (
    AssetLifecycleStatus,
    AssetMediaKind,
    AssetOriginKind,
    JobItemStatus,
    JobStatus,
    JobType,
    MembershipRole,
    RetryScope,
    UsageCompleteness,
)


class MoneyAmount(BaseModel):
    micros: str
    currency: str


class CostSummary(BaseModel):
    estimated_min: MoneyAmount | None
    estimated_max: MoneyAmount | None
    actual: MoneyAmount | None
    estimated_credits: int | None
    actual_credits: int | None
    usage_completeness: UsageCompleteness


class CurrentUserResponse(BaseModel):
    id: str


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    role: MembershipRole


CapabilityAvailability = Literal["available", "unavailable"]
CapabilityExecution = Literal["local", "mock", "provider", "none"]
CapabilityReasonCode = Literal[
    "LOCAL_EDIT_PROVIDER_NOT_IMPLEMENTED",
    "TASK_RUNNER_MOCK",
    "EXTERNAL_AUTHENTICATION_NOT_IMPLEMENTED",
]


class CapabilityStatus(BaseModel):
    availability: CapabilityAvailability = Field(
        description=(
            "Whether the workflow and API are available for internal testing. "
            "This does not mean that real generation is available; clients must "
            "also inspect execution."
        )
    )
    execution: CapabilityExecution = Field(
        description=(
            "How this capability executes: locally, through the zero-cost mock "
            "runner, through a real provider, or not at all."
        )
    )
    reason_code: CapabilityReasonCode | None = Field(
        description=(
            "Stable machine-readable explanation when execution is mocked or the "
            "capability is unavailable."
        )
    )


class RuntimeCapabilities(BaseModel):
    asset_management: CapabilityStatus = Field(
        description="Asset upload, listing, and private access URL workflow."
    )
    local_edit: CapabilityStatus = Field(
        description=(
            "Local-edit workflow. It uses the mock adapter under the mock runner "
            "and the dedicated strict masked-repair provider under Tengli."
        )
    )
    detail_pack: CapabilityStatus = Field(
        description=(
            "Detail-pack workflow. Its execution follows the selected task runner."
        )
    )
    external_authentication: CapabilityStatus = Field(
        description=(
            "External authentication capability. A configured mode alone does not "
            "mean that the implementation is available."
        )
    )


class RuntimeStatusResponse(BaseModel):
    environment: Literal["development", "test", "production"]
    authentication_mode: Literal["development", "external"]
    task_runner: Literal["mock", "tengli"]
    capabilities: RuntimeCapabilities


class AssetResponse(BaseModel):
    id: str
    workspace_id: str
    media_kind: AssetMediaKind
    origin_kind: AssetOriginKind
    lifecycle_status: AssetLifecycleStatus
    original_filename: str
    content_type: str
    byte_size: int
    width: int | None
    height: int | None
    sha256: str
    created_at: datetime


class AssetListResponse(BaseModel):
    items: list[AssetResponse]
    next_cursor: str | None
    has_more: bool
    total: int | None = None


class AccessUrlRequest(BaseModel):
    disposition: Literal["inline", "attachment"] = "inline"
    variant: Literal["original"] = "original"


class AccessUrlResponse(BaseModel):
    url: str
    expires_at: datetime
    disposition: Literal["inline", "attachment"]


class LocalEditInput(BaseModel):
    source_asset_id: str
    selection_mask_asset_id: str

    @model_validator(mode="after")
    def distinct_assets(self) -> "LocalEditInput":
        if self.source_asset_id == self.selection_mask_asset_id:
            raise ValueError("source and selection mask must be different assets")
        return self


class LocalEditConfiguration(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)
    quality: Literal["preview", "balanced", "final"] = "balanced"
    output_format: Literal["png"] = "png"


class ProductGroupInput(BaseModel):
    group_key: str = Field(min_length=1, max_length=64)
    asset_ids: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_assets(self) -> "ProductGroupInput":
        if len(self.asset_ids) != len(set(self.asset_ids)):
            raise ValueError("asset_ids must not contain duplicates")
        return self


class DetailPackInput(BaseModel):
    product_groups: list[ProductGroupInput] = Field(min_length=1, max_length=1)


class DetailPackConfiguration(BaseModel):
    product_name: str = Field(min_length=1, max_length=160)
    selling_points: list[str] = Field(default_factory=list, max_length=12)
    platform_code: str = Field(min_length=1, max_length=32)
    language: str = Field(default="zh-CN", min_length=2, max_length=16)
    page_count: int = Field(ge=1, le=12)
    size: Literal[
        "1024x1536",
        "1600x1600",
        "2200x2200",
        "2000x2000",
        "1000x1000",
        "1024x1024",
        "2048x2048",
        "1200x1200",
        "750x1000",
    ] = "1024x1536"


class JobCreateBase(BaseModel):
    intent: Literal["draft", "submit"] = "submit"
    display_name: str | None = Field(default=None, max_length=160)


class LocalEditJobCreate(JobCreateBase):
    type: Literal[JobType.LOCAL_EDIT]
    input: LocalEditInput
    configuration: LocalEditConfiguration


class DetailPackJobCreate(JobCreateBase):
    type: Literal[JobType.DETAIL_PACK]
    input: DetailPackInput
    configuration: DetailPackConfiguration


JobCreate = Annotated[
    LocalEditJobCreate | DetailPackJobCreate,
    Field(discriminator="type"),
]


class DraftJobUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    configuration: dict[str, Any] | None = None


class JobItemResponse(BaseModel):
    id: str
    item_key: str
    ordinal: int
    status: JobItemStatus
    stage: str | None
    quality: str | None
    result_source: str | None
    error_code: str | None
    error_message: str | None
    error_details: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None


class JobAssetResponse(BaseModel):
    asset_id: str
    job_item_id: str | None
    direction: str
    role: str
    ordinal: int
    is_deliverable: bool
    validation: dict[str, Any]


class PlanResponse(BaseModel):
    id: str
    revision: int
    schema_version: str
    payload: dict[str, Any]
    validation_status: str
    validation_errors: list[dict[str, Any]]
    confirmed_at: datetime | None


class JobListItemResponse(BaseModel):
    id: str
    workspace_id: str
    type: JobType
    status: JobStatus
    stage: str | None
    display_name: str | None
    progress: int
    expected_item_count: int
    succeeded_item_count: int
    failed_item_count: int
    allowed_actions: list[str]
    cost: CostSummary
    created_at: datetime
    updated_at: datetime


class JobDetailResponse(JobListItemResponse):
    configuration: dict[str, Any]
    configuration_schema: str
    prompt_version: str
    strategy_version: str
    release_version: str
    root_job_id: str | None
    retry_of_job_id: str | None
    retry_scope: str | None
    state_version: int
    error_code: str | None
    error_message: str | None
    error_details: dict[str, Any] | None
    api_request_count: int
    cancel_requested_at: datetime | None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    items: list[JobItemResponse]
    assets: list[JobAssetResponse]
    plan: PlanResponse | None


class JobListResponse(BaseModel):
    items: list[JobListItemResponse]
    next_cursor: str | None
    has_more: bool
    total: int | None = None


class CancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RetryRequest(BaseModel):
    scope: RetryScope = RetryScope.FAILED
    item_ids: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def selected_requires_items(self) -> "RetryRequest":
        if self.scope == RetryScope.SELECTED and not self.item_ids:
            raise ValueError("selected retry scope requires item_ids")
        if self.scope != RetryScope.SELECTED and self.item_ids:
            raise ValueError("item_ids are only valid for selected retry scope")
        return self


class PlanUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    payload: dict[str, Any]


class PlanConfirmRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    checks: dict[str, str]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class OpenAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
