"""Datetime helpers: always work with timezone-aware (UTC) datetimes.

Legacy/manually-seeded documents sometimes store datetimes WITHOUT timezone
info (naive). Comparing/subtracting a naive datetime with an aware
`datetime.now(timezone.utc)` raises
`TypeError: can't compare offset-naive and offset-aware datetimes`, which
previously bubbled up as HTTP 500 (e.g. /api/my/businesses,
/api/my/active-buff-multipliers). Use these helpers wherever a stored datetime
is compared with "now".
"""
from datetime import datetime, timezone
from typing import Optional, Union


def to_aware(value: Union[str, datetime, None]) -> Optional[datetime]:
    """Return a timezone-aware UTC datetime.

    Accepts an ISO string (with or without 'Z'/offset) or a datetime object.
    Naive inputs are assumed to be UTC. Returns None if it cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return None


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)
