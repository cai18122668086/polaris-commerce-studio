import json
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image
from pydantic import SecretStr

from app.errors import ApiError
from app.justone import fetch_product, image_url, parse_product_link

ITEM_ID = "3256807411229880"
US_URL = f"https://www.aliexpress.us/item/{ITEM_ID}.html"
GLO_URL = f"https://www.aliexpress.com/item/{ITEM_ID}.html"
USER_URL = US_URL + "?gatewayAdapt=glo2usa4itemAdapt#nav-review"
IMAGE = "https://ae-pic-a1.aliexpress-media.com/kf/product.jpg"
ROUTE = "/api/v1/workspaces/ws_test/replica"


def provider(monkeypatch, data):
    calls = []

    def open_request(request, timeout):
        calls.append(request)
        return BytesIO(json.dumps({"code": 0, "data": data}).encode())

    monkeypatch.setattr(
        "app.justone.build_opener",
        lambda *handlers: SimpleNamespace(open=open_request),
    )
    return calls


@pytest.mark.parametrize(
    ("link", "canonical"),
    [
        (USER_URL, US_URL),
        (GLO_URL + "?skuId=987654321", GLO_URL),
        (US_URL + "?itemId=987654321", US_URL),
        (f"https://m.aliexpress.com/item/{ITEM_ID}.html", GLO_URL),
    ],
)
def test_listing_path_and_site_survive_tracking_parameters(link, canonical):
    assert parse_product_link(link) == ("aliexpress", ITEM_ID, canonical)


def test_bare_id_defaults_to_us():
    assert parse_product_link(ITEM_ID, "aliexpress") == (
        "aliexpress",
        ITEM_ID,
        US_URL,
    )


@pytest.mark.parametrize(
    "link",
    [
        f"https://aliexpress.us.evil.test/item/{ITEM_ID}.html",
        f"https://u:p@aliexpress.us/item/{ITEM_ID}.html",
        f"https://aliexpress.us:8443/item/{ITEM_ID}.html",
        f"https://aliexpress.us/store/123?itemId={ITEM_ID}",
    ],
)
def test_unsupported_hosts_and_non_listing_pages_are_rejected(link):
    with pytest.raises(ApiError):
        parse_product_link(link)


@pytest.mark.parametrize(("canonical", "site"), [(US_URL, "US"), (GLO_URL, "GLO")])
def test_request_uses_correct_site_and_normalizes_gallery(monkeypatch, canonical, site):
    calls = provider(
        monkeypatch,
        {
            "site": site,
            "product_id": ITEM_ID,
            "title": "Collectible figure",
            "images": [IMAGE, IMAGE, "https://evil.test/other.jpg"],
        },
    )
    product = fetch_product("test-token", "aliexpress", ITEM_ID, canonical)
    request = urlparse(calls[0].full_url)
    assert request.path == "/api/aliexpress/get-product-detail/v1"
    assert parse_qs(request.query) == {
        "token": ["test-token"],
        "itemId": [ITEM_ID],
        "site": [site],
    }
    assert len(calls) == 1
    assert product["sourceUrl"] == canonical
    assert product["imageUrls"] == [IMAGE]
    assert product["descImageUrls"] == []
    assert product["skuImageUrls"] == []
    assert product["costCents"] is None  # Account tariff is unverified.


@pytest.mark.parametrize("returned_id", [None, "987654321"])
def test_different_or_missing_product_identity_is_rejected(monkeypatch, returned_id):
    provider(monkeypatch, {"product_id": returned_id, "images": [IMAGE]})
    with pytest.raises(ApiError) as caught:
        fetch_product("test-token", "aliexpress", ITEM_ID, US_URL)
    assert caught.value.code == "PRODUCT_ID_MISMATCH"


def test_aliexpress_cdn_does_not_allow_untrusted_image_hosts():
    assert image_url(IMAGE) == IMAGE
    assert image_url("https://ae01.alicdn.com/kf/product.jpg")
    assert image_url("https://aliexpress-media.com.evil.test/product.jpg") is None
    assert image_url("https://user:secret@aliexpress-media.com/product.jpg") is None
    assert image_url("https://aliexpress-media.com:8443/product.jpg") is None


@pytest.mark.parametrize("site", ["US", "GLO"])
def test_observed_empty_gallery_is_visible_and_polling_does_not_retry(
    client,
    monkeypatch,
    site,
):
    # Both real probes on 2026-11-07 returned code=0 with this empty gallery.
    calls = provider(
        monkeypatch,
        {
            "site": site,
            "product_id": ITEM_ID,
            "title": "Pokemon Pokeball Transform Figure Set - Pikachu Charizard",
            "description": "Collectible Pokémon toy balls featuring "
            "Pikachu, Charizard, "
            "Venusaur, Blastoise, Mewtwo, Gyarados, Solgaleo, Lunala, and Eevee. "
            "1/6 scale PVC model, 14+ age, CE certified, perfect for fans and gifts.",
            "images": [],
        },
    )
    client.app.state.settings.justone_api_token = SecretStr("test-token")
    response = client.post(
        ROUTE + "/products",
        json={
            "url": USER_URL if site == "US" else GLO_URL,
            "platform": "aliexpress",
        },
    )
    assert response.status_code == 202
    document_id = response.json()["id"]
    for _ in range(2):
        document = client.get(ROUTE + "/documents/" + document_id).json()
        assert document["status"] == "failed"
        assert document["payload"]["error_code"] == "PRODUCT_IMAGES_MISSING"
        assert "未提供可用图片" in document["payload"]["error"]
        assert "product" not in document["payload"]
    assert len(calls) == 1


def test_source_list_and_site_specific_same_day_cache(client, monkeypatch):
    calls = provider(monkeypatch, {"product_id": ITEM_ID, "images": [IMAGE]})
    client.app.state.settings.justone_api_token = SecretStr("test-token")
    assert {"code": "aliexpress", "label": "AliExpress（速卖通）"} in client.get(
        ROUTE + "/product-platforms"
    ).json()
    us = client.post(ROUTE + "/products", json={"url": USER_URL}).json()
    repeated = client.post(ROUTE + "/products", json={"url": US_URL}).json()
    glo = client.post(ROUTE + "/products", json={"url": GLO_URL}).json()
    assert repeated["id"] == us["id"]
    assert repeated["status"] == "ready"
    assert glo["id"] != us["id"]
    assert len(calls) == 2


def test_unsupported_pinduoduo_source_remains_rejected():
    with pytest.raises(ApiError) as caught:
        parse_product_link("https://mobile.yangkeduo.com/goods.html?goods_id=123456789")
    assert caught.value.code == "UNSUPPORTED_SOURCE"


def test_returned_aliexpress_cdn_image_can_be_previewed_and_imported(
    client, monkeypatch
):
    provider(monkeypatch, {"product_id": ITEM_ID, "images": [IMAGE]})
    client.app.state.settings.justone_api_token = SecretStr("test-token")
    created = client.post(ROUTE + "/products", json={"url": USER_URL}).json()
    document_id = created["id"]
    content = BytesIO()
    Image.new("RGB", (80, 90), "blue").save(content, "PNG")
    downloads = []

    def download(url, limit):
        downloads.append(url)
        return content.getvalue()

    monkeypatch.setattr("app.replica._download", download)
    preview = client.get(ROUTE + f"/products/{document_id}/images/imageUrls/0")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content == content.getvalue()
    invalid = client.post(
        ROUTE + f"/products/{document_id}/import",
        json={"urls": [IMAGE.replace("product.jpg", "unreturned.jpg")]},
    )
    assert invalid.status_code == 400
    imported = client.post(
        ROUTE + f"/products/{document_id}/import",
        json={"urls": [IMAGE]},
    )
    assert imported.status_code == 200
    assert imported.json()[0]["role"] == "主图"
    assert imported.json()[0]["asset_id"]
    assert downloads == [IMAGE, IMAGE]
