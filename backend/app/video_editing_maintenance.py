"""Explicit editing dispatcher/recovery service; never runs media tools in API."""

import argparse
import logging
import signal
import threading

from . import video_credit_billing as video_credits
from .config import Settings
from .database import build_database_for
from .video_editing_planning_worker import recover as recover_planning
from .video_editing_worker import recover
from .video_media_cleanup import Scheduler as MediaCleanup


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()
    if not 10 <= args.interval <= 300:
        parser.error("Interval must be 10..300 seconds")
    # INFO 级别要能进容器日志：调度数、积分结算、磁盘清理（B14）每轮的结果。
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    settings = Settings()
    if not settings.video_editing_enabled:
        raise SystemExit("Editing service is disabled")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    engine, factory = build_database_for(settings)
    cleanup = MediaCleanup(settings)
    try:
        while not stop.is_set():
            try:
                count = recover(factory)
                count += recover_planning(factory)
                if count:
                    logging.info("Editing tasks dispatched: %s", count)
                # Settle/release holds of finished video tasks, including
                # ones whose worker crashed or hit a Celery time limit.
                settled = video_credits.sweep(factory)
                if settled:
                    logging.info("Video credit holds resolved: %s", settled)
                # 磁盘清理按自己的间隔执行，每次执行都记一行日志（删了多少、腾出多少）。
                cleanup.tick(factory)
            except Exception:
                # DB connection strings and broker credentials stay out of logs.
                logging.error("Editing recovery scan failed; retrying")
            stop.wait(args.interval)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
