from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

InspirationStatus = Literal["draft", "published", "archived"]
InspirationAssetRole = Literal["result", "user_upload", "reference"]

class InspirationAssetInput(BaseModel):
    asset_id: str = Field(min_length=1, max_length=40)
    role: InspirationAssetRole
    ordinal: int = Field(default=0, ge=0)
    label: str | None = Field(default=None, max_length=40)

class InspirationCaseCreate(BaseModel):
    slug: str | None = Field(default=None, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    role: str = Field(default="", max_length=80)
    type: str = Field(default="万能改图", max_length=40)
    category: str = Field(default="其他", max_length=80)
    platform: str = Field(default="国内", max_length=16)
    ratio: str = Field(default="自动", max_length=24)
    intent: str = Field(default="", max_length=300)
    prompt: str = Field(min_length=1)
    sort_order: int = 0
    is_pinned: bool = False
    assets: list[InspirationAssetInput] = Field(default_factory=list)

class InspirationCaseUpdate(InspirationCaseCreate):
    pass

class InspirationAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    asset_id: str
    role: InspirationAssetRole
    ordinal: int
    label: str | None
    url: str

class InspirationCaseResponse(BaseModel):
    id: str
    slug: str | None
    title: str
    description: str
    role: str
    type: str
    category: str
    platform: str
    ratio: str
    intent: str
    prompt: str
    status: InspirationStatus
    sort_order: int
    is_pinned: bool
    cover_image: InspirationAssetResponse | None
    gallery: list[InspirationAssetResponse]
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime

class InspirationCaseListResponse(BaseModel):
    items: list[InspirationCaseResponse]

class InspirationAdminAccessResponse(BaseModel):
    can_manage: bool
