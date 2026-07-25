from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="POLARIS_",
        extra="ignore",
    )

    app_name: str = "Polaris Commerce Studio API"
    app_version: str = "0.1.0"
    database_url: str = (
        "postgresql+psycopg://polaris:polaris_dev_only@localhost:5432/polaris"
    )
    auto_create_schema: bool = False
    storage_backend: Literal["local", "s3"] = "s3"
    storage_dir: Path = Path("backend/.data/storage")
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key: str = "polaris_minio"
    s3_secret_key: str = "polaris_minio_dev_only"
    s3_bucket: str = "polaris-assets"
    auto_process_jobs: bool = True
    task_dispatcher: Literal["inline", "celery"] = "celery"
    mock_job_delay_seconds: float = Field(default=0.35, ge=0, le=10)
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    max_image_pixels: int = Field(default=40_000_000, ge=1)
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:3001",
        ]
    )
