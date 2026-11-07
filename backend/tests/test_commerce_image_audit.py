import copy
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from app import amazon_product, commerce_sources, everyinfra, replica
from app.commerce_images import download_url
from app.errors import ApiError

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/commerce-image-audit.json").read_text(
        encoding="utf-8"
    )
)
SAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/everyinfra-product-samples.json").read_text(
        encoding="utf-8"
    )
)


def test_shopee_profile_keeps_gallery_and_adds_verified_variant_images(monkeypatch):
    sample = next(s for s in SAMPLES if s["source"] == "shopee")
    calls = []

    def request(key, platform, action, params):
        calls.append(action)
        return sample["response"] if action == "profile" else FIXTURES["shopee-detail"]

    monkeypatch.setattr(everyinfra, "_request", request)
    p = everyinfra.fetch_product(
        "key", "shopee", sample["item_id"], sample["canonical"]
    )
    assert calls == ["profile", "product_detail"]
    assert len(p["imageUrls"]) == 9
    assert len(p["skuImageUrls"]) == 4
    assert p["descImageUrls"] == []


@pytest.mark.parametrize("wrong", [False, True])
def test_jd_description_endpoint_checks_each_item_identity(monkeypatch, wrong):
    sample = next(s for s in SAMPLES if s["source"] == "jd")
    wire = copy.deepcopy(FIXTURES["jd-description"])
    if wrong:
        wire["results"][3]["item_id"] = "unrelated"
    monkeypatch.setattr(everyinfra, "_request", lambda *args: wire)
    p = everyinfra.normalize_product(
        sample["response"], "jd", sample["item_id"], sample["canonical"]
    )
    everyinfra.supplement_product_images("key", p)
    assert len(p["descImageUrls"]) == (0 if wrong else 11)
    if wrong:
        assert p["imageFetchWarnings"] == [
            {"group": "descImageUrls", "code": "PRODUCT_ID_MISMATCH"}
        ]


def test_supplement_failure_retains_usable_gallery(monkeypatch):
    sample = next(s for s in SAMPLES if s["source"] == "shopee")
    p = everyinfra.normalize_product(
        sample["response"], "shopee", sample["item_id"], sample["canonical"]
    )

    def fail(*args):
        raise ApiError(502, "EVERYINFRA_503", "private error")

    monkeypatch.setattr(everyinfra, "_request", fail)
    everyinfra.supplement_product_images("key", p)
    assert len(p["imageUrls"]) == 9
    assert "private error" not in json.dumps(p)


def test_walmart_text_only_profile_uses_same_listing_detail(monkeypatch):
    calls = []

    def request(key, platform, action, params):
        calls.append(action)
        return (
            {"results": {"item_id": "19564124754"}}
            if action == "profile"
            else FIXTURES["walmart-detail"]
        )

    monkeypatch.setattr(everyinfra, "_request", request)
    p = everyinfra.fetch_product(
        "key", "walmart", "19564124754", "https://www.walmart.com/ip/19564124754"
    )
    assert calls == ["profile", "product_detail"]
    assert len(p["imageUrls"]) == 1
    assert p["capability"] == "walmart.product_detail"


def test_missing_1688_details_are_supplemented_without_replacing_main_or_skus(
    monkeypatch,
):
    sample = next(s for s in SAMPLES if s["source"] == "1688")
    original = {
        "platform": "1688",
        "numIid": sample["item_id"],
        "sourceUrl": sample["canonical"],
        "imageUrls": ["main"],
        "descImageUrls": [],
        "skuImageUrls": ["sku"],
        "supplier": "justoneapi",
    }
    monkeypatch.setattr("app.justone.fetch_product", lambda *args: original)
    monkeypatch.setattr(everyinfra, "_request", lambda *args: sample["response"])
    p = commerce_sources.fetch_product(
        "key", "1688", sample["item_id"], sample["canonical"], everyinfra_key="backup"
    )
    assert p["imageUrls"] == ["main"] and p["skuImageUrls"] == ["sku"]
    assert len(p["descImageUrls"]) == 16


def test_xhs_heif_is_requested_as_same_object_webp_for_preview_and_import(monkeypatch):
    url = "https://mall-i2.xhscdn.com/arkgoods/object?imageView2/2/w/1440/format/heif/q/46&sign=keep&ap=3"
    changed = download_url(url)
    assert changed == url.replace("/format/heif", "/format/webp")
    assert download_url(
        url.replace("xhscdn.com", "xhscdn.com.evil.test")
    ) == url.replace("xhscdn.com", "xhscdn.com.evil.test")
    data = BytesIO()
    Image.new("RGB", (80, 80)).save(data, "WEBP")
    requests = []

    def open_request(request, timeout):
        requests.append(request)
        return BytesIO(data.getvalue())

    monkeypatch.setattr(
        "app.aliexpress_images.build_opener",
        lambda *args: SimpleNamespace(open=open_request),
    )
    assert replica._download(url, 10000) == data.getvalue()
    assert requests[0].full_url == changed
    assert "image/avif" not in requests[0].get_header("Accept")


def test_amazon_explicit_groups_exclude_reviews_and_sponsored_photos(monkeypatch):
    wire = copy.deepcopy(FIXTURES["justone-amazon-raw"])
    wire["data"]["aplus_images"] = ["https://m.media-amazon.com/aplus.jpg"]
    p = amazon_product.normalize_product(
        wire, "B09B8V1LZ3", "https://www.amazon.com/dp/B09B8V1LZ3"
    )
    assert len(p["imageUrls"]) == 9
    assert len(p["skuImageUrls"]) == 3
    assert p["descImageUrls"] == ["https://m.media-amazon.com/aplus.jpg"]
    monkeypatch.setattr(amazon_product, "fetch_product", lambda *args: p)
    monkeypatch.setattr(
        everyinfra, "fetch_product", lambda *args: pytest.fail("unneeded backup query")
    )
    assert (
        commerce_sources.fetch_product(
            "key", "amazon", "B09B8V1LZ3", p["sourceUrl"], everyinfra_key="backup"
        )
        is p
    )


@pytest.mark.parametrize(
    "field,value", [("asin", "OTHER"), ("country", "JP"), ("landing_asin", "OTHER")]
)
def test_amazon_market_and_identity_are_checked(field, value):
    wire = copy.deepcopy(FIXTURES["justone-amazon-raw"])
    wire["data"][field] = value
    with pytest.raises(ApiError) as caught:
        amazon_product.normalize_product(
            wire, "B09B8V1LZ3", "https://www.amazon.com/dp/B09B8V1LZ3"
        )
    assert caught.value.code == "PRODUCT_ID_MISMATCH"


def test_amazon_request_uses_requested_market_and_falls_back_once(monkeypatch):
    requests = []

    def open_request(request, timeout):
        requests.append(request)
        return BytesIO(json.dumps(FIXTURES["justone-amazon-raw"]).encode())

    monkeypatch.setattr(
        amazon_product, "build_opener", lambda *args: SimpleNamespace(open=open_request)
    )
    with pytest.raises(ApiError):
        amazon_product.fetch_product(
            "private-token", "B09B8V1LZ3", "https://www.amazon.co.jp/dp/B09B8V1LZ3"
        )
    assert parse_qs(urlparse(requests[0].full_url).query)["country"] == ["JP"]

    def fail(*args):
        raise ApiError(502, "PRODUCT_PROVIDER_UNAVAILABLE", "redacted")

    monkeypatch.setattr(amazon_product, "fetch_product", fail)
    calls = []
    monkeypatch.setattr(
        everyinfra,
        "fetch_product",
        lambda *args: calls.append(args) or {"supplier": "everyinfra"},
    )
    p = commerce_sources.fetch_product(
        "token",
        "amazon",
        "B09B8V1LZ3",
        "https://www.amazon.com/dp/B09B8V1LZ3",
        everyinfra_key="key",
    )
    assert len(calls) == 1 and p["fallbackFrom"] == "justoneapi"


def test_temu_options_preserve_sku_images_even_when_they_overlap_gallery():
    p = everyinfra.normalize_product(
        FIXTURES["everyinfra-temu"],
        "temu",
        "601103236118964",
        "https://www.temu.com/goods.html?goods_id=601103236118964",
    )
    assert len(p["skuImageUrls"]) == 2
    assert p["skuImageUrls"] == p["imageUrls"]
