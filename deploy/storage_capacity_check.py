"""Check the backing filesystem headroom before MinIO starts refusing writes."""

import argparse
import os
import sys
from pathlib import Path

GIB = 1024**3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, nargs="+")
    parser.add_argument("--warn-gib", type=int, default=14)
    parser.add_argument("--critical-gib", type=int, default=10)
    args = parser.parse_args()
    if not 0 < args.critical_gib < args.warn_gib:
        parser.error("Require 0 < critical-gib < warn-gib")
    status = 0
    filesystems = {}
    for path in args.path:
        try:
            device = path.stat().st_dev
            statvfs = os.statvfs(path)
        except OSError as error:
            print(f"CRITICAL {path}: {error}", file=sys.stderr)
            status = 2
            continue
        if device in filesystems:
            continue
        filesystems[device] = path
        available = statvfs.f_bavail * statvfs.f_frsize / GIB
        level = (
            "CRITICAL"
            if available < args.critical_gib
            else "WARNING"
            if available < args.warn_gib
            else "OK"
        )
        print(
            f"{level} {path}: {available:.2f} GiB available "
            f"(warn < {args.warn_gib}, critical < {args.critical_gib})",
            file=sys.stdout if level == "OK" else sys.stderr,
        )
        status = max(status, {"OK": 0, "WARNING": 1, "CRITICAL": 2}[level])
    return status


if __name__ == "__main__":
    sys.exit(main())
