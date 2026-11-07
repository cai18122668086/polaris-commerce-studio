"""Product source registry and bounded primary / backup routing."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse

from . import justone
from .errors import ApiError

SOURCE_LABELS = {
    "taobao": "淘宝",
    "tmall": "天猫",
    "1688": "1688",
    "jd": "京东",
    "aliexpress": "AliExpress（速卖通）",
    "amazon": "Amazon（亚马逊）",
    "shopee": "Shopee",
    "temu": "TEMU",
    "ebay": "eBay",
    "etsy": "Etsy",
    "walmart": "Walmart（沃尔玛）",
    "douyin": "抖音商城",
    "xiaohongshu": "小红书商城",
    "xianyu": "闲鱼",
    "dewu": "得物",
}
MARKET_HOSTS = {
    "amazon": (
        "amazon.com",
        "amazon.co.uk",
        "amazon.de",
        "amazon.fr",
        "amazon.it",
        "amazon.es",
        "amazon.co.jp",
        "amazon.ca",
        "amazon.com.au",
        "amazon.in",
        "amazon.com.br",
        "amazon.com.mx",
        "amazon.nl",
        "amazon.se",
        "amazon.pl",
        "amazon.com.be",
        "amazon.com.tr",
        "amazon.ae",
        "amazon.sa",
        "amazon.sg",
        "amazon.eg",
        "amazon.co.za",
    ),
    "shopee": (
        "shopee.co.id",
        "shopee.sg",
        "shopee.com.my",
        "shopee.co.th",
        "shopee.ph",
        "shopee.vn",
        "shopee.com.br",
        "shopee.tw",
        "shopee.com.mx",
        "shopee.com.co",
        "shopee.cl",
    ),
    "temu": ("temu.com",),
    "ebay": (
        "ebay.com",
        "ebay.co.uk",
        "ebay.de",
        "ebay.fr",
        "ebay.it",
        "ebay.es",
        "ebay.com.au",
        "ebay.ca",
        "ebay.at",
        "ebay.be",
        "ebay.ch",
        "ebay.ie",
        "ebay.nl",
        "ebay.pl",
        "ebay.com.sg",
        "ebay.com.my",
        "ebay.com.hk",
        "ebay.ph",
    ),
    "etsy": ("etsy.com",),
    "walmart": ("walmart.com",),
    "douyin": ("douyin.com", "jinritemai.com"),
    "xiaohongshu": ("xiaohongshu.com",),
    "xianyu": ("goofish.com",),
    "dewu": ("dewu.com",),
}


def parse_product_link(raw: str, platform_hint: str = "auto") -> tuple[str, str, str]:
    raw = html.unescape(raw.strip())
    match = re.search(r"https?://[^\s<>\"，]+", raw)
    if not match:
        if platform_hint in justone.ENDPOINTS or platform_hint == "auto":
            return justone.parse_product_link(raw, platform_hint)
        if platform_hint not in MARKET_HOSTS:
            raise ApiError(
                400, "UNSUPPORTED_SOURCE", "暂不支持该商品来源，请上传参考图。"
            )
        # IDs are interpreted only with an explicit source platform.
        defaults = {
            "amazon": f"https://www.amazon.com/dp/{raw}",
            "etsy": f"https://www.etsy.com/listing/{raw}",
            "ebay": f"https://www.ebay.com/itm/{raw}",
            "temu": f"https://www.temu.com/goods.html?goods_id={raw}",
            "walmart": f"https://www.walmart.com/ip/{raw}",
            "douyin": f"https://haohuo.jinritemai.com/views/product/item2?product_id={raw}",
            "xiaohongshu": f"https://www.xiaohongshu.com/goods-detail/{raw}",
            "xianyu": f"https://www.goofish.com/item?id={raw}",
            "dewu": f"https://www.dewu.com/product-detail.html?spuId={raw}",
        }
        if platform_hint not in defaults or not re.fullmatch(r"[A-Za-z0-9]+", raw):
            raise ApiError(
                400,
                "PRODUCT_ID_MISSING",
                "请使用完整商品链接；Shopee 链接需要同时包含店铺和商品 ID。",
            )
        raw = defaults[platform_hint]
        match = re.search(r"https?://[^\s<>\"，]+", raw)
    assert match is not None
    raw = match.group(0).rstrip("，。；！）)]}￥¥")
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            raise ValueError
    except ValueError:
        raise ApiError(400, "INVALID_PRODUCT_LINK", "商品链接格式无效。") from None
    if any(
        justone.domain_matches(host, domains)
        for domains in justone.MARKET_HOSTS.values()
    ):
        return justone.parse_product_link(raw, platform_hint)
    platform = next(
        (
            p
            for p, domains in MARKET_HOSTS.items()
            if justone.domain_matches(host, domains)
        ),
        "",
    )
    if not platform:
        raise ApiError(400, "UNSUPPORTED_SOURCE", "暂不支持该商品来源，请上传参考图。")
    query = parse_qs(parsed.query)
    path = parsed.path
    item_id = ""
    canonical = ""
    if platform == "amazon":
        found = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Za-z0-9]{10})(?:/|$)", path)
        if found:
            item_id = found[1].upper()
            canonical = f"https://{host}/dp/{item_id}"
    elif platform == "shopee":
        found = re.search(r"(?:-i\.|/i\.)(\d+)\.(\d+)(?:/|$)", path) or re.fullmatch(
            r"/product/(\d+)/(\d+)/?", path
        )
        if found:
            item_id = found[2]
            canonical = f"https://{host}/product-i.{found[1]}.{item_id}"
    elif platform == "ebay":
        found = re.fullmatch(r"/itm/(?:[^/]+/)?(\d{9,15})/?", path)
        if found:
            item_id = found[1]
            canonical = f"https://{host}/itm/{item_id}"
    elif platform == "etsy":
        found = re.match(r"/(?:[a-z]{2}/)?listing/(\d+)(?:/|$)", path)
        if found:
            item_id = found[1]
            canonical = f"https://www.etsy.com/listing/{item_id}"
    elif platform == "walmart":
        found = re.fullmatch(r"/ip/(?:[^/]+/)?(\d+)/?", path)
        if found:
            item_id = found[1]
            canonical = f"https://www.walmart.com/ip/{item_id}"
    elif platform == "temu":
        found = re.search(r"-g-(\d+)\.html$", path)
        item_id = (
            found[1]
            if found
            else query.get("goods_id", [""])[0]
            if path.endswith("/goods.html")
            else ""
        )
        canonical = f"https://www.temu.com/goods.html?goods_id={item_id}"
    elif platform == "douyin":
        item_id = query.get("product_id", [""])[0]
        found = re.search(r"/view/product/(\d+)(?:/|$)", path)
        if found:
            item_id = found[1]
        canonical = (
            f"https://haohuo.jinritemai.com/views/product/item2?product_id={item_id}"
        )
    elif platform == "xiaohongshu":
        found = re.fullmatch(r"/goods-detail/([a-fA-F0-9]{24})/?", path)
        if found:
            item_id = found[1].lower()
            canonical = f"https://www.xiaohongshu.com/goods-detail/{item_id}"
    elif platform == "xianyu":
        item_id = query.get("id", [""])[0] if path.rstrip("/") == "/item" else ""
        canonical = f"https://www.goofish.com/item?id={item_id}"
    elif platform == "dewu":
        item_id = (
            query.get("spuId", query.get("spu_id", [""]))[0]
            if "product" in path.lower()
            else ""
        )
        canonical = f"https://www.dewu.com/product-detail.html?spuId={item_id}"
    if not item_id or (
        platform not in {"amazon", "xiaohongshu"} and not item_id.isdigit()
    ):
        raise ApiError(
            400,
            "PRODUCT_ID_MISSING",
            "未识别出商品 ID，请使用完整商品链接，或选择来源平台后输入商品 ID。"
            "抖音商城需商品 ID，不支持推广 ID。",
        )
    return platform, item_id, canonical


def fetch_product(
    token: str, platform: str, item_id: str, canonical: str, *, everyinfra_key: str = ""
) -> dict:
    primary_error = None
    if platform == "amazon" and token:
        from .amazon_product import fetch_product as fetch_amazon

        try:
            return fetch_amazon(token, item_id, canonical)
        except ApiError as error:
            if not everyinfra_key:
                raise
            primary_error = error
    if platform in justone.ENDPOINTS and (
        platform != "aliexpress" or not everyinfra_key
    ):
        try:
            product = justone.fetch_product(token, platform, item_id, canonical)
            if (
                platform == "1688"
                and everyinfra_key
                and not product.get("descImageUrls")
            ):
                from .everyinfra import supplement_product_images

                supplement_product_images(everyinfra_key, product)
            return product
        except ApiError as error:
            if not everyinfra_key:
                raise
            primary_error = error
    if not everyinfra_key:
        raise ApiError(
            503,
            "PRODUCT_PROVIDER_NOT_CONFIGURED",
            "商品采集服务正在配置，请先上传参考图。",
        )
    from .everyinfra import fetch_product as fetch_backup

    try:
        result = fetch_backup(everyinfra_key, platform, item_id, canonical)
    except ApiError as error:
        if primary_error:
            raise ApiError(
                error.status_code,
                error.code,
                "原商品服务和备用商品服务均未获取到可用图片，请稍后重试或上传参考图。",
            ) from None
        raise
    if primary_error:
        result["fallbackFrom"] = "justoneapi"
        result["fallbackReason"] = primary_error.code
    return result
