"""Replay recorded public products; live-preview and import every returned image.

Runs in an isolated container with temporary SQLite/local storage. No product
API credentials, production database, or generation provider are used.
"""

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app import aliexpress_images, amazon_product, everyinfra, replica
from app.config import Settings
from app.main import create_app
from app.models import AssetRecord

root = Path(sys.argv[1])
samples = json.loads(Path(sys.argv[2]).read_text())
groups = ("imageUrls", "descImageUrls", "skuImageUrls")
plans = []


def replay_request(key, platform, action, params):
    names = {
        ("jd", "description_images"): "jd-description",
        ("shopee", "product_detail"): "shopee-detail",
        ("alibaba1688", "product_detail"): "everyinfra-1688",
    }
    return json.loads((root / (names[(platform, action)] + ".json")).read_text())["wire"]


everyinfra._request = replay_request
for file in sorted(root.glob("*.json")):
    if not file.name.startswith(("everyinfra-", "justoneapi-")):
        continue
    row = json.loads(file.read_text())
    platform = row.get("platform")
    if row.get("ok"):
        if row["provider"] == "everyinfra":
            product = everyinfra.normalize_product(row["wire"], platform, row["item_id"], row["canonical"])
        else:
            product = row["product"]
        everyinfra.supplement_product_images("replay-only", product)
    elif platform == "walmart":
        wire = json.loads((root / "walmart-detail.json").read_text())["wire"]
        product = everyinfra.normalize_product(wire, platform, row["item_id"], row["canonical"], action="product_detail")
    else:
        continue
    plans.append((file.stem, product))
amazon = json.loads((root / "justone-amazon-raw.json").read_text())
plans.append(("justoneapi-amazon", amazon_product.normalize_product(amazon, "B09B8V1LZ3", "https://www.amazon.com/dp/B09B8V1LZ3")))
for sample in samples:
    if sample["source"] in {"aliexpress", "etsy"}:
        plans.append(("recorded-" + sample["source"], everyinfra.normalize_product(sample["response"], sample["source"], sample["item_id"], sample["canonical"])))

if len(sys.argv) > 3:
    plans = [(name, product) for name, product in plans if name in sys.argv[3:]]

settings = Settings(
    _env_file=None, environment="test", auth_mode="development",
    development_user_id="usr_all_images", development_workspace_id="ws_all_images",
    development_workspace_name="图片全渠道隔离验证",
    database_url="sqlite:////tmp/all-images.db", auto_create_schema=True,
    storage_backend="local", storage_dir=Path("/tmp/all-images-assets"),
    aurora_work_root=Path("/tmp/all-images-aurora"),
    auto_process_jobs=False, task_dispatcher="inline",
    ecommerce_startup_recovery_enabled=False, ecommerce_login_enabled=False,
    retention_enabled=False,
)
route = "/api/v1/workspaces/ws_all_images/replica"
results = []
cdn_calls = []
original_opener = aliexpress_images.build_opener


def count_opener(*args):
    cdn_calls.append(1)
    return original_opener(*args)


aliexpress_images.build_opener = count_opener
with TestClient(create_app(settings)) as client:
    for name, product in plans:
        replica.fetch_product = lambda *args, **kwargs: product
        response = client.post(route + "/products", json={"url": product["sourceUrl"]})
        assert response.status_code == 202, response.text
        document_id = response.json()["id"]
        # Primary and backup for the same item share the normal request cache;
        # isolate each replay without changing production cache semantics.
        from app.models import ReplicaDocumentRecord
        with client.app.state.session_factory() as session:
            row = session.get(ReplicaDocumentRecord, document_id)
            row.payload = {**row.payload, "product": product}
            row.status = "ready"
            session.commit()
        images = [(group, index, url) for group in groups for index, url in enumerate(product[group])]

        def preview(item):
            group, index, url = item
            r = client.get(route + f"/products/{document_id}/images/{group}/{index}")
            return {"group": group, "index": index, "url": url, "status": r.status_code,
                    "sha256": hashlib.sha256(r.content).hexdigest() if r.status_code == 200 else None,
                    "error": r.text[:250] if r.status_code != 200 else None}

        with ThreadPoolExecutor(max_workers=2) as pool:
            previews = list(pool.map(preview, images))
        hashes = {r["url"]: r["sha256"] for r in previews}
        urls = list(dict.fromkeys(url for _, _, url in images))
        imports = []
        errors = []
        before_import = len(cdn_calls)
        if all(r["status"] == 200 for r in previews):
            for start in range(0, len(urls), 20):
                r = client.post(route + f"/products/{document_id}/import", json={"urls": urls[start:start + 20]})
                if r.status_code == 200:
                    imports.extend(r.json())
                else:
                    errors.append({"status": r.status_code, "error": r.text[:250]})
        with client.app.state.session_factory() as session:
            matching = all(session.get(AssetRecord, row["asset_id"]).sha256 == hashes[row["url"]] for row in imports)
        result = {"name": name, "platform": product["platform"], "groups": {g: len(product[g]) for g in groups},
                  "previews": len(previews), "preview_ok": sum(r["status"] == 200 for r in previews),
                  "unique_urls": len(urls), "imports": len(imports), "hashes_match": matching,
                  "preview_failures": [r for r in previews if r["status"] != 200], "import_errors": errors}
        result["cdn_requests_for_import"] = len(cdn_calls) - before_import
        result["ok"] = result["preview_ok"] == len(previews) and len(imports) == len(urls) and matching and result["cdn_requests_for_import"] == 0
        results.append(result)
        Path("/tmp/all-images-evidence.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False), flush=True)
assert all(r["ok"] for r in results), "See per-channel image evidence"
print(json.dumps({"verified": True, "products": len(results), "channels": len({r['platform'] for r in results}),
                  "previews": sum(r['previews'] for r in results), "imports": sum(r['imports'] for r in results),
                  "production_database_used": False}), flush=True)
