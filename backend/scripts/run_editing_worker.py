"""Separate process entry; --once runs one task, --recover requeues durable work."""

import argparse

from app.config import Settings
from app.database import build_database
from app.video_editing_worker import process, recover


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once")
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    if not args.once and not args.recover:
        parser.error("Choose --once TASK_ID or --recover")
    settings = Settings()
    engine, factory = build_database(settings.database_url)
    try:
        if args.once:
            process(args.once, settings, factory)
        else:
            print("Requeued tasks:", recover(factory))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
