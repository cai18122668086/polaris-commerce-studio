from __future__ import annotations

import uuid
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from .state import HarnessError


NEAR_RATIO_TOLERANCE = 0.01
MAX_HYBRID_CROP_FRACTION = 0.12


def ensure_format_canvas(path: str | Path, width: int, height: int) -> str:
    """Create an exact-size blank raster used only to lock the initial image-generation canvas."""
    target = Path(path).resolve()
    if width <= 0 or height <= 0:
        raise HarnessError("Format-canvas dimensions must be positive integers")
    if target.is_file():
        try:
            with Image.open(target) as existing:
                if existing.size == (width, height):
                    return str(target)
        except (OSError, UnidentifiedImageError):
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", (width, height), (248, 248, 246))
    canvas.save(target, format="PNG", optimize=True)
    canvas.close()
    return str(target)


def _crop_toward_ratio(image: Image.Image, target_ratio: float) -> tuple[Image.Image, float]:
    """Reduce large edge bands while keeping crop bounded and geometry proportional."""
    width, height = image.size
    source_ratio = width / height
    if source_ratio < target_ratio:
        required_fraction = 1 - (source_ratio / target_ratio)
        crop_fraction = min(required_fraction, MAX_HYBRID_CROP_FRACTION)
        crop_px = int(round(height * crop_fraction))
        top = crop_px // 2
        return image.crop((0, top, width, height - (crop_px - top))), crop_fraction
    required_fraction = 1 - (target_ratio / source_ratio)
    crop_fraction = min(required_fraction, MAX_HYBRID_CROP_FRACTION)
    crop_px = int(round(width * crop_fraction))
    left = crop_px // 2
    return image.crop((left, 0, width - (crop_px - left), height)), crop_fraction


def image_dimensions(path: str | Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, UnidentifiedImageError) as exc:
        raise HarnessError(f"Generated image is not a readable raster image: {path}") from exc


def normalize_generated_image(
    source: str | Path,
    target_width: int,
    target_height: int,
) -> dict:
    """Return an exact-size raster without ever stretching width and height independently."""
    source_path = Path(source).resolve()
    if target_width <= 0 or target_height <= 0:
        raise HarnessError("Approved output dimensions must be positive integers")

    try:
        with Image.open(source_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise HarnessError(f"Generated image is not a readable raster image: {source_path}") from exc

    source_width, source_height = image.size
    source_ratio = source_width / source_height
    target_ratio = target_width / target_height
    ratio_error = abs(source_ratio - target_ratio) / target_ratio

    if image.size == (target_width, target_height):
        image.close()
        return {
            "path": str(source_path),
            "source_path": str(source_path),
            "source_width_px": source_width,
            "source_height_px": source_height,
            "width_px": target_width,
            "height_px": target_height,
            "mode": "EXACT",
            "relative_ratio_error": ratio_error,
            "bounded_crop_fraction": 0.0,
        }

    output = source_path.with_name(
        f"{source_path.stem}-normalized-{uuid.uuid4().hex[:8]}.png"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    if ratio_error <= NEAR_RATIO_TOLERANCE:
        normalized = ImageOps.fit(
            image,
            (target_width, target_height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        mode = "CENTER_CROP_RESIZE"
    else:
        adjusted, crop_fraction = _crop_toward_ratio(image, target_ratio)
        adjusted_ratio = adjusted.width / adjusted.height
        adjusted_error = abs(adjusted_ratio - target_ratio) / target_ratio
        if adjusted_error <= NEAR_RATIO_TOLERANCE:
            normalized = ImageOps.fit(
                adjusted,
                (target_width, target_height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            adjusted.close()
            mode = "BOUNDED_CENTER_CROP_RESIZE"
        else:
            background = ImageOps.fit(
                adjusted,
                (target_width, target_height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            ).filter(ImageFilter.GaussianBlur(radius=max(target_width, target_height) / 45))
            veil = Image.new("RGB", (target_width, target_height), "white")
            background = Image.blend(background, veil, 0.16)
            foreground = ImageOps.contain(
                adjusted,
                (target_width, target_height),
                method=Image.Resampling.LANCZOS,
            )
            x = (target_width - foreground.width) // 2
            y = (target_height - foreground.height) // 2
            background.paste(foreground, (x, y))
            foreground.close()
            veil.close()
            adjusted.close()
            normalized = background
            mode = "HYBRID_CROP_WITH_BLURRED_EDGE_EXTENSION"

    normalized.save(output, format="PNG", optimize=True)
    normalized.close()
    image.close()
    return {
        "path": str(output.resolve()),
        "source_path": str(source_path),
        "source_width_px": source_width,
        "source_height_px": source_height,
        "width_px": target_width,
        "height_px": target_height,
        "mode": mode,
        "relative_ratio_error": ratio_error,
        "bounded_crop_fraction": 0.0 if ratio_error <= NEAR_RATIO_TOLERANCE else crop_fraction,
    }


