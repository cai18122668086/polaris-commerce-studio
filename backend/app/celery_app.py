from celery import Celery

from .celery_limits import task_annotations
from .config import Settings

settings = Settings()
celery_app = Celery(
    "polaris",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks",
        "app.ecommerce_worker",
        "app.video_editing_worker",
        "app.video_editing_planning_worker",
        "app.video_benchmark_transcribe",
    ],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    worker_soft_shutdown_timeout=30,
    # Soft limit raises SoftTimeLimitExceeded inside the task so its failure
    # path runs; the hard limit (soft + grace) kills a stuck child.
    task_annotations=task_annotations(settings),
    task_routes={
        "polaris.process_job": {"queue": "default"},
        "polaris.cancel_job": {"queue": "default"},
        "polaris.process_crawl_task": {"queue": "crawl"},
        "polaris.process_editing_task": {"queue": "editing"},
        "polaris.transcribe_benchmark": {"queue": "editing"},
        "polaris.process_editing_planning_task": {"queue": "editing-planning"},
    },
)
