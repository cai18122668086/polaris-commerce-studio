from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="POLARIS_",
        extra="ignore",
    )

    app_name: str = "Polaris Commerce Studio API"
    app_version: str = "1.1.0"
    environment: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["development", "external"] = "development"
    development_user_id: str = "usr_development"
    development_workspace_id: str = "ws_development"
    development_workspace_name: str = "开发工作区"
    access_url_secret: str = "development-access-url-secret-change-me"
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
    s3_auto_create_bucket: bool = True
    auto_process_jobs: bool = True
    task_dispatcher: Literal["inline", "celery"] = "celery"
    task_runner: Literal["mock", "tengli"] = "mock"
    mock_job_delay_seconds: float = Field(default=0.35, ge=0, le=10)
    tengli_api_key: SecretStr = SecretStr("")
    tengli_base_url: str = "https://api.tengliapi.xyz:8443"
    tengli_image_model: str = "gpt-image-2"
    tengli_vision_model: str = "gpt-5.6-terra"
    tengli_smoke_budget_usd: float = Field(default=200, gt=0, le=200)
    xinghe_concurrency: Literal[1, 2, 6] = 6
    xinghe_medium_price_micros: int = Field(default=45_000, ge=0)
    xinghe_high_price_micros: int = Field(default=90_000, ge=0)
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

    def validate_runtime_safety(self) -> None:
        if self.environment != "production":
            return
        if self.auth_mode == "development":
            raise RuntimeError("生产环境禁止使用 development 身份模式。")
        forbidden_secrets = {
            "polaris_minio_dev_only",
            "development-access-url-secret-change-me",
        }
        if self.s3_secret_key in forbidden_secrets:
            raise RuntimeError("生产环境禁止使用开发对象存储密钥。")
        if self.access_url_secret in forbidden_secrets:
            raise RuntimeError("生产环境必须配置独立的访问 URL 签名密钥。")
