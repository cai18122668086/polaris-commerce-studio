"""Run an editing task, requeue durable work, or check a target runtime."""

import argparse

from app.config import Settings
from app.database import build_database
from app.video_editing_runtime_check import print_editing_runtime
from app.video_editing_worker import process, recover


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--once")
    action.add_argument("--recover", action="store_true")
    action.add_argument("--check-runtime", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.check_runtime:
        print_editing_runtime(settings)
        return
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
