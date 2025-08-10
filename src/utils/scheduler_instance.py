import threading
from functools import wraps
from datetime import datetime
from typing import Any, Callable

from flask import Flask
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent

from utils.backup_utils import (
    get_scheduler_instance,
    send_backup_email_with_context,
)
from utils.logging_config import get_logger
from config.env import GUNICORN_WORKER_ID

from app.models import BackupConfig

scheduler_lock = threading.Lock()
scheduler = get_scheduler_instance()

logger = get_logger(__name__)


def with_scheduler_lock(f: Callable) -> Callable:
    """Ensure thread-safe access to the scheduler.

    Parameters
    ----------
    f : Callable
        Function to wrap with a lock.

    Returns
    -------
    Callable
        Wrapped function that acquires ``scheduler_lock`` before executing.
    """

    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with scheduler_lock:
            return f(*args, **kwargs)

    return wrapper


def is_main_process() -> bool:
    """Determine if execution occurs in the main Gunicorn process.

    Returns
    -------
    bool
        ``True`` if running outside Gunicorn or in worker ``0``.
    """

    return GUNICORN_WORKER_ID is None or GUNICORN_WORKER_ID == "0"


def start_scheduler() -> None:
    """Start the APScheduler instance in the main process.

    The scheduler starts only once and solely within the primary Gunicorn worker.
    """

    if not scheduler.running and is_main_process():
        logger.info("Starting scheduler...")
        scheduler.start()


def shutdown_scheduler() -> None:
    """Stop the scheduler if it is currently running."""

    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped.")


@with_scheduler_lock
def schedule_backup(app: Flask) -> None:
    """Configure a recurring database backup job.

    Parameters
    ----------
    app : Flask
        Application instance providing context and configuration.

    Returns
    -------
    None
        The job is added to ``scheduler`` when backups are enabled; otherwise
        no action is taken.
    """

    logger.info("Starting schedule_backup function")
    logger.info(f"Current jobs: {scheduler.get_jobs()}")
    logger.info(f"Scheduler running: {scheduler.running}")

    if not is_main_process():
        return

    with app.app_context():
        config = BackupConfig.query.first()
        logger.info(f"Backup config: {config.__dict__ if config else None}")

        if config and config.enabled:
            try:
                backup_time = datetime.strptime(config.backup_time, "%H:%M").time()
                logger.info(f"Scheduled time: {backup_time}")

                # If 'app' has _get_current_object(), use it; otherwise use app directly.
                real_app = app._get_current_object() if hasattr(app, "_get_current_object") else app

                job_args = {
                    "func": send_backup_email_with_context,
                    "trigger": "cron",
                    "hour": backup_time.hour,
                    "minute": backup_time.minute,
                    "args": [real_app, config.email, app.config["DB_PATH"]],
                    "id": f"{config.frequency.lower()}_backup",
                    "replace_existing": True,
                    "name": f"Backup {config.frequency}",
                }

                scheduler.add_job(**job_args)
                logger.info(f"Jobs after scheduling: {scheduler.get_jobs()}")
                for job in scheduler.get_jobs():
                    logger.info(f"Job {job.id} next run: {job.next_run_time}")

            except Exception as e:  # pragma: no cover - defensive logging
                logger.error(f"Scheduling error: {e}", exc_info=True)


def job_error_handler(event: JobExecutionEvent) -> None:
    """Log scheduler job failures."""

    logger.error(f"Job failed: {event.job_id}, error: {event.exception}")


def job_executed_handler(event: JobExecutionEvent) -> None:
    """Log successful scheduler job executions."""

    logger.info(f"Job executed: {event.job_id}, runtime: {event.scheduled_run_time}")

scheduler.add_listener(job_error_handler, EVENT_JOB_ERROR)
scheduler.add_listener(job_executed_handler, EVENT_JOB_EXECUTED)
