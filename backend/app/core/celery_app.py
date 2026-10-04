from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "reprolens_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.pipeline.orchestrator"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Celery provides robust task retries and routing essential for pipeline stability
)
