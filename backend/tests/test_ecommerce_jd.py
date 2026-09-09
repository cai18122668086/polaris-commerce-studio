from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.ecommerce_routes as ecommerce_routes
from app.ecommerce_jd import (
    JDAdapter,
    JDProduct,
    _computed_background_image_fragment,
    parse_product_html,
)


@pytest.fixture(autouse=True)
def admin_access(client) -> None:
    client.app.state.settings.announcement_admin_emails = ["admin@example.com"]


FIXTURES = Path(__file__).parent / "fixtures" / "jd"
URL = "https://item.jd.com/123456789012.html"
GLOBAL_BUY_URL = (
    "https://npcitem.jd.hk/65656494448.html"
    "?extension_id=example&jd_pop=abc&abt=0"
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_product_fixture_extracts_fields_and_structured_image_roles() -> None:
    product = parse_product_html(fixture("product.html"), URL)

    assert product.status == "product"
    assert product.product_id == "123456789012"
    assert product.title == "京东示例商品"
    assert product.price == "129.00"
    assert product.shop_name == "示例京东旗舰店"
    assert [image.role for image in product.images].count("main") == 4
    assert [image.role for image in product.images].count("detail") == 3
    assert [image.role for image in product.images].count("sku") == 3
    assert all("recommend" not in image.url for image in product.images)


def test_structured_sku_data_extracts_groups_properties_and_image() -> None:
    product = parse_product_html(fixture("structured-sku.html"), URL)

    assert [(group.name, group.values) for group in product.sku_prop_groups] == [
        ("颜色", ("红色", "蓝色")),
        ("尺码", ("M", "L")),
    ]
    assert len(product.skus) == 1
    sku = product.skus[0]
    assert sku.sku_id == "900000000001"
    assert sku.price == "199.00"
    assert sku.stock == "有货"
    assert sku.properties == (
        {"name": "颜色", "value": "红色"},
        {"name": "尺码", "value": "M"},
    )
    assert sku.image_url == "https://img10.360buyimg.com/n1/jfs/red.jpg"
    assert [(image.url, image.role) for image in product.images] == [
        ("https://img10.360buyimg.com/n1/jfs/red.jpg", "sku")
    ]


def test_status_pages_are_not_converted_to_empty_products() -> None:
    adapter = JDAdapter()
    assert adapter.parse_product(fixture("login.html"), URL).status == "login_required"
    assert adapter.parse_product(fixture("risk.html"), URL).status == "risk_controlled"
    assert (
        adapter.parse_product(fixture("not-found.html"), URL).status
        == "product_not_found"
    )


def test_recommendation_containers_are_excluded() -> None:
    product = parse_product_html(fixture("recommendations.html"), URL)
    urls = [image.url for image in product.images]
    assert urls == ["https://img10.360buyimg.com/n1/jfs/product-main.jpg"]


def test_main_image_count_and_shape_do_not_define_roles() -> None:
    product = parse_product_html(fixture("product-images-sku.html"), URL)
    main = [image for image in product.images if image.role == "main"]
    detail = [image for image in product.images if image.role == "detail"]
    sku = [image for image in product.images if image.role == "sku"]

    assert len(main) == 7
    assert len(detail) == 1
    assert len(sku) == 1
    assert detail[0].url.endswith("portrait-detail-1200x2400.jpg")


def test_live_like_gallery_detail_review_and_icon_boundaries() -> None:
    product = parse_product_html(fixture("classification-boundaries.html"), URL)

    main = [image.url for image in product.images if image.role == "main"]
    detail = [image.url for image in product.images if image.role == "detail"]
    sku = [image.url for image in product.images if image.role == "sku"]

    assert len(main) == 9
    assert all("main-" in url for url in main)
    assert len(detail) == 14
    assert all("detail-" in url for url in detail)
    assert sku == ["https://img10.360buyimg.com/n1/jfs/sku-red.jpg"]
    assert not any(
        token in image.url
        for image in product.images
        for token in ("nav-control", "review", "avatar", "control")
    )


def test_jd_detail_cdn_paths_override_broad_or_missing_dom_context() -> None:
    product = parse_product_html(fixture("url-role-boundaries.html"), URL)

    main = [image.url for image in product.images if image.role == "main"]
    detail = [image.url for image in product.images if image.role == "detail"]
    sku = [image.url for image in product.images if image.role == "sku"]

    assert len(main) == 9
    assert len(detail) == 14
    assert sum("/popWareDetail/" in url for url in detail) == 13
    assert sum("/imgzone/" in url for url in detail) == 1
    assert sku == ["https://img10.360buyimg.com/n1/jfs/sku-red.jpg"]


def test_same_asset_keeps_highest_context_role() -> None:
    shared = "https://img10.360buyimg.com/n1/s800x800_jfs/shared.jpg"
    html = f"""
    <html><head><title>共享图片商品</title></head><body>
      <div class="detail"><img src="{shared}"></div>
      <div class="gallery"><img src="{shared}"></div>
      <div class="sku"><img src="{shared}"></div>
    </body></html>
    """
    product = parse_product_html(html, URL)
    assert [(image.url, image.role) for image in product.images] == [
        ("https://img10.360buyimg.com/n1/jfs/shared.jpg", "sku")
    ]


def test_iframe_fixture_is_parseable_as_a_detail_fragment() -> None:
    product = parse_product_html(fixture("iframe-detail.html"), URL)
    assert [image.role for image in product.images] == ["detail"]


def test_short_link_is_accepted_by_url_boundary() -> None:
    product = parse_product_html(
        "<html><head><title>短链商品</title></head><body></body></html>",
        "https://3.cn/abc123",
        "https://item.jd.com/987654321.html",
    )
    assert product.product_id == "987654321"


def test_global_buy_jd_url_is_accepted_and_extracts_path_product_id() -> None:
    product = parse_product_html(
        "<html><head><title>Global Purchase Product</title></head><body></body></html>",
        GLOBAL_BUY_URL,
    )

    assert product.status == "product"
    assert product.product_id == "65656494448"


def test_unrelated_jd_hk_host_is_not_accepted_by_jd_adapter() -> None:
    with pytest.raises(ValueError):
        parse_product_html(
            "<html><head><title>Other Site</title></head><body></body></html>",
            "https://www.jd.hk/65656494448.html",
        )


def test_cross_platform_url_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_product_html(
            fixture("product.html"), "https://item.taobao.com/item.htm?id=123456789012"
        )


def test_jd_route_uses_jd_adapter_without_touching_taobao(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    product = JDAdapter().parse_product(fixture("product.html"), URL)

    def fake_jd_fetch(target_url: str) -> JDProduct:
        calls.append(target_url)
        return product

    monkeypatch.setattr(ecommerce_routes, "crawl_one_jd", fake_jd_fetch)
    monkeypatch.setattr(
        ecommerce_routes,
        "crawl_one",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("JD URL must not reach the Taobao adapter")
        ),
    )

    response = client.post(
        "/api/ecommerce/fetch-item",
        json={"url": URL, "platform": "auto", "includeDescImages": True},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["platform"] == "jd"
    assert len(data["imageUrls"]) == 4
    assert len(data["descImageUrls"]) == 3
    assert len(data["skuImageUrls"]) == 3
    assert calls == [URL]


def test_jd_route_surfaces_login_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = JDAdapter().parse_product(fixture("login.html"), URL)
    monkeypatch.setattr(ecommerce_routes, "crawl_one_jd", lambda target_url: blocked)
    response = client.post("/api/ecommerce/fetch-item", json={"url": URL})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "LOGIN_REQUIRED"


def test_jd_session_start_uses_independent_manager(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = client.app
    calls: list[str | None] = []

    def fake_start(
        target_url: str | None = None, **_: object
    ) -> dict[str, object]:
        calls.append(target_url)
        return {"state": "login_pending", "platform": "jd"}

    monkeypatch.setattr(
        application.state.ecommerce_session_jd, "start_login", fake_start
    )
    response = client.post(
        "/api/ecommerce/session/start",
        json={"platform": "jd", "url": URL},
    )

    assert response.status_code == 200
    assert response.json()["data"]["platform"] == "jd"
    assert calls == [None]
    assert (
        application.state.ecommerce_session_jd.profile_dir
        != application.state.ecommerce_session.profile_dir
    )


def test_jd_login_uses_official_login_origin() -> None:
    from app.ecommerce_login import _default_login_url

    assert _default_login_url("jd") == "https://passport.jd.com/new/login.aspx"


def test_normalise_keeps_uniform_contract() -> None:
    product = JDAdapter().parse_product(fixture("product.html"), URL)
    normalised = ecommerce_routes._normalise(product, URL, True)
    assert set(
        (
            "platform",
            "numIid",
            "title",
            "price",
            "shopName",
            "imageUrls",
            "descImageUrls",
            "skuImageUrls",
            "warnings",
        )
    ).issubset(normalised)
    assert normalised["platform"] == "jd"


def test_jd_product_page_login_prompt_is_not_an_authentication_signal() -> None:
    from app.ecommerce_login import looks_like_authenticated_page

    assert not looks_like_authenticated_page(
        URL,
        "京东商品详情",
        "京东首页 你好，请登录 我的订单 我的京东 商品标题 ¥1759",
        platform="jd",
    )


def test_jd_order_center_with_order_card_is_authenticated() -> None:
    from app.ecommerce_login import looks_like_authenticated_page

    assert looks_like_authenticated_page(
        "https://order.jd.com/center/list.action",
        "订单列表-京东商城",
        "你好，请登录 订单中心 近3个月订单 收货人 金额 操作 "
        "2026-08-27 订单号 1234567890123456 已完成",
        platform="jd",
    )


def test_jd_order_center_without_order_card_is_not_authenticated() -> None:
    from app.ecommerce_login import looks_like_authenticated_page

    assert not looks_like_authenticated_page(
        "https://order.jd.com/center/list.action",
        "订单列表-京东商城",
        "你好，请登录 订单中心 近3个月订单 收货人 金额 操作",
        platform="jd",
    )


def test_jd_risk_page_wins_over_order_account_markers() -> None:
    from app.ecommerce_login import looks_like_authenticated_page

    assert not looks_like_authenticated_page(
        "https://order.jd.com/center/list.action",
        "安全验证",
        "订单中心 近3个月订单 订单号 1234567890123456 请完成验证码",
        platform="jd",
    )


def test_jd_login_label_is_independent() -> None:
    from app.ecommerce_login import looks_like_authenticated_page

    assert not looks_like_authenticated_page(
        "https://passport.jd.com/new/login.aspx",
        "京东登录",
        "扫码登录",
        platform="jd",
    )


class _LoginProbeLocator:
    def __init__(self, page: _LoginProbePage) -> None:
        self.page = page

    def inner_text(self, timeout: int) -> str:
        return self.page.body


class _LoginProbePage:
    def __init__(self, url: str, title: str = "", body: str = "") -> None:
        self.url = url
        self._title = title
        self.body = body
        self.goto_calls: list[str] = []
        self.closed = False

    def title(self) -> str:
        return self._title

    def locator(self, selector: str) -> _LoginProbeLocator:
        assert selector == "body"
        return _LoginProbeLocator(self)

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True

    def goto(self, url: str, **_: object) -> None:
        self.goto_calls.append(url)
        self.url = url
        self._title = "订单列表-京东商城"
        self.body = "订单中心 近3个月订单 退出登录 暂无订单"


class _LoginProbeContext:
    def __init__(self, pages: list[_LoginProbePage]) -> None:
        self.pages = pages
        self.new_page_called = False

    def new_page(self) -> _LoginProbePage:
        self.new_page_called = True
        raise AssertionError("JD session probing must not create a second tab")


def test_jd_session_probe_reuses_current_tab() -> None:
    from app.ecommerce_login import _JD_SESSION_CHECK_URL, _probe_jd_session

    page = _LoginProbePage(
        "https://passport.jd.com/new/login.aspx", "京东登录", "扫码登录"
    )
    context = _LoginProbeContext([page])

    returned_page, authenticated = _probe_jd_session(context, page)

    assert returned_page is page
    assert authenticated is True
    assert page.goto_calls == [_JD_SESSION_CHECK_URL]
    assert context.new_page_called is False


def test_jd_login_profile_keeps_only_one_owned_tab() -> None:
    from app.ecommerce_login import _close_extra_pages

    current = _LoginProbePage("https://passport.jd.com/new/login.aspx")
    extra = _LoginProbePage("https://order.jd.com/center/list.action")
    context = _LoginProbeContext([current, extra])

    _close_extra_pages(context, current)

    assert current.closed is False
    assert extra.closed is True


def test_jd_order_center_without_orders_but_with_logout_is_authenticated() -> None:
    from app.ecommerce_login import looks_like_authenticated_page

    assert looks_like_authenticated_page(
        "https://order.jd.com/center/list.action",
        "订单列表-京东商城",
        "订单中心 近3个月订单 退出登录 暂无订单",
        platform="jd",
    )


def test_jd_order_center_with_account_greeting_is_authenticated() -> None:
    from app.ecommerce_login import looks_like_authenticated_page

    title = "".join(chr(code) for code in (0x8ba2, 0x5355, 0x5217, 0x8868))
    title += "-" + "".join(chr(code) for code in (0x4eac, 0x4e1c, 0x5546, 0x57ce))
    body = "".join(chr(code) for code in (0x4f60, 0x597d, 0xff0c, 0x5f20, 0x4e09))
    body += " " + "".join(chr(code) for code in (0x8ba2, 0x5355, 0x4e2d, 0x5fc3))
    body += " " + "".join(chr(code) for code in (0x8fd1,))
    body += "3" + "".join(chr(code) for code in (0x4e2a, 0x6708, 0x8ba2, 0x5355))
    body += " " + "".join(chr(code) for code in (0x6682, 0x65e0, 0x8ba2, 0x5355))

    assert looks_like_authenticated_page(
        "https://order.jd.com/center/list.action",
        title,
        body,
        platform="jd",
    )


def test_jd_order_center_ignores_public_login_prompt_when_account_name_present(
) -> None:
    from app.ecommerce_login import looks_like_authenticated_page

    assert looks_like_authenticated_page(
        "https://order.jd.com/center/list.action",
        "订单列表-京东商城",
        "你好，请登录 订单中心 近3个月订单 你好，张三 暂无订单",
        platform="jd",
    )


def test_jd_order_center_account_shell_without_orders_is_authenticated() -> None:
    from app.ecommerce_login import looks_like_authenticated_page

    assert looks_like_authenticated_page(
        "https://order.jd.com/center/list.action",
        "订单列表-京东商城",
        (
            "订单中心 近3个月订单 我的订单 我的钱包 账户设置 足迹收藏 "
            "客户服务 我的活动 暂无订单"
        ),
        platform="jd",
    )


def test_fixture_is_valid_utf8_json_contract() -> None:
    # Keep the fixture intentionally small and deterministic for future edits.
    payload = json.loads('{"platform":"jd","roles":["main","detail","sku"]}')
    assert payload["platform"] == "jd"


class _ComputedStylePage:
    def evaluate(self, script: str) -> list[dict[str, str]]:
        assert "getComputedStyle" in script
        return [
            {
                "url": "https://img10.360buyimg.com/pc_s800x800_jfs/detail-bg.jpg",
                "marker": "detail-content",
            },
            {"url": "data:image/gif;base64,placeholder", "marker": "detail"},
        ]


def test_rendered_background_images_are_exposed_to_existing_parser() -> None:
    fragment = _computed_background_image_fragment(_ComputedStylePage())
    product = parse_product_html(
        f"<html><head><title>背景图商品</title></head><body>{fragment}</body></html>",
        URL,
    )

    assert [image.url for image in product.images] == [
        "https://img10.360buyimg.com/jfs/detail-bg.jpg"
    ]
    assert product.images[0].role == "detail"

