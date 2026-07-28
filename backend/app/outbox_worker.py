import time

from .config import Settings
from .database import build_database
from .outbox import publish_pending_events
from .storage import build_image_storage
from .task_runner import build_task_runner, validate_task_runner_settings


def main() -> None:
    settings = Settings()
    settings.validate_runtime_safety()
    validate_task_runner_settings(settings)
    engine, session_factory = build_database(settings.database_url)
    storage = build_image_storage(settings)
    runner = build_task_runner(session_factory, settings, storage)
    try:
        while True:
            published = publish_pending_events(settings, session_factory, runner)
            time.sleep(0.5 if published else 2)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
