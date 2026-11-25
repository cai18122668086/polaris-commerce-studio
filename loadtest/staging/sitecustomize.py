"""Staging only: apply stg_boot fakes in every Python process of the staging containers,
including processes spawned by `uvicorn --workers N` (multiprocessing spawn re-imports from scratch)."""
import os
import sys

if os.environ.get("STG_SHIM_AUTOPATCH") == "1":
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    try:
        import stg_boot

        stg_boot.patch()
    except Exception as exc:  # never let the shim break interpreter start-up silently
        print(f"stg_boot autopatch failed: {exc!r}", file=sys.stderr)
        raise
