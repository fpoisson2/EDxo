import logging
from typing import Optional, Mapping, Dict, Any

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
