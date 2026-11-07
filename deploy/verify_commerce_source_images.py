"""Exercise all real AliExpress images through preview and import in isolation.

Supply the recorded public product fixture, never a production database or
storage mount. Only public CDN reads are live; no product API or generation is
called. Imports reuse the exact bytes that were previewed.
"""

import hashlib
import json
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import aliexpress_images, replica
from app.config import Settings
from app.everyinfra import normalize_product
from app.main import create_app
from app.models import AssetRecord

fixture = next(
    sample for sample in json.loads(Path(sys.argv[1]).read_text())
    if sample["source"] == "aliexpress"
)
product = normalize_product(
    fixture["response"], fixture["source"], fixture["item_id"], fixture["canonical"]
)
replica.fetch_product = lambda *args, **kwargs: product
original_opener = aliexpress_images.build_opener
cdn_calls = []


def opener(*args):
    cdn_calls.append(1)
    return original_opener(*args)


aliexpress_images.build_opener = opener
settings = Settings(
    _env_file=None,
    environment="test", auth_mode="development",
    development_user_id="usr_cdn_probe", development_workspace_id="ws_cdn_probe",
    development_workspace_name="图片导入隔离验证",
    database_url="sqlite:////tmp/cdn-probe.db", auto_create_schema=True,
    storage_backend="local", storage_dir=Path("/tmp/cdn-probe-assets"),
    aurora_work_root=Path("/tmp/cdn-probe-aurora"),
    auto_process_jobs=False, task_dispatcher="inline",
    ecommerce_startup_recovery_enabled=False, ecommerce_login_enabled=False,
    retention_enabled=False,
)
route = "/api/v1/workspaces/ws_cdn_probe/replica"
with TestClient(create_app(settings)) as client:
    created = client.post(route + "/products", json={"url": fixture["url"]})
    assert created.status_code == 202, created.text
    document_id = created.json()["id"]
    results = []
    urls = []
    for group in ("imageUrls", "descImageUrls", "skuImageUrls"):
        for index, url in enumerate(product[group]):
            preview = client.get(route + f"/products/{document_id}/images/{group}/{index}")
            assert preview.status_code == 200, (group, index, preview.text[:100])
            with Image.open(BytesIO(preview.content)) as image:
                width, height = image.size
                image.verify()
            results.append({"group": group, "index": index, "url": url, "bytes": len(preview.content), "width": width, "height": height, "sha256": hashlib.sha256(preview.content).hexdigest()})
            urls.append(url)
        print(json.dumps({"group": group, "previewed": len(product[group])}), flush=True)
    urls = list(dict.fromkeys(urls))
    assert len(urls) == 37
    preview_calls = len(cdn_calls)
    imported = []
    for start in range(0, len(urls), 20):
        response = client.post(route + f"/products/{document_id}/import", json={"urls": urls[start:start + 20]})
        assert response.status_code == 200, response.text
        imported.extend(response.json())
    assert len(imported) == len(urls)
    assert len({row["asset_id"] for row in imported}) == len(urls)
    assert Counter(row["role"] for row in imported) == {"主图": 6, "详情图": 13, "SKU图": 18}
    hashes = {row["url"]: row["sha256"] for row in results}
    with client.app.state.session_factory() as session:
        for row in imported:
            asset = session.get(AssetRecord, row["asset_id"])
            assert asset.sha256 == hashes[row["url"]], "Imported bytes differ from preview"
    assert len(cdn_calls) == preview_calls, "Import refetched already previewed images"
    print(json.dumps({"verified": True, "product_id": product["numIid"], "previews": len(results), "imports": len(imported), "import_roles": dict(Counter(row["role"] for row in imported)), "preview_import_hashes_match": True, "groups": {group: len(product[group]) for group in ("imageUrls", "descImageUrls", "skuImageUrls")}, "cdn_requests_for_preview": preview_calls, "cdn_requests_for_import": 0, "production_database_used": False, "results": results}), flush=True)
