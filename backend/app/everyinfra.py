"""EveryInfra product data, with marketplace identity and image validation."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .commerce_images import image_url
from .errors import ApiError

API_URL = "https://api.everyinfra.com/api/v1/social"
# platform -> (upstream platform, action, parameter, returned identity field).
PRODUCT_ROUTES = {
    "taobao": ("taobao", "product_detail", "url", "id"),
    "tmall": ("taobao", "product_detail", "url", "id"),
    "1688": ("alibaba1688", "product_detail", "url", "id"),
    "jd": ("jd", "product_detail", "item_id", "item_id"),
    "aliexpress": ("aliexpress", "product_detail", "url", "id"),
    "amazon": ("amazon", "profile", "url", "asin"),
    "ebay": ("ebay", "product_detail", "url", "item_id"),
    "etsy": ("etsy", "profile", "url", "listing_id"),
    "shopee": ("shopee", "profile", "url", "item_id"),
    "temu": ("temu", "profile", "url", "product_id"),
    "walmart": ("walmart", "profile", "url", "item_id"),
    "douyin": ("douyin", "product_detail", "product_id", "product_id"),
    "xiaohongshu": ("xiaohongshu", "product_detail", "product_id", "id"),
    "xianyu": ("xianyu", "item_detail", "urls", "item_id"),
    "dewu": ("dewu", "product_summary", "url", "spu_id"),
}


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        # Never forward the service credential to another origin.
        raise ApiError(
            502,
            "PRODUCT_PROVIDER_UNAVAILABLE",
            "备用商品服务连接异常，请稍后重试或上传参考图。",
        )


def _request(key: str, platform: str, action: str, params: dict) -> dict:
    request = Request(
        API_URL,
        data=json.dumps(
            {"platform": platform, "action": action, "params": params}
        ).encode(),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Polaris/1.0",
        },
        method="POST",
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirects()).open(
            request, timeout=150
        ) as response:
            wire = json.loads(response.read(16 * 1024 * 1024))
    except HTTPError as error:
        messages = {
            401: "备用商品服务凭证失效，请联系管理员。",
            402: "备用商品服务余额不足，请联系管理员。",
            403: "备用商品接口未开通，请联系管理员。",
            422: "备用商品服务未识别该商品，请检查链接或上传参考图。",
            429: "备用商品服务繁忙，请稍后重试。",
        }
        raise ApiError(
            502,
            f"EVERYINFRA_{error.code}",
            messages.get(
                error.code, "备用商品服务暂时不可用，请稍后重试或上传参考图。"
            ),
        ) from None
    except (URLError, TimeoutError, ValueError):
        raise ApiError(
            502,
            "PRODUCT_PROVIDER_UNAVAILABLE",
            "备用商品服务暂时无法连接，请稍后重试或上传参考图。",
        ) from None
    if not isinstance(wire, Mapping) or wire.get("error") or "results" not in wire:
        raise ApiError(
            502,
            "PRODUCT_DATA_INVALID",
            "备用商品服务未返回有效商品信息，请稍后重试或上传参考图。",
        )
    return dict(wire)


def _images(value: object) -> list[str]:
    candidates = []
    if isinstance(value, str):
        candidates = re.findall(r"(?:https?:)?//[^\s\"'<>]+", html.unescape(value))
    elif isinstance(value, Mapping):
        for child in value.values():
            candidates.extend(_images(child))
    elif isinstance(value, list):
        for child in value:
            candidates.extend(_images(child))
    return list(dict.fromkeys(url for raw in candidates if (url := image_url(raw))))[
        :120
    ]


def normalize_product(
    wire: dict,
    platform: str,
    item_id: str,
    canonical: str,
    *,
    action: str | None = None,
) -> dict:
    upstream, default_action, _, identity = PRODUCT_ROUTES[platform]
    action = action or default_action
    if action == "product_detail" and platform in {"walmart", "shopee", "etsy"}:
        identity = "id"
    data = wire.get("results")
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, Mapping) or not data:
        raise ApiError(
            502,
            "PRODUCT_DATA_INVALID",
            "备用商品服务未获取到该商品，请检查链接或上传参考图。",
        )
    if str(data.get(identity, "")).casefold() != item_id.casefold():
        raise ApiError(
            502,
            "PRODUCT_ID_MISMATCH",
            "备用商品服务返回的商品与链接不一致，请上传参考图或稍后重试。",
        )
    returned_platform = data.get("platform", wire.get("platform"))
    accepted_platforms = {upstream, "1688"} if platform == "1688" else {upstream}
    if returned_platform and returned_platform not in accepted_platforms:
        raise ApiError(
            502,
            "PRODUCT_ID_MISMATCH",
            "备用商品服务返回的平台与链接不一致，请上传参考图或稍后重试。",
        )
    # Read only product image fields. Reviews, seller avatars, shop galleries,
    # recommendations and ads must never become product references.
    main = _images(
        [
            data.get(k)
            for k in (
                "images",
                "image_urls",
                "main_image_urls",
                "main_image_url",
                "image_url",
            )
        ]
    )
    detail = _images(
        [
            data.get(k)
            for k in ("description_images", "detail_image_urls", "description_html")
        ]
    )
    sku_fields: tuple[str, ...] = ("variants", "skus", "props_images")
    if platform == "temu":
        sku_fields += ("options",)
    sku = _images([data.get(k) for k in sku_fields])
    if not main and not detail:
        raise ApiError(
            502,
            "PRODUCT_IMAGES_MISSING",
            "商品信息已返回，但备用采集服务未提供可用图片；请上传参考图或更换商品链接。",
        )
    billing = wire.get("billing") or {}
    cost_usd = billing.get("charged_usd") if isinstance(billing, Mapping) else None
    return {
        "platform": platform,
        "targetPlatform": "amazon-us" if platform == "amazon" else platform,
        "numIid": item_id,
        "sourceUrl": canonical,
        "title": str(data.get("title") or data.get("name") or "")[:500] or None,
        "price": data.get("price", data.get("price_min", data.get("price_cny"))),
        "shopName": data.get(
            "shop_name", data.get("store_name", data.get("supplier_name"))
        ),
        "imageUrls": main,
        "descImageUrls": detail,
        "skuImageUrls": sku,
        "supplier": "everyinfra",
        "endpoint": "/api/v1/social",
        "capability": f"{upstream}.{action}",
        "costCents": None,
        "costUsd": cost_usd,
        "providerRequestId": wire.get("id"),
    }


def fetch_product(key: str, platform: str, item_id: str, canonical: str) -> dict:
    if not key:
        raise ApiError(
            503,
            "PRODUCT_PROVIDER_NOT_CONFIGURED",
            "备用商品服务正在配置，请先上传参考图。",
        )
    upstream, action, parameter, _ = PRODUCT_ROUTES[platform]
    value = (
        item_id
        if parameter in {"item_id", "product_id"}
        else [canonical]
        if parameter == "urls"
        else canonical
    )
    try:
        wire = _request(key, upstream, action, {parameter: value})
        product = normalize_product(wire, platform, item_id, canonical)
    except ApiError as error:
        # Walmart's profile can contain only text, while product_detail has the
        # same listing's image. Do not replace identity or authentication errors.
        if platform != "walmart" or error.code != "PRODUCT_IMAGES_MISSING":
            raise
        wire = _request(key, upstream, "product_detail", {"url": canonical})
        return normalize_product(
            wire, platform, item_id, canonical, action="product_detail"
        )
    supplement_product_images(key, product)
    return product


def supplement_product_images(key: str, product: dict) -> None:
    """Fill verified missing groups once, retaining usable product data on failure."""
    platform = product["platform"]
    item_id = product["numIid"]
    canonical = product["sourceUrl"]
    if platform == "jd" and not product["descImageUrls"]:
        action, params, group = (
            "description_images",
            {"item_id": item_id},
            "descImageUrls",
        )
    elif platform == "shopee" and not product["skuImageUrls"]:
        action, params, group = "product_detail", {"url": canonical}, "skuImageUrls"
    elif platform == "1688" and not product["descImageUrls"]:
        action, params, group = "product_detail", {"url": canonical}, "descImageUrls"
    else:
        return
    upstream = PRODUCT_ROUTES[platform][0]
    try:
        wire = _request(key, upstream, action, params)
        if platform == "jd":
            rows = wire["results"]
            if not isinstance(rows, list) or any(
                not isinstance(row, Mapping)
                or str(row.get("item_id", "")) != item_id
                or row.get("platform", "jd") != "jd"
                for row in rows
            ):
                raise ApiError(502, "PRODUCT_ID_MISMATCH", "详情图商品身份不一致。")
            images = _images([row.get("image_url") for row in rows])
        else:
            images = normalize_product(
                wire, platform, item_id, canonical, action=action
            )[group]
        product[group] = images
        billing = wire.get("billing") or {}
        cost = billing.get("charged_usd") if isinstance(billing, Mapping) else None
        product.setdefault("imageSupplements", []).append(
            {
                "supplier": "everyinfra",
                "capability": f"{upstream}.{action}",
                "costUsd": cost,
            }
        )
        if product.get("supplier") == "everyinfra":
            prior = product.get("costUsd")
            product["costUsd"] = (
                prior + cost if prior is not None and cost is not None else None
            )
    except ApiError as error:
        product.setdefault("imageFetchWarnings", []).append(
            {"group": group, "code": error.code}
        )
