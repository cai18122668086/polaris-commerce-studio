import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
from pydantic import SecretStr

from app import commerce_sources, everyinfra
from app.commerce_images import image_url
from app.errors import ApiError

SAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/everyinfra-product-samples.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s["source"])
def test_real_responses_preserve_product_identity_and_image_roles(sample):
    assert commerce_sources.parse_product_link(sample["url"], sample["source"]) == (
        sample["source"],
        sample["item_id"],
        sample["canonical"],
    )
    product = everyinfra.normalize_product(
        sample["response"], sample["source"], sample["item_id"], sample["canonical"]
    )
    assert {k: len(product[k]) for k in sample["counts"]} == sample["counts"]
    assert product["supplier"] == "everyinfra"


@pytest.mark.parametrize(
    "url,source,item",
    [
        (
            "https://www.amazon.co.jp/product/dp/B09B8V1LZ3?tag=track",
            "amazon",
            "B09B8V1LZ3",
        ),
        ("https://shopee.sg/product/123/456?utm=abc", "shopee", "456"),
        (
            "https://www.ebay.co.uk/itm/Some-Item/133576802017?var=4",
            "ebay",
            "133576802017",
        ),
        ("https://www.etsy.com/listing/1710567856/title", "etsy", "1710567856"),
        (
            "https://www.temu.com/some-title-g-601103236118964.html?sku_id=12",
            "temu",
            "601103236118964",
        ),
        (
            "https://www.walmart.com/ip/Some-Product/19564124754",
            "walmart",
            "19564124754",
        ),
        ("https://www.dewu.com/product-detail.html?spuId=123456", "dewu", "123456"),
        ("https://www.goofish.com/item?id=123456", "xianyu", "123456"),
    ],
)
def test_marketplace_paths_strip_tracking_without_changing_identity(url, source, item):
    platform, item_id, canonical = commerce_sources.parse_product_link(url)
    assert (platform, item_id) == (source, item)
    assert "utm" not in canonical and "sku_id" not in canonical


@pytest.mark.parametrize(
    "source",
    [
        "amazon",
        "dewu",
        "ebay",
        "etsy",
        "walmart",
        "temu",
        "douyin",
        "xianyu",
        "xiaohongshu",
    ],
)
def test_explicit_source_is_required_for_identifiers(source):
    value = (
        "B09B8V1LZ3"
        if source == "amazon"
        else "6a4629ef7d09bf0001a45876"
        if source == "xiaohongshu"
        else "123456789012"
    )
    assert commerce_sources.parse_product_link(value, source)[0] == source
    with pytest.raises(ApiError):
        commerce_sources.parse_product_link(value)


@pytest.mark.parametrize(
    "url",
    [
        "https://amazon.com.evil.test/dp/B09B8V1LZ3",
        "https://u:p@www.amazon.com/dp/B09B8V1LZ3",
        "https://www.amazon.com:8443/dp/B09B8V1LZ3",
        "https://127.0.0.1/ip/123456",
        "https://www.etsy.com/shop/seller",
        "https://shopee.sg/shop/123",
        "https://www.xiaohongshu.com/user/profile/6a4629ef7d09bf0001a45876",
        "https://www.douyin.com/video/123456789012",
        "https://haohuo.jinritemai.com/views/product/item2?promotion_id=123456789012",
        "https://mobile.yangkeduo.com/goods.html?goods_id=123456789",
    ],
)
def test_unsupported_and_non_product_urls_are_rejected(url):
    with pytest.raises(ApiError):
        commerce_sources.parse_product_link(url)


def test_primary_success_does_not_spend_backup_credits(monkeypatch):
    primary = {"supplier": "justoneapi"}
    monkeypatch.setattr("app.justone.fetch_product", lambda *args: primary)
    monkeypatch.setattr(
        everyinfra, "fetch_product", lambda *args: pytest.fail("backup queried")
    )
    assert (
        commerce_sources.fetch_product(
            "primary", "jd", "123", "url", everyinfra_key="backup"
        )
        is primary
    )


@pytest.mark.parametrize(
    "code",
    [
        "PRODUCT_IMAGES_MISSING",
        "PRODUCT_PROVIDER_301",
        "PRODUCT_PROVIDER_UNAVAILABLE",
        "PRODUCT_PROVIDER_NOT_CONFIGURED",
    ],
)
def test_primary_failure_queries_backup_once(monkeypatch, code):
    calls = []

    def primary(*args):
        raise ApiError(502, code, "private upstream details")

    def backup(*args):
        calls.append(args)
        return {"supplier": "everyinfra"}

    monkeypatch.setattr("app.justone.fetch_product", primary)
    monkeypatch.setattr(everyinfra, "fetch_product", backup)
    result = commerce_sources.fetch_product(
        "primary", "jd", "123", "url", everyinfra_key="backup"
    )
    assert len(calls) == 1
    assert result["fallbackFrom"] == "justoneapi"
    assert result["fallbackReason"] == code
    assert "private upstream" not in json.dumps(result)


def test_new_channel_uses_everyinfra_without_calling_primary(monkeypatch):
    monkeypatch.setattr(
        "app.justone.fetch_product", lambda *args: pytest.fail("primary queried")
    )
    monkeypatch.setattr(
        everyinfra, "fetch_product", lambda *args: {"supplier": "everyinfra"}
    )
    for source in [
        "aliexpress",
        "shopee",
        "temu",
        "dewu",
        "xianyu",
        "walmart",
        "etsy",
        "ebay",
        "xiaohongshu",
        "douyin",
    ]:
        assert (
            commerce_sources.fetch_product(
                "primary", source, "id", "url", everyinfra_key="backup"
            )["supplier"]
            == "everyinfra"
        )


def test_image_groups_ignore_seller_reviews_and_recommendations():
    sample = SAMPLES[0]
    wire = json.loads(json.dumps(sample["response"]))
    unwanted = "https://ae-pic-a1.aliexpress-media.com/unrelated.jpg"
    wire["results"].update(
        {
            "shop": {"images": [unwanted]},
            "reviews": [{"images": [unwanted]}],
            "recommendations": [{"images": [unwanted]}],
        }
    )
    product = everyinfra.normalize_product(
        wire, sample["source"], sample["item_id"], sample["canonical"]
    )
    assert (
        unwanted
        not in product["imageUrls"] + product["descImageUrls"] + product["skuImageUrls"]
    )


@pytest.mark.parametrize("field,value", [("id", "wrong"), ("platform", "jd")])
def test_backup_cannot_substitute_another_product_or_platform(field, value):
    sample = SAMPLES[0]
    wire = json.loads(json.dumps(sample["response"]))
    wire["results"][field] = value
    with pytest.raises(ApiError) as caught:
        everyinfra.normalize_product(
            wire, sample["source"], sample["item_id"], sample["canonical"]
        )
    assert caught.value.code == "PRODUCT_ID_MISMATCH"


@pytest.mark.parametrize(
    "host",
    [
        "m.media-amazon.com",
        "i.etsystatic.com",
        "down-id.img.susercontent.com",
        "mall-i2.xhscdn.com",
        "i5.walmartimages.com",
        "cdn.poizon.com",
    ],
)
def test_new_image_hosts_keep_existing_url_restrictions(host):
    assert image_url(f"https://{host}/image")
    assert image_url(f"https://{host}.evil.test/image") is None
    assert image_url(f"https://u:p@{host}/image") is None
    assert image_url(f"https://{host}:8443/image") is None
    assert image_url(f"https://{host}/page.html") is None


def test_channel_catalog_and_backup_success_are_cached_in_the_workspace(
    client, monkeypatch
):
    client.app.state.settings.everyinfra_product_sources_enabled = True
    client.app.state.settings.everyinfra_api_key = SecretStr("backup-test-key")
    route = "/api/v1/workspaces/ws_test/replica"
    channels = client.get(route + "/product-platforms").json()
    assert len(channels) == 15
    assert "pinduoduo" not in {x["code"] for x in channels}
    calls = []
    sample = SAMPLES[0]

    def request(key, platform, action, params):
        calls.append((platform, action, params))
        return sample["response"]

    monkeypatch.setattr(everyinfra, "_request", request)
    first = client.post(route + "/products", json={"url": sample["url"]})
    assert first.status_code == 202
    cached = client.post(route + "/products", json={"url": sample["url"]}).json()
    assert cached["id"] == first.json()["id"]
    assert cached["status"] == "ready"
    assert cached["payload"]["product"]["supplier"] == "everyinfra"
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 402, 422, 429, 503])
def test_http_failures_are_bounded_and_do_not_expose_provider_secrets(
    monkeypatch, status
):
    calls = []

    def open_request(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, status, "private-key-error", {}, BytesIO())

    monkeypatch.setattr(
        everyinfra, "build_opener", lambda *args: SimpleNamespace(open=open_request)
    )
    with pytest.raises(ApiError) as caught:
        everyinfra.fetch_product(
            "private-key",
            "aliexpress",
            "123456789",
            "https://www.aliexpress.us/item/123456789.html",
        )
    assert len(calls) == 1
    assert "private-key" not in caught.value.message
    assert caught.value.code == f"EVERYINFRA_{status}"


def test_credential_is_only_sent_in_header_to_fixed_provider_origin(monkeypatch):
    sample = SAMPLES[0]
    calls = []

    def open_request(request, timeout):
        calls.append(request)
        return BytesIO(json.dumps(sample["response"]).encode())

    monkeypatch.setattr(
        everyinfra, "build_opener", lambda *args: SimpleNamespace(open=open_request)
    )
    everyinfra.fetch_product(
        "private-key", sample["source"], sample["item_id"], sample["canonical"]
    )
    assert calls[0].full_url == "https://api.everyinfra.com/api/v1/social"
    assert calls[0].get_header("Authorization") == "Bearer private-key"
    assert "private-key" not in calls[0].data.decode()
    with pytest.raises(ApiError):
        everyinfra.NoRedirects().redirect_request(
            calls[0], None, 302, "", {}, "https://evil.test"
        )
