from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def now_utc() -> datetime:
    """Return a timezone-aware UTC datetime (no deprecation warnings)."""
    return datetime.now(timezone.utc)


def ensure_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize a datetime to timezone-aware UTC for safe comparisons.

    - If dt is None, returns None.
    - If dt is naive, assumes it is UTC and attaches timezone.utc.
    - If dt is aware, converts to UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

