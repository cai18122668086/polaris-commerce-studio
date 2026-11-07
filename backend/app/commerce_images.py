"""Image hosts used by the supported marketplaces, shared by preview and import."""

import html
from urllib.parse import urlparse

from .justone import domain_matches
from .justone import image_url as legacy_image_url

IMAGE_HOSTS = (
    "media-amazon.com",
    "ssl-images-amazon.com",
    "images-amazon.com",
    "ebayimg.com",
    "etsystatic.com",
    "susercontent.com",
    "shopeemobile.com",
    "kwcdn.com",
    "temucdn.com",
    "pddpic.com",
    "walmartimages.com",
    "poizon.com",
    "dewucdn.com",
    "dewu.com",
    "byteimg.com",
    "ecombdimg.com",
    "douyincdn.com",
    "pstatp.com",
    "xhscdn.com",
    "xiaohongshu.com",
)


def image_url(value: object) -> str | None:
    accepted = legacy_image_url(value)
    if accepted or not isinstance(value, str):
        return accepted
    value = html.unescape(value.strip()).replace("\\/", "/")
    if value.startswith("//"):
        value = "https:" + value
    try:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
            or parsed.path.lower().endswith(
                (".html", ".htm", ".js", ".json", ".css", ".svg")
            )
            or not domain_matches(parsed.hostname.lower(), IMAGE_HOSTS)
        ):
            return None
    except ValueError:
        return None
    return value
