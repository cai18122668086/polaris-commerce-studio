import json
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import SecretStr

from app.errors import ApiError
from app.justone import (
    TAOBAO_FALLBACK_ENDPOINT,
    fetch_product,
    normalize_product,
    parse_product_link,
)

ITEM_ID = "1063600240762"
CANONICAL = f"https://item.taobao.com/item.htm?id={ITEM_ID}"
AD_LINK = (
    "https://item.taobao.com/item.htm?"
    "ali_refid=a3_420860_1007%3A10353112734%3AH%3A10353112734_0_28295483766"
    "&ali_trackid=319_f0f958ef812f8763109184428df675c0"
    f"&id={ITEM_ID}&item_type=ad&mi_id=0000EOABCGMO"
    "&mm_sceneid=0_0_10353112734_0_0&skuId=6107973556141"
    "&spm=tbpc.pc_sem_alimama%2Fa.201876.d5"
)


def stub_provider(monkeypatch, replies):
    calls = []
    pending = iter(replies)

    def open_request(request, timeout):
        calls.append(request)
        return BytesIO(json.dumps(next(pending)).encode())

    monkeypatch.setattr(
        "app.justone.build_opener",
        lambda *handlers: SimpleNamespace(open=open_request),
    )
    return calls


def test_ad_link_uses_item_id_instead_of_tracking_id_or_sku():
    assert parse_product_link(AD_LINK) == ("taobao", ITEM_ID, CANONICAL)


@pytest.mark.parametrize(
    "link",
    [
        f"https://h5.m.taobao.com/awp/core/detail.htm?id={ITEM_ID}",
        f"https://m.taobao.com/i{ITEM_ID}.htm",
        f"https://m.taobao.com/share?url=https%3A%2F%2Fitem.taobao.com%2Fitem.htm%3Fid%3D{ITEM_ID}",
    ],
)
def test_mobile_product_urls_use_the_same_canonical_product(link):
    assert parse_product_link(link) == ("taobao", ITEM_ID, CANONICAL)


def test_mobile_share_page_with_script_redirect_is_parsed_without_executing_it(
    monkeypatch,
):
    class LandingPage(BytesIO):
        def geturl(self):
            return "https://e.tb.cn/h.synthetic"

    body = (
        '<script>location.href="https:\\/\\/item.taobao.com\\/item.htm?id='
        f'{ITEM_ID}"</script>'
    )
    monkeypatch.setattr(
        "app.justone.build_opener",
        lambda *args: SimpleNamespace(
            open=lambda *args, **kwargs: LandingPage(body.encode())
        ),
    )
    assert parse_product_link(
        "【淘宝】商品分享 https://e.tb.cn/h.synthetic，复制打开"
    ) == ("taobao", ITEM_ID, CANONICAL)


def test_share_page_does_not_follow_external_script_links(monkeypatch):
    class LandingPage(BytesIO):
        def geturl(self):
            return "https://e.tb.cn/h.synthetic"

    calls = []

    def open_request(request, **kwargs):
        calls.append(request.full_url)
        return LandingPage(
            b'<script>location.href="http://127.0.0.1/private?id=123456"</script>'
        )

    monkeypatch.setattr(
        "app.justone.build_opener", lambda *args: SimpleNamespace(open=open_request)
    )
    with pytest.raises(ApiError, match="商品 ID"):
        parse_product_link("https://e.tb.cn/h.synthetic")
    assert calls == ["https://e.tb.cn/h.synthetic"]


@pytest.mark.parametrize("text", ["商品不存在或已下架", "商品不存在", "商品已下架"])
def test_code_zero_with_unavailable_text_is_a_collection_failure(monkeypatch, text):
    calls = stub_provider(monkeypatch, [{"code": 0, "data": text}] * 2)
    with pytest.raises(ApiError) as caught:
        fetch_product("test-token", "taobao", ITEM_ID, CANONICAL)
    assert caught.value.status_code == 502
    assert caught.value.code == "PRODUCT_UNAVAILABLE"
    assert "采集服务" in caught.value.message
    assert "若原商品仍可打开" in caught.value.message
    assert len(calls) == 2  # At most one independent fallback; no recursive retries.
    assert parse_qs(urlparse(calls[0].full_url).query)["itemId"] == [ITEM_ID]
    assert urlparse(calls[1].full_url).path == TAOBAO_FALLBACK_ENDPOINT


@pytest.mark.parametrize("platform", ["taobao", "tmall"])
@pytest.mark.parametrize(
    "failure", [{"code": 0, "data": "商品不存在或已下架"}, {"code": 301}]
)
def test_collection_failure_in_v6_uses_v3_once(monkeypatch, platform, failure):
    calls = stub_provider(
        monkeypatch,
        [
            failure,
            {
                "code": 0,
                "data": {
                    "num_iid": ITEM_ID,
                    "title": "紫色上衣",
                    "item_imgs": [{"url": "//img.alicdn.com/main.jpg"}],
                    "desc_img": ["//img.alicdn.com/detail.jpg"],
                    "props_img": {"color:purple": "//img.alicdn.com/sku.jpg"},
                },
            },
        ],
    )
    product = fetch_product("test-token", platform, ITEM_ID, CANONICAL)
    assert product["title"] == "紫色上衣"
    assert product["endpoint"] == TAOBAO_FALLBACK_ENDPOINT
    assert product["attemptedEndpoints"] == [
        "/api/taobao/get-item-detail/v6",
        TAOBAO_FALLBACK_ENDPOINT,
    ]
    assert product["costCents"] is None
    assert product["imageUrls"] == ["https://img.alicdn.com/main.jpg"]
    assert product["descImageUrls"] == ["https://img.alicdn.com/detail.jpg"]
    assert product["skuImageUrls"] == ["https://img.alicdn.com/sku.jpg"]
    assert len(calls) == 2


@pytest.mark.parametrize("returned_id", [None, "987654321"])
@pytest.mark.parametrize(
    "failure", [{"code": 0, "data": "商品不存在或已下架"}, {"code": 301}]
)
def test_fallback_rejects_missing_or_different_product_id(
    monkeypatch, returned_id, failure
):
    calls = stub_provider(
        monkeypatch,
        [
            failure,
            {
                "code": 0,
                "data": {
                    "num_iid": returned_id,
                    "images": ["//img.alicdn.com/wrong.jpg"],
                },
            },
        ],
    )
    with pytest.raises(ApiError) as caught:
        fetch_product("test-token", "taobao", ITEM_ID, CANONICAL)
    assert caught.value.code == "PRODUCT_ID_MISMATCH"
    assert len(calls) == 2


@pytest.mark.parametrize("platform", ["1688", "jd"])
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ({"code": 0, "data": "商品不存在或已下架"}, "PRODUCT_UNAVAILABLE"),
        ({"code": 301}, "PRODUCT_PROVIDER_301"),
    ],
)
def test_other_platforms_never_use_taobao_fallback(
    monkeypatch, platform, failure, expected_code
):
    calls = stub_provider(monkeypatch, [failure])
    with pytest.raises(ApiError) as caught:
        fetch_product("test-token", platform, ITEM_ID, CANONICAL)
    assert caught.value.code == expected_code
    assert len(calls) == 1


@pytest.mark.parametrize("data", [None, [], "", 42, "private-token-and-raw-error"])
def test_invalid_product_data_has_safe_actionable_error(monkeypatch, data):
    calls = stub_provider(monkeypatch, [{"code": 0, "data": data}])
    with pytest.raises(ApiError) as caught:
        fetch_product("test-token", "taobao", ITEM_ID, CANONICAL)
    assert caught.value.code == "PRODUCT_DATA_INVALID"
    assert "上传参考图" in caught.value.message
    assert "private-token" not in caught.value.message
    assert "格式无法识别" not in caught.value.message
    assert len(calls) == 1


@pytest.mark.parametrize(
    "wire", [None, [], "unexpected response", {}, {"code": "0"}, {"code": False}]
)
def test_invalid_envelope_does_not_escape_as_attribute_error(monkeypatch, wire):
    stub_provider(monkeypatch, [wire])
    with pytest.raises(ApiError, match="未返回有效商品信息") as caught:
        fetch_product("test-token", "taobao", ITEM_ID, CANONICAL)
    assert caught.value.code == "PRODUCT_DATA_INVALID"


@pytest.mark.parametrize("code", [100, 302, 303, 400, 500, 600, 601, 602])
def test_other_provider_errors_never_trigger_fallback(monkeypatch, code):
    calls = stub_provider(monkeypatch, [{"code": code, "data": "商品不存在或已下架"}])
    with pytest.raises(ApiError) as caught:
        fetch_product("test-token", "taobao", ITEM_ID, CANONICAL)
    assert caught.value.code == f"PRODUCT_PROVIDER_{code}"
    assert len(calls) == 1


@pytest.mark.parametrize("platform", ["taobao", "tmall"])
def test_collection_failure_in_both_endpoints_stops_after_one_fallback(
    monkeypatch, platform
):
    calls = stub_provider(monkeypatch, [{"code": 301}] * 2)
    with pytest.raises(ApiError) as caught:
        fetch_product("test-token", platform, ITEM_ID, CANONICAL)
    assert caught.value.code == "PRODUCT_PROVIDER_301"
    assert [urlparse(call.full_url).path for call in calls] == [
        "/api/taobao/get-item-detail/v6",
        TAOBAO_FALLBACK_ENDPOINT,
    ]


def test_successful_v6_does_not_query_fallback(monkeypatch):
    calls = stub_provider(
        monkeypatch,
        [{"code": 0, "data": {"images": ["//img.alicdn.com/main.jpg"]}}],
    )
    product = fetch_product("test-token", "taobao", ITEM_ID, CANONICAL)
    assert product["endpoint"] == "/api/taobao/get-item-detail/v6"
    assert product["costCents"] == 25
    assert "attemptedEndpoints" not in product
    assert len(calls) == 1


def test_valid_product_still_normalizes_image_groups():
    product = normalize_product(
        {
            "item": {
                "title": "保温杯",
                "images": ["//img.alicdn.com/main.jpg"],
                "desc": '<img src="//img.alicdn.com/detail.jpg">',
                "sku": {"images": ["//img.alicdn.com/sku.jpg"]},
            }
        },
        "taobao",
        ITEM_ID,
        CANONICAL,
    )
    assert product["title"] == "保温杯"
    assert product["imageUrls"] == ["https://img.alicdn.com/main.jpg"]
    assert product["descImageUrls"] == ["https://img.alicdn.com/detail.jpg"]
    assert product["skuImageUrls"] == ["https://img.alicdn.com/sku.jpg"]


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ({"code": 0, "data": "商品不存在或已下架"}, "PRODUCT_UNAVAILABLE"),
        ({"code": 301}, "PRODUCT_PROVIDER_301"),
    ],
)
def test_failed_product_is_visible_and_only_explicit_retry_queries_again(
    client, monkeypatch, failure, expected_code
):
    calls = stub_provider(
        monkeypatch,
        [
            failure,
            failure,
            {
                "code": 0,
                "data": {
                    "item": {
                        "title": "恢复的商品",
                        "images": ["https://img.alicdn.com/main.jpg"],
                    }
                },
            },
        ],
    )
    client.app.state.settings.justone_api_token = SecretStr("test-token")
    route = "/api/v1/workspaces/ws_test/replica"
    created = client.post(route + "/products", json={"url": AD_LINK})
    assert created.status_code == 202
    document_id = created.json()["id"]
    for _ in range(3):
        failed = client.get(route + "/documents/" + document_id).json()
        assert failed["status"] == "failed"
        assert failed["payload"]["error_code"] == expected_code
        assert "上传参考图" in failed["payload"]["error"]
        assert "product" not in failed["payload"]
    assert len(calls) == 2
    retried = client.post(route + "/products", json={"url": CANONICAL})
    assert retried.status_code == 202
    assert retried.json()["id"] == document_id
    ready = client.get(route + "/documents/" + document_id).json()
    assert ready["status"] == "ready"
    assert ready["payload"]["product"]["title"] == "恢复的商品"
    assert "error_code" not in ready["payload"]
    assert len(calls) == 3
    client.post(route + "/products", json={"url": AD_LINK})
    assert len(calls) == 3  # Successful same-day cache remains in use.


@pytest.mark.parametrize(
    "failure", [{"code": 0, "data": "商品不存在或已下架"}, {"code": 301}]
)
def test_fallback_product_is_cached_without_requery(client, monkeypatch, failure):
    calls = stub_provider(
        monkeypatch,
        [
            failure,
            {
                "code": 0,
                "data": {
                    "num_iid": ITEM_ID,
                    "title": "紫色上衣",
                    "item_imgs": [{"url": "//img.alicdn.com/main.jpg"}],
                },
            },
        ],
    )
    client.app.state.settings.justone_api_token = SecretStr("test-token")
    route = "/api/v1/workspaces/ws_test/replica"
    created = client.post(route + "/products", json={"url": AD_LINK})
    assert created.status_code == 202
    document_id = created.json()["id"]
    ready = client.get(route + "/documents/" + document_id).json()
    assert ready["status"] == "ready"
    assert ready["payload"]["product"]["endpoint"] == TAOBAO_FALLBACK_ENDPOINT
    assert ready["payload"]["product"]["sourceUrl"] == CANONICAL
    cached = client.post(route + "/products", json={"url": CANONICAL})
    assert cached.json()["id"] == document_id
    assert cached.json()["status"] == "ready"
    assert len(calls) == 2
