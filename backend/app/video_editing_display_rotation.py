"""Read the lossless quarter turns represented by FFprobe display matrices."""

from typing import Any

_ONE = 1 << 16
_ROTATIONS = {
    0: (_ONE, 0, 0, _ONE),
    90: (0, -_ONE, _ONE, 0),
    180: (-_ONE, 0, 0, -_ONE),
    270: (0, _ONE, -_ONE, 0),
}


def display_rotation(video: dict[str, Any]) -> int:
    """Return a verified counterclockwise turn, or reject a different transform."""
    matrices = [
        side
        for side in video.get("side_data_list", [])
        if side.get("side_data_type") == "Display Matrix"
        or "displaymatrix" in side
        or "rotation" in side
    ]
    legacy = video.get("tags", {}).get("rotate")
    if not matrices and legacy in (None, "0", 0):
        return 0
    try:
        (matrix,) = matrices
        angle = int(matrix["rotation"]) % 360
        a, b, u, c, d, v, x, y, w = (
            int(value)
            for line in matrix["displaymatrix"].strip().splitlines()
            for value in line.partition(":")[2].split()
        )
        width, height = video["width"], video["height"]
        translation = (
            -min(a, 0) * width - min(c, 0) * height,
            -min(b, 0) * width - min(d, 0) * height,
        )
        if (
            (a, b, c, d) == _ROTATIONS.get(angle)
            and (u, v, w) == (0, 0, 1 << 30)
            and (x, y) in {(0, 0), translation}
            and (legacy is None or int(legacy) % 360 == angle)
        ):
            return angle
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    raise ValueError("Source display transform is not a verified quarter turn")


def display_size(video: dict[str, Any], angle: int) -> tuple[int, int]:
    width, height = video["width"], video["height"]
    return (height, width) if angle in {90, 270} else (width, height)
