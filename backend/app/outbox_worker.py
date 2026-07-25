import time

from .config import Settings
from .database import build_database
from .outbox import publish_pending_events
from .task_runner import MockTaskRunner


def main() -> None:
    settings = Settings()
    settings.validate_runtime_safety()
    engine, session_factory = build_database(settings.database_url)
    runner = MockTaskRunner(session_factory, settings.mock_job_delay_seconds)
    try:
        while True:
            published = publish_pending_events(settings, session_factory, runner)
            time.sleep(0.5 if published else 2)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
