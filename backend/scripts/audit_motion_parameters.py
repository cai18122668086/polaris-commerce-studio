"""Inspect all original contracts. This command never renders or calls a model."""

import argparse
from pathlib import Path

from app.motion_library import MOTION_SHA256, atomic_json, verify_package
from app.motion_parameter_contracts import all_contracts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    integrity = verify_package(args.library)
    groups = all_contracts(args.library)
    atomic_json(
        args.out,
        {
            "version": "tengli.native-parameter-audit/1",
            "release": MOTION_SHA256,
            "integrity": integrity,
            "group_count": len(groups),
            "scope": (
                "original concrete template fields; "
                "not full native authoring or runtime coverage"
            ),
            "groups": groups,
        },
    )
    print(f"{len(groups)} original group contracts recorded; no render or paid call.")


if __name__ == "__main__":
    main()
