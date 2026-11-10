"""Verify exact original fonts/models and merge the private dependency registry."""

import argparse
import json
from pathlib import Path

from app.motion_local_dependencies import intake_local_dependencies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument(
        "--candidate",
        nargs=2,
        metavar=("RESOURCE_ID", "FILE"),
        action="append",
        required=True,
    )
    parser.add_argument("--provenance", default="")
    parser.add_argument(
        "--component-use-reference",
        nargs=2,
        metavar=("RESOURCE_ID", "REFERENCE"),
        action="append",
        default=[],
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    candidates = {rid: Path(path) for rid, path in args.candidate}
    if len(candidates) != len(args.candidate):
        parser.error("Supply each original resource only once")
    references = dict(args.component_use_reference)
    if len(references) != len(args.component_use_reference):
        parser.error("Supply each component use reference only once")
    try:
        report = intake_local_dependencies(
            args.package,
            args.bindings,
            candidates,
            origin=args.provenance,
            component_references=references,
            apply=args.apply,
        )
    except OSError:
        parser.error("Unable to access the private intake files or registry lock")
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
