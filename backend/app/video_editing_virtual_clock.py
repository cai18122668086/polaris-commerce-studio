"""Invert the original Build12 discrete drawing clock."""

import math
from itertools import pairwise


def first_visible_frame(
    actual: list[float], virtual: list[float], required: int
) -> int:
    boundary = (required - 0.5) / 30
    for (a, x), (b, y) in pairwise(zip(actual, virtual, strict=True)):
        if x <= boundary <= y:
            frames = (a + (b - a) * (boundary - x) / (y - x)) * 30
            # The original renderer uses Python's ties-to-even round.
            return (
                math.floor(frames + 1e-8) + 1
                if required % 2
                else math.ceil(frames - 1e-8)
            )
    raise ValueError("Native event lies outside its virtual scene")
