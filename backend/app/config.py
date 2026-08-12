from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MAX_PROVIDER_ALLOWANCE = 20_000_000


def default_masked_skill_root() -> Path:
    """Return the project-owned, distributable masked repair runtime source."""

    return (
        Path(__file__).resolve().parents[1]
        / "skill_sources"
        / "masked-image-repair"
    )


def default_xinghe_skill_root() -> Path:
    """Return the project-owned, distributable Xinghe runtime source."""

    return (
        Path(__file__).resolve().parents[1]
        / "skill_sources"
        / "xinghe-ecommerce-detail"
    )


def default_skill_root(skill_id: str) -> Path:
    """Return a project-owned runtime source without changing existing roots."""

    if skill_id == "masked-image-repair":
        return default_masked_skill_root()
    if skill_id == "xinghe-ecommerce-detail":
        return default_xinghe_skill_root()
    return Path(__file__).resolve().parents[1] / "skill_sources" / skill_id


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
    supertokens_connection_uri: str = "http://localhost:3567"
    supertokens_api_key: SecretStr = SecretStr("")
    supertokens_api_domain: str = "https://www.tengliapi.xyz"
    supertokens_website_domain: str = "https://www.tengliapi.xyz"
    supertokens_api_base_path: str = "/api/auth"
    supertokens_website_base_path: str = "/auth"
    supertokens_cookie_secure: bool = True
    supertokens_cookie_same_site: Literal["lax", "none", "strict"] = "lax"
    auth_smtp_host: str = ""
    auth_smtp_port: int = Field(default=587, ge=1, le=65535)
    auth_smtp_username: str = ""
    auth_smtp_password: SecretStr = SecretStr("")
    auth_smtp_secure: bool = False
    auth_email_from_name: str = "Polaris Commerce Studio"
    auth_email_from_address: str = ""
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
    asset_access_url_mode: Literal["auto", "same_origin"] = "auto"
    auto_process_jobs: bool = True
    task_dispatcher: Literal["inline", "celery"] = "celery"
    task_runner: Literal["mock", "tengli"] = "mock"
    product_image_provider_enabled: bool = Field(default=False)
    reference_remix_provider_enabled: bool = Field(default=False)
    model_pose_transfer_provider_enabled: bool = Field(default=False)
    creative_image_provider_enabled: bool = Field(default=False)
    amazon_visual_suite_provider_enabled: bool = Field(default=False)
    domestic_main_image_provider_enabled: bool = Field(default=False)
    crossborder_detail_provider_enabled: bool = Field(default=False)
    mock_job_delay_seconds: float = Field(default=0.35, ge=0, le=10)
    tengli_api_key: SecretStr = SecretStr("")
    tengli_base_url: str = "https://api.tengliapi.xyz:8443"
    tengli_image_model: str = "gpt-image-2"
    tengli_vision_model: str = "gpt-5.6-terra"
    tengli_smoke_budget_usd: float = Field(
        default=200,
        gt=0,
        le=MAX_PROVIDER_ALLOWANCE,
    )
    provider_quota_enabled: bool = Field(default=True)
    workspace_credit_enforcement_enabled: bool = Field(default=False)
    tengli_daily_budget_usd: float = Field(
        default=0,
        ge=0,
        le=MAX_PROVIDER_ALLOWANCE,
    )
    tengli_monthly_budget_usd: float = Field(
        default=0,
        ge=0,
        le=MAX_PROVIDER_ALLOWANCE,
    )
    tengli_daily_request_limit: int = Field(
        default=0,
        ge=0,
        le=MAX_PROVIDER_ALLOWANCE,
    )
    tengli_planner_reserve_micros: int = Field(
        default=250_000,
        ge=1,
        le=2_000_000,
    )
    xinghe_concurrency: Literal[1, 2, 6] = 6
    xinghe_medium_price_micros: int = Field(default=45_000, ge=0)
    xinghe_high_price_micros: int = Field(default=90_000, ge=0)
    xinghe_skill_root: Path = Field(default_factory=default_xinghe_skill_root)
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

    @field_validator("xinghe_concurrency", mode="before")
    @classmethod
    def parse_xinghe_concurrency(cls, value: object) -> object:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                pass
        return value

    def validate_runtime_safety(self) -> None:
        required_smtp = {
            "POLARIS_AUTH_SMTP_HOST": self.auth_smtp_host,
            "POLARIS_AUTH_SMTP_USERNAME": self.auth_smtp_username,
            "POLARIS_AUTH_SMTP_PASSWORD": self.auth_smtp_password.get_secret_value(),
            "POLARIS_AUTH_EMAIL_FROM_ADDRESS": self.auth_email_from_address,
        }
        smtp_configured = any(required_smtp.values())
        missing_smtp = [name for name, value in required_smtp.items() if not value]
        if smtp_configured and missing_smtp:
            raise RuntimeError(
                "transaction email configuration is incomplete: "
                + ", ".join(missing_smtp)
            )
        if self.environment != "production":
            return
        if self.auth_mode == "development":
            raise RuntimeError(
                "production must not use development authentication mode"
            )
        if not self.supertokens_cookie_secure:
            raise RuntimeError("production SuperTokens cookies must use Secure")
        if not self.supertokens_api_domain.startswith("https://"):
            raise RuntimeError("production SuperTokens API domain must use HTTPS")
        if not self.supertokens_website_domain.startswith("https://"):
            raise RuntimeError("production SuperTokens website domain must use HTTPS")
        if not self.supertokens_api_key.get_secret_value():
            raise RuntimeError("production SuperTokens Core API key is required")
        if not smtp_configured:
            raise RuntimeError("production transaction email SMTP is required")
        forbidden_secrets = {
            "polaris_minio_dev_only",
            "development-access-url-secret-change-me",
        }
        if self.s3_secret_key in forbidden_secrets:
            raise RuntimeError(
                "production S3 secret key must not use a development placeholder"
            )
        if self.access_url_secret in forbidden_secrets:
            raise RuntimeError(
                "production access URL secret must not use a development placeholder"
            )
