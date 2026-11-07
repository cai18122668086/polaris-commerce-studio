"""Candidate-image smoke: disposable SQLite/storage; real product API and image.

Run in an isolated candidate container with only the EveryInfra key supplied.
This does not access the production database, storage, users or generation APIs.
"""

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

settings = Settings(
    _env_file=None,
    environment="test", auth_mode="development",
    development_user_id="usr_commerce_probe", development_workspace_id="ws_commerce_probe",
    development_workspace_name="采集隔离验证",
    database_url="sqlite:////tmp/commerce-probe.db", auto_create_schema=True,
    storage_backend="local", storage_dir=Path("/tmp/commerce-probe-assets"),
    auto_process_jobs=False, task_dispatcher="inline",
    ecommerce_startup_recovery_enabled=False, ecommerce_login_enabled=False,
    retention_enabled=False,
    everyinfra_api_key=os.environ["POLARIS_EVERYINFRA_API_KEY"],
    everyinfra_product_sources_enabled=True,
)
route = "/api/v1/workspaces/ws_commerce_probe/replica"
url = "https://www.aliexpress.us/item/3256807411229880.html?gatewayAdapt=glo2usa4itemAdapt#nav-review"
with TestClient(create_app(settings)) as client:
    platforms = client.get(route + "/product-platforms")
    assert platforms.status_code == 200 and len(platforms.json()) == 15
    response = client.post(route + "/products", json={"url": url})
    assert response.status_code == 202, response.text
    document_id = response.json()["id"]
    ready = client.get(route + "/documents/" + document_id).json()
    assert ready["status"] == "ready", ready
    product = ready["payload"]["product"]
    assert product["supplier"] == "everyinfra" and product["numIid"] == "3256807411229880"
    assert product["imageUrls"]
    preview = client.get(route + f"/products/{document_id}/images/imageUrls/0")
    assert preview.status_code == 200, preview.text[:200]
    imported = client.post(route + f"/products/{document_id}/import", json={"urls": product["imageUrls"][:1]})
    assert imported.status_code == 200 and imported.json()[0]["asset_id"], imported.text
    repeated = client.post(route + "/products", json={"url": url}).json()
    assert repeated["id"] == document_id and repeated["status"] == "ready"
    assert os.environ["POLARIS_EVERYINFRA_API_KEY"] not in json.dumps(ready)
    print(json.dumps({"sandbox_smoke": "passed", "channels": len(platforms.json()), "image_counts": {k: len(product[k]) for k in ("imageUrls", "descImageUrls", "skuImageUrls")}, "preview_bytes": len(preview.content), "imported_images": len(imported.json()), "same_day_cache": True, "production_database_used": False}, ensure_ascii=False), flush=True)
