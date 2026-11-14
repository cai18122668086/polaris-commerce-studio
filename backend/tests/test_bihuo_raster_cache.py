"""Pure glyph reuse must preserve pixels, isolation and the memory ceiling."""

import sys
from types import ModuleType

from PIL import Image, ImageDraw

from app.bihuo_suite.raster_cache import RasterCache, native_raster_cache


def test_cached_glyphs_are_pixel_identical_and_do_not_share_mutations():
    calls = []

    def raster(text, color):
        calls.append(text)
        image = Image.new("RGBA", (120, 48))
        ImageDraw.Draw(image).text((5, 5), text, fill=tuple(color))
        return image, (1, 2, 3, 4), 16

    cache = RasterCache()
    wrapped = cache.wrap(raster)
    first = wrapped("caption", [20, 90, 230, 255])
    pixels = first[0].tobytes()
    first[0].putalpha(0)
    second = wrapped("caption", [20, 90, 230, 255])
    assert second[0].tobytes() == pixels
    assert second[1:] == first[1:]
    assert second[0] is not first[0]
    assert calls == ["caption"]
    assert cache.hits == 1


def test_lru_eviction_and_oversized_rasters_remain_bounded():
    def raster(size):
        return Image.new("RGBA", (size, size)), (0, 0, size, size), 16

    cache = RasterCache(max_bytes=400)
    wrapped = cache.wrap(raster)
    wrapped(10)
    wrapped(11)
    assert cache.bytes == 400
    wrapped(9)
    assert cache.bytes == 324
    assert len(cache.items) == 1
    wrapped(10)
    assert cache.bytes == 400
    assert cache.misses == 4


def test_scoped_aliases_are_restored_even_when_rendering_fails(monkeypatch):
    root = ModuleType("test_native_suite")
    pilot = ModuleType(root.__name__ + ".vendor.pilot")
    other = ModuleType("unrelated_native_suite.vendor.pilot")

    def text_image(text):
        return Image.new("RGBA", (2, 2)), (0, 0, 2, 2), 16

    text_image.__module__ = pilot.__name__
    for module in (root, pilot, other):
        module.text_image = text_image
        monkeypatch.setitem(sys.modules, module.__name__, module)
    try:
        with native_raster_cache(root) as cache:
            assert root.text_image is pilot.text_image
            assert root.text_image is not text_image
            assert other.text_image is text_image
            root.text_image("same")
            pilot.text_image("same")
            assert cache.hits == 1
            raise RuntimeError("encoder stopped")
    except RuntimeError:
        pass
    assert root.text_image is pilot.text_image is text_image
    assert cache.bytes == 0
