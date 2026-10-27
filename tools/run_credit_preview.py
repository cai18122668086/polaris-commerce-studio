"""Only the isolated local credit preview. Never reads production .env files."""

import sys
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import uvicorn
from app.config import Settings
from app.main import create_app
from app.provider import FakeProvider, ProviderArtifact

DATA = ROOT / "backend" / ".data" / "credit-preview"
DATA.mkdir(parents=True, exist_ok=True)
settings = Settings(
    _env_file=None,
    environment="test",
    auth_mode="development",
    development_user_id="usr_credit_preview",
    development_workspace_id="ws_credit_preview",
    development_workspace_name="积分隔离验证工作区",
    database_url=f"sqlite:///{(DATA / 'credits-deliverable-v2.db').as_posix()}",
    auto_create_schema=True,
    storage_backend="local",
    storage_dir=DATA / "storage",
    task_dispatcher="inline",
    task_runner="mock",
    auto_process_jobs=True,
    provider_quota_enabled=True,
    workspace_credit_enforcement_enabled=True,
    product_image_provider_enabled=False,
    reference_remix_provider_enabled=False,
    model_pose_transfer_provider_enabled=False,
    creative_image_provider_enabled=False,
    amazon_visual_suite_provider_enabled=False,
    crossborder_detail_provider_enabled=False,
    domestic_main_image_provider_enabled=False,
    legacy_detail_api_url="",
    ecommerce_startup_recovery_enabled=False,
    ecommerce_login_enabled=False,
    aurora_work_root=DATA / "aurora",
    ecommerce_session_dir=DATA / "sessions",
    ecommerce_1688_session_dir=DATA / "sessions-1688",
    ecommerce_jd_session_dir=DATA / "sessions-jd",
    ecommerce_pinduoduo_session_dir=DATA / "sessions-pdd",
    development_provider_env_file=DATA / "providers-disabled.env",
    cors_origins=["http://127.0.0.1:4190", "http://localhost:4190"],
)


class SyntheticCreditPreviewProvider(FakeProvider):
    """Local test image only; no AI call and no supplier credentials."""

    name = "synthetic-credit-preview"

    async def execute(self, request):
        image = Image.new("RGB", (96, 96), (242, 239, 251))
        ImageDraw.Draw(image).text((10, 32), "CREDIT DEMO", fill=(85, 73, 130))
        output = BytesIO()
        image.save(output, "PNG")
        png = output.getvalue()
        return replace(
            await super().execute(request),
            artifact=ProviderArtifact(
                payload=png,
                filename="synthetic-credit-demo.png",
                content_type="image/png",
                width=96,
                height=96,
                sha256=sha256(png).hexdigest(),
            ),
        )


app = create_app(settings)
app.state.task_runner.coordinator.provider = SyntheticCreditPreviewProvider()
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8190)
