"""Explicit editing dispatcher/recovery service; never runs media tools in API."""

import argparse
import logging
import signal
import threading

from .config import Settings
from .database import build_database
from .video_editing_planning_worker import recover as recover_planning
from .video_editing_worker import recover


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()
    if not 10 <= args.interval <= 300:
        parser.error("Interval must be 10..300 seconds")
    settings = Settings()
    if not settings.video_editing_enabled:
        raise SystemExit("Editing service is disabled")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    engine, factory = build_database(settings.database_url)
    try:
        while not stop.is_set():
            try:
                count = recover(factory)
                count += recover_planning(factory)
                if count:
                    logging.info("Editing tasks dispatched: %s", count)
            except Exception:
                # DB connection strings and broker credentials stay out of logs.
                logging.error("Editing recovery scan failed; retrying")
            stop.wait(args.interval)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
