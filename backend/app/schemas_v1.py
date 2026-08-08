from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .amazon_visual_suite_contract import (
    AMAZON_DEFAULT_MARKETPLACE,
    AmazonMarketplace,
)
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
    "REAL_PROVIDER_NOT_REGISTERED",
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
    features: dict[str, CapabilityStatus] = Field(
        default_factory=dict,
        description="Configuration-driven workflow capability map.",
    )
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


class ProductImageInput(BaseModel):
    product_asset_ids: list[str] = Field(min_length=1, max_length=8)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_assets(self) -> "ProductImageInput":
        combined = self.product_asset_ids + self.reference_asset_ids
        if len(combined) != len(set(combined)):
            raise ValueError("input assets must not contain duplicates")
        return self


ProductImageTaskType = Literal[
    "scene_main",
    "white_background",
    "model_image",
    "change_model",
    "try_on",
    "change_scene",
    "change_background",
    "change_color",
]


class ProductImageConfiguration(BaseModel):
    task_type: ProductImageTaskType
    platform_code: str = Field(default="tmall", min_length=1, max_length=32)
    aspect_ratio: Literal["1:1", "3:4", "4:3", "4:5", "9:16", "16:9"] = "1:1"
    image_count: int = Field(default=1, ge=1, le=12)
    instruction: str = Field(default="", max_length=4000)
    target_color: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_target_color(self) -> "ProductImageConfiguration":
        if self.task_type == "change_color" and not (self.target_color or "").strip():
            raise ValueError("target_color is required for change_color")
        return self


class ReferenceRemixInput(BaseModel):
    product_asset_ids: list[str] = Field(min_length=1, max_length=8)
    reference_asset_ids: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_assets(self) -> "ReferenceRemixInput":
        combined = self.product_asset_ids + self.reference_asset_ids
        if len(combined) != len(set(combined)):
            raise ValueError("input assets must not contain duplicates")
        return self


class ReferenceRemixConfiguration(BaseModel):
    platform_code: str = Field(default="tmall", min_length=1, max_length=32)
    language: str = Field(default="zh-CN", min_length=2, max_length=16)
    selling_points: list[str] = Field(default_factory=list, max_length=12)
    aspect_ratio: Literal[
        "follow-reference", "1:1", "3:4", "4:3", "4:5", "9:16", "16:9"
    ] = "follow-reference"
    image_count: int = Field(default=1, ge=1, le=12)
    instruction: str = Field(default="", max_length=4000)


class CreativeImageInput(BaseModel):
    product_asset_ids: list[str] = Field(min_length=1, max_length=8)
    competitor_asset_ids: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_assets(self) -> "CreativeImageInput":
        combined = self.product_asset_ids + self.competitor_asset_ids
        if len(combined) != len(set(combined)):
            raise ValueError("input assets must not contain duplicates")
        return self


class CreativeImageConfiguration(BaseModel):
    creative_direction: Literal[
        "selling_point",
        "pain_point",
        "scenario",
        "promotion",
        "premium",
        "social",
    ] = "selling_point"
    platform_code: str = Field(default="tmall", min_length=1, max_length=32)
    language: str = Field(default="zh-CN", min_length=2, max_length=16)
    selling_points: list[str] = Field(default_factory=list, max_length=12)
    aspect_ratio: Literal["1:1", "3:4", "4:3", "4:5", "9:16", "16:9"] = "1:1"
    image_count: int = Field(default=1, ge=1, le=12)
    instruction: str = Field(default="", max_length=4000)


class DetailPackInput(BaseModel):
    product_groups: list[ProductGroupInput] = Field(min_length=1, max_length=1)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=8)


class DetailPackConfiguration(BaseModel):
    product_name: str = Field(min_length=1, max_length=160)
    selling_points: list[str] = Field(default_factory=list, max_length=12)
    platform_code: str = Field(min_length=1, max_length=32)
    market_region: Literal["domestic", "international"] = "international"
    category: str | None = Field(default=None, max_length=80)
    language: str = Field(default="zh-CN", min_length=2, max_length=16)
    page_count: int = Field(ge=1, le=12)
    auto_start_after_plan: bool = True
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
        "1200x1600",
        "1464x600",
        "1600x1200",
    ] = "1024x1536"

    @model_validator(mode="after")
    def default_domestic_delivery_size(self) -> "DetailPackConfiguration":
        if self.market_region == "domestic" and "size" not in self.model_fields_set:
            self.size = "1200x1600"
        return self


class AmazonVisualSuiteInput(BaseModel):
    white_background_product_asset_ids: list[str] = Field(min_length=1, max_length=8)
    detail_asset_ids: list[str] = Field(default_factory=list, max_length=8)
    package_asset_ids: list[str] = Field(default_factory=list, max_length=8)
    scene_asset_ids: list[str] = Field(default_factory=list, max_length=8)
    brand_asset_ids: list[str] = Field(default_factory=list, max_length=8)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=8)
    competitor_reference_asset_ids: list[str] = Field(
        default_factory=list,
        max_length=8,
    )

    @model_validator(mode="after")
    def unique_assets(self) -> "AmazonVisualSuiteInput":
        combined = (
            self.white_background_product_asset_ids
            + self.detail_asset_ids
            + self.package_asset_ids
            + self.scene_asset_ids
            + self.brand_asset_ids
            + self.reference_asset_ids
            + self.competitor_reference_asset_ids
        )
        if len(combined) != len(set(combined)):
            raise ValueError("input assets must not contain duplicates")
        if len(combined) > 8:
            raise ValueError("Amazon visual suite accepts at most 8 source images")
        return self


class AmazonVisualSuiteConfiguration(BaseModel):
    marketplace: AmazonMarketplace = AMAZON_DEFAULT_MARKETPLACE
    product_name: str = Field(default="", max_length=160)
    category: str = Field(default="", max_length=120)
    target_buyer: str = Field(default="", max_length=500)
    listing_title: str = Field(default="", max_length=240)
    bullet_points: list[str] = Field(default_factory=list, max_length=12)
    listing_description: str = Field(default="", max_length=4000)
    a_plus_copy: str = Field(default="", max_length=4000)
    product_facts: list[str] = Field(default_factory=list, max_length=24)
    parameters: list[str] = Field(default_factory=list, max_length=24)
    certifications_or_evidence: list[str] = Field(default_factory=list, max_length=24)
    forbidden_claims: list[str] = Field(default_factory=list, max_length=24)
    brand_colors: list[str] = Field(default_factory=list, max_length=8)
    style_preferences: list[str] = Field(default_factory=list, max_length=12)
    instruction: str = Field(default="", max_length=4000)
    language: str = Field(default="en-US", min_length=2, max_length=16)


class JobCreateBase(BaseModel):
    intent: Literal["draft", "submit"] = "submit"
    display_name: str | None = Field(default=None, max_length=160)


class LocalEditJobCreate(JobCreateBase):
    type: Literal[JobType.LOCAL_EDIT]
    input: LocalEditInput
    configuration: LocalEditConfiguration


class ProductImageJobCreate(JobCreateBase):
    type: Literal[JobType.PRODUCT_IMAGE]
    input: ProductImageInput
    configuration: ProductImageConfiguration


class ReferenceRemixJobCreate(JobCreateBase):
    type: Literal[JobType.REFERENCE_REMIX]
    input: ReferenceRemixInput
    configuration: ReferenceRemixConfiguration


class CreativeImageJobCreate(JobCreateBase):
    type: Literal[JobType.CREATIVE_IMAGE]
    input: CreativeImageInput
    configuration: CreativeImageConfiguration


class DetailPackJobCreate(JobCreateBase):
    type: Literal[JobType.DETAIL_PACK]
    input: DetailPackInput
    configuration: DetailPackConfiguration


class AmazonVisualSuiteJobCreate(JobCreateBase):
    type: Literal[JobType.AMAZON_VISUAL_SUITE]
    input: AmazonVisualSuiteInput
    configuration: AmazonVisualSuiteConfiguration


JobCreate = Annotated[
    LocalEditJobCreate
    | ProductImageJobCreate
    | ReferenceRemixJobCreate
    | CreativeImageJobCreate
    | DetailPackJobCreate
    | AmazonVisualSuiteJobCreate,
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
