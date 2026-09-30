"""Encode existing homepage artwork; never overwrite source PNGs."""

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "public/images/homepage-features/native-v2"
OUTPUT = SOURCE.parent / "native-v2-webp"


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    report = []
    for source in sorted(SOURCE.glob("*.png")):
        with Image.open(source) as image:
            # Retain the authored crop and ample resolution for high-DPI cards.
            image.thumbnail((1152, 1152), Image.Resampling.LANCZOS)
            target = OUTPUT / source.with_suffix(".webp").name
            image.save(target, "WEBP", quality=86, method=6)
            report.append({"file": target.name, "width": image.width,
                           "height": image.height, "source_bytes": source.stat().st_size,
                           "bytes": target.stat().st_size})
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
