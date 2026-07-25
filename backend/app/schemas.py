from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssetOrigin(StrEnum):
    UPLOAD = "upload"
    LOCAL_EDIT = "local_edit"
    DETAIL_PACK = "detail_pack"


class JobType(StrEnum):
    LOCAL_EDIT = "local_edit"
    DETAIL_PACK = "detail_pack"


class JobStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    PLANNING = "planning"
    PROCESSING = "processing"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}
WORKSPACE_ID_PATTERN = r"^[A-Za-z0-9_-]+$"


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    task_runner: str


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    filename: str
    content_type: str
    byte_size: int
    width: int
    height: int
    storage_key: str
    origin: AssetOrigin
    created_at: datetime


class AssetListResponse(BaseModel):
    items: list[AssetResponse]
    total: int


class JobCreate(BaseModel):
    type: JobType
    workspace_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=WORKSPACE_ID_PATTERN,
    )
    input_asset_ids: list[str]
    configuration: dict[str, Any] = Field(default_factory=dict)
    prompt_version: str = Field(default="phase1-mock", max_length=64)
    strategy_version: str = Field(default="phase1-mock", max_length=64)
    estimated_cost: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_asset_count(self) -> "JobCreate":
        asset_count = len(self.input_asset_ids)
        if self.type == JobType.LOCAL_EDIT and asset_count != 1:
            raise ValueError("local_edit requires exactly one input asset")
        if self.type == JobType.DETAIL_PACK and not 1 <= asset_count <= 8:
            raise ValueError("detail_pack requires between one and eight input assets")
        if len(set(self.input_asset_ids)) != asset_count:
            raise ValueError("input_asset_ids must not contain duplicates")
        return self


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    type: JobType
    status: JobStatus
    progress: int
    input_asset_ids: list[str]
    configuration: dict[str, Any]
    prompt_version: str
    strategy_version: str
    raw_outputs: list[dict[str, Any]]
    delivery_outputs: list[dict[str, Any]]
    error_code: str | None
    error_message: str | None
    api_request_count: int
    usage: dict[str, Any]
    estimated_cost: float | None
    actual_cost: float | None
    queue_task_id: str | None
    retry_of_job_id: str | None
    parent_job_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
