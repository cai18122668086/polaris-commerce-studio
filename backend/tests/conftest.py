from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        auth_mode="development",
        development_user_id="usr_test",
        development_workspace_id="ws_test",
        development_workspace_name="测试工作区",
        access_url_secret="test-access-url-secret",
        release_sha="a" * 40,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        auto_create_schema=True,
        storage_backend="local",
        storage_dir=tmp_path / "storage",
        domestic_main_image_asset_cache_dir=tmp_path / "main-image-assets",
        auto_process_jobs=False,
        task_dispatcher="inline",
        mock_job_delay_seconds=0,
        workspace_credit_enforcement_enabled=True,
        max_upload_bytes=2 * 1024 * 1024,
        max_image_pixels=2_000_000,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
