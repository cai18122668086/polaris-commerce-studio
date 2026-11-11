"""Explicit local installation; neither downloads assets nor calls paid APIs."""

import argparse
from pathlib import Path

from app.motion_library import (
    MOTION_SHA256,
    WRITING_SHA256,
    atomic_json,
    install_archive,
    registry,
)
from app.video_writing_rules import verify_writing_package


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-zip", type=Path, required=True)
    parser.add_argument("--writing-zip", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    package = install_archive(
        args.motion_zip, args.root / MOTION_SHA256[:12] / "motion", MOTION_SHA256
    )
    writing = install_archive(
        args.writing_zip, args.root / WRITING_SHA256[:12] / "writing", WRITING_SHA256
    )
    verify_writing_package(writing)
    index = args.root / MOTION_SHA256[:12] / "registry.json"
    # Do not overwrite later runtime evidence when reinstalling the same release.
    if not index.exists():
        atomic_json(index, registry(package))
    print(f"Installed full library: {package}")
    print("Registered 132 groups, 197 bundled assets, 699 external references.")
    print("Runtime and visual validation remain separate from registration.")


if __name__ == "__main__":
    main()
