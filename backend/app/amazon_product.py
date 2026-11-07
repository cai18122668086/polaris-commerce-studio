"""Amazon image groups from the existing JustOne account, with strict identity."""

import json
from collections.abc import Mapping
from urllib.parse import urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener

from .errors import ApiError
from .everyinfra import NoRedirects, _images

ENDPOINT = "/api/amazon/get-product-detail/v1"
COUNTRIES = {
    "com": "US",
    "co.uk": "GB",
    "de": "DE",
    "fr": "FR",
    "it": "IT",
    "es": "ES",
    "co.jp": "JP",
    "ca": "CA",
    "com.au": "AU",
    "in": "IN",
    "com.br": "BR",
    "com.mx": "MX",
    "nl": "NL",
    "se": "SE",
    "pl": "PL",
    "com.be": "BE",
    "com.tr": "TR",
    "ae": "AE",
    "sa": "SA",
    "sg": "SG",
    "eg": "EG",
    "co.za": "ZA",
}


def country_for(canonical: str) -> str:
    host = (urlparse(canonical).hostname or "").removeprefix("www.")
    return COUNTRIES[host.removeprefix("amazon.")]


def normalize_product(wire: dict, item_id: str, canonical: str) -> dict:
    if type(wire.get("code")) is not int or wire.get("code") != 0:
        raise ApiError(
            502, "PRODUCT_PROVIDER_UNAVAILABLE", "商品服务暂时无法读取该商品。"
        )
    data = wire.get("data")
    if (
        not isinstance(data, Mapping)
        or str(data.get("asin", "")).upper() != item_id.upper()
        or data.get("country", country_for(canonical)) != country_for(canonical)
        or data.get("landing_asin", item_id) != item_id
    ):
        raise ApiError(
            502, "PRODUCT_ID_MISMATCH", "商品服务返回的商品或市场与链接不一致。"
        )
    main = _images([data.get("product_photos"), data.get("product_photo")])
    detail = _images(data.get("aplus_images"))
    variations = data.get("product_variations")
    sku = []
    if isinstance(variations, Mapping):
        sku = _images(
            [
                row.get("photo")
                for rows in variations.values()
                if isinstance(rows, list)
                for row in rows
                if isinstance(row, Mapping)
            ]
        )
    if not main and not detail:
        raise ApiError(502, "PRODUCT_IMAGES_MISSING", "商品服务未返回可用图片。")
    return {
        "platform": "amazon",
        "targetPlatform": "amazon-us",
        "numIid": item_id,
        "sourceUrl": canonical,
        "title": str(data.get("product_title") or "")[:500] or None,
        "price": data.get("product_price"),
        "shopName": data.get("product_byline"),
        "imageUrls": main,
        "descImageUrls": detail,
        "skuImageUrls": sku,
        "supplier": "justoneapi",
        "endpoint": ENDPOINT,
        "costCents": None,
    }


def fetch_product(token: str, item_id: str, canonical: str) -> dict:
    params = {"token": token, "asin": item_id, "country": country_for(canonical)}
    try:
        with build_opener(ProxyHandler({}), NoRedirects()).open(
            Request(
                "https://api.justoneapi.com" + ENDPOINT + "?" + urlencode(params),
                headers={"Accept": "application/json", "User-Agent": "Polaris/1.0"},
            ),
            timeout=120,
        ) as response:
            wire = json.loads(response.read(16 * 1024 * 1024))
    except Exception:
        # Never expose the request URL, which contains the existing API token.
        raise ApiError(
            502, "PRODUCT_PROVIDER_UNAVAILABLE", "商品服务暂时无法连接。"
        ) from None
    if not isinstance(wire, dict):
        raise ApiError(502, "PRODUCT_DATA_INVALID", "商品服务未返回有效商品信息。")
    return normalize_product(wire, item_id, canonical)
