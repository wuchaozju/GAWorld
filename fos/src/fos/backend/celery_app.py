from __future__ import annotations

import os

try:
    from celery import Celery
except ModuleNotFoundError:
    Celery = None

# Broker URL - prefer env var, fallback to redis localhost
BROKER_URL = os.environ.get("REDIS_URL") or os.environ.get("FOS_REDIS_URL") or "redis://localhost:6379/0"

if Celery is None:

    class _NullControl:
        """Stub for Celery's Inspect-like control interface."""

        def revoke(self, *args, **kwargs) -> None:
            pass

    class NullCeleryApp:
        """Fallback Celery app used when the celery package is not installed."""

        is_available: bool = False

        def __init__(self) -> None:
            self.control = _NullControl()

    celery_app = NullCeleryApp()
else:
    celery_app = Celery("fos", broker=BROKER_URL)
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_track_started=True,
    )
