"""SearchSmartly project package.

Importing the Celery app here is what makes ``@shared_task`` bind to this
project's Celery instance when Django starts.
"""

from .celery import app as celery_app

__all__ = ["celery_app"]
