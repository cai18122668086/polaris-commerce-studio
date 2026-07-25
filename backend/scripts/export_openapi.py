import json
import sys
from pathlib import Path

from app.config import Settings
from app.main import create_app


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: export_openapi.py OUTPUT_PATH")
    output = Path(sys.argv[1]).resolve()
    settings = Settings(
        _env_file=None,
        environment="test",
        auth_mode="development",
        database_url="sqlite://",
        storage_backend="local",
        auto_create_schema=False,
        auto_process_jobs=False,
    )
    schema = create_app(settings).openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
