import logging
import json
from typing import Optional, Mapping, Dict, Any

_LOGGING_CONFIGURED = False
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


_DEFAULT_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__.keys())


class ContextFormatter(logging.Formatter):
    """Formatter that appends any custom LogRecord attributes as JSON context.

    This ensures that fields passed via ``extra={...}`` appear in logs even if
    the base format string doesn't include them explicitly.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        # Collect non-standard attributes from the record
        context: Dict[str, Any] = {}
        for k, v in record.__dict__.items():
            if k in _DEFAULT_RECORD_KEYS:
                continue
            if k.startswith("_"):
                continue
            if k in {"exc_text", "stack_info"}:
                continue
            context[k] = v
        if context:
            try:
                ctx = json.dumps(context, ensure_ascii=False, default=str)
                return f"{base} | {ctx}"
            except Exception:
                # Fallback: show a best-effort repr
                return f"{base} | context={context}"
        return base


class SafeStreamHandler(logging.StreamHandler):
    """StreamHandler that ignores writes after the stream is closed.

    During test teardown the standard streams may be closed before
    application atexit handlers run.  Emitting log records in that
    scenario normally raises ``ValueError: I/O operation on closed file``.
    This handler quietly drops such records so that logging during
    shutdown does not generate noisy tracebacks.
    """

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - tiny wrapper
        stream = getattr(self, "stream", None)
        if not stream or getattr(stream, "closed", False):
            return
        try:
            super().emit(record)
        except Exception:
            # Ignore logging errors at interpreter shutdown
            pass

def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with a standard format once."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    handler = SafeStreamHandler()
    handler.setFormatter(ContextFormatter(LOG_FORMAT))
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


# ---- Debug helpers (safe logging) ----
SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key"}


def redact_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    """Return a copy of headers with sensitive values redacted.

    Only used for temporary debugging; avoid long-term logging of full headers.
    """
    out: Dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in SENSITIVE_HEADERS:
            if not v:
                out[k] = "<empty>"
            elif lk == "authorization":
                # Keep scheme and last 6 chars for correlation
                parts = v.split(" ", 1)
                if len(parts) == 2:
                    scheme, token = parts
                    out[k] = f"{scheme} ****{token[-6:]}"
                else:
                    out[k] = "****"
            else:
                out[k] = "<redacted>"
        else:
            out[k] = v
    return out


def dump_request_meta(environ: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract forwarding-related request metadata from the WSGI environ."""
    keys = [
        "REQUEST_METHOD",
        "PATH_INFO",
        "QUERY_STRING",
        "HTTP_HOST",
        "REMOTE_ADDR",
        "HTTP_X_FORWARDED_PROTO",
        "HTTP_X_FORWARDED_HOST",
        "HTTP_X_FORWARDED_PORT",
        "HTTP_X_FORWARDED_PREFIX",
        "SCRIPT_NAME",
        "wsgi.url_scheme",
    ]
    return {k: environ.get(k) for k in keys}
