"""Bounded, render-local reuse of pure native glyph rasters.

Only the established pilot.text_image helper is eligible. Every returned image
is a copy, so later alpha/blur operations cannot alter another frame's glyphs.
No frame, person, material, clock, font selection or layout is cached here.
"""

from __future__ import annotations

import sys
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from types import ModuleType
from typing import Any

from PIL import Image


def _key(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return tuple(_key(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _key(item)) for key, item in value.items()))
    hash(value)
    return value


class RasterCache:
    def __init__(self, max_bytes: int = 32 * 1024 * 1024) -> None:
        self.max_bytes = max_bytes
        self.bytes = 0
        self.hits = 0
        self.misses = 0
        self.items: OrderedDict[Any, tuple[Any, int]] = OrderedDict()

    def wrap(self, function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def cached(*args: Any, **kwargs: Any) -> Any:
            try:
                key = (function, _key(args), _key(kwargs))
            except TypeError:
                return function(*args, **kwargs)
            if key in self.items:
                value, size = self.items.pop(key)
                self.items[key] = (value, size)
                self.hits += 1
            else:
                self.misses += 1
                value = function(*args, **kwargs)
                if not (
                    isinstance(value, tuple)
                    and len(value) == 3
                    and isinstance(value[0], Image.Image)
                ):
                    return value
                size = value[0].width * value[0].height * len(value[0].getbands())
                if size > self.max_bytes:
                    return value
                while self.items and self.bytes + size > self.max_bytes:
                    _, (_, evicted) = self.items.popitem(last=False)
                    self.bytes -= evicted
                # Keep our own image even when the helper itself has a cache.
                value = (value[0].copy(), *value[1:])
                self.items[key] = (value, size)
                self.bytes += size
            return (value[0].copy(), *value[1:])

        return cached


@contextmanager
def native_raster_cache(module: ModuleType) -> Iterator[RasterCache]:
    cache = RasterCache()
    prefix = module.__name__ + "."
    modules = [
        item
        for name, item in list(sys.modules.items())
        if name == module.__name__ or name.startswith(prefix)
    ]
    originals = {
        value
        for item in modules
        if callable(value := getattr(item, "text_image", None))
        and getattr(value, "__module__", "").endswith(".pilot")
        and getattr(value, "__name__", "") == "text_image"
    }
    wrappers = {function: cache.wrap(function) for function in originals}
    replaced = []
    try:
        for item in modules:
            value = getattr(item, "text_image", None)
            if callable(value) and value in wrappers:
                replaced.append((item, value))
                vars(item)["text_image"] = wrappers[value]
        yield cache
    finally:
        for item, original in replaced:
            vars(item)["text_image"] = original
        cache.items.clear()
        cache.bytes = 0
