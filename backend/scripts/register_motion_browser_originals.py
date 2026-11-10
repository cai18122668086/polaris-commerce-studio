"""Inspect or register originals supplied at the native package-relative paths."""

import argparse
import json
from pathlib import Path

from app.motion_browser_originals import intake_browser_originals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--provenance", default="")
    parser.add_argument("--apply", action="store_true", help="Register verified files")
    args = parser.parse_args()
    try:
        report = intake_browser_originals(
            args.package,
            args.bindings,
            source=args.source,
            origin=args.provenance,
            apply=args.apply,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
