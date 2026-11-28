"""No blue / purple in MG output (plan §5.4, CI-enforced).

A pixel counts as blue/purple when its hue is 190°–300° and saturation >0.25.
More than 0.5 % of visible pixels (alpha > 10 %) fails the check.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

HUE_LOW, HUE_HIGH, SATURATION, LIMIT = 190.0, 300.0, 0.25, 0.005
_HEX = re.compile(r"#([0-9a-fA-F]{6})\b")


def _hsv(rgb: Any) -> tuple[Any, Any]:
    import numpy as np

    rgb = rgb.astype(np.float32) / 255.0
    high = rgb.max(axis=-1)
    low = rgb.min(axis=-1)
    delta = high - low
    sat = np.where(high > 0, delta / np.maximum(high, 1e-6), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    safe = np.maximum(delta, 1e-6)
    hue = np.where(
        high == r,
        ((g - b) / safe) % 6,
        np.where(high == g, (b - r) / safe + 2, (r - g) / safe + 4),
    )
    hue = np.where(delta > 0, hue * 60.0, 0)
    return hue, sat


def blue_purple_ratio(image: Any) -> float:
    """Share of visible pixels that are blue/purple (PIL image, any mode)."""
    import numpy as np

    rgba = np.asarray(image.convert("RGBA"))
    visible = rgba[..., 3] > 25
    if not visible.any():
        return 0.0
    hue, sat = _hsv(rgba[..., :3])
    bad = visible & (hue >= HUE_LOW) & (hue <= HUE_HIGH) & (sat > SATURATION)
    return float(bad.sum()) / float(visible.sum())


def check_image(path: Path) -> float:
    from PIL import Image

    with Image.open(path) as image:
        return blue_purple_ratio(image)


def hex_is_blue_purple(value: str) -> bool:
    import numpy as np

    rgb = np.array([[[int(value[i : i + 2], 16) for i in (1, 3, 5)]]], np.uint8)
    hue, sat = _hsv(rgb)
    return bool(
        HUE_LOW <= float(hue[0, 0]) <= HUE_HIGH and float(sat[0, 0]) > SATURATION
    )


def source_colours(text: str) -> list[str]:
    """Every #rrggbb literal in a component source that is blue/purple."""
    return [m.group(0) for m in _HEX.finditer(text) if hex_is_blue_purple(m.group(0))]
