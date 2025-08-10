import logging
from typing import Optional

_LOGGING_CONFIGURED = False
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with a standard format once."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    _LOGGING_CONFIGURED = True

def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a logger with the project's configuration."""
    if not _LOGGING_CONFIGURED:
        setup_logging()
    return logging.getLogger(name)
