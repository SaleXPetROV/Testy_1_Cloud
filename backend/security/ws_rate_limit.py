"""F36 helper: per-user token-bucket rate limiter for WebSocket messages.

Slowapi handles HTTP endpoints via a decorator, but WebSocket message rate
limiting has to be done inside the receive loop. This module offers a tiny
in-memory sliding-window counter, keyed by an arbitrary identifier (usually
`user_id`).

Defaults: 60 messages / minute per user. Configurable via
`WS_MSG_LIMIT_PER_MIN` env var.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict


_WS_MSG_LIMIT_PER_MIN = max(1, int(os.environ.get("WS_MSG_LIMIT_PER_MIN", "60")))
_WS_WINDOW_SECONDS = 60

_buckets: Dict[str, Deque[float]] = defaultdict(deque)


def check_ws_msg_rate(identifier: str) -> bool:
    """Return True if the caller is under the message limit. Records the hit.

    Returns False when the limit is exceeded. Caller should either drop the
    message silently, send an error frame, or close the connection.
    """
    if not identifier:
        return True  # anonymous keep-alive frames aren't attributable — allow.
    now = time.monotonic()
    window_start = now - _WS_WINDOW_SECONDS
    bucket = _buckets[identifier]
    while bucket and bucket[0] < window_start:
        bucket.popleft()
    if len(bucket) >= _WS_MSG_LIMIT_PER_MIN:
        return False
    bucket.append(now)
    return True


def reset_ws_rate(identifier: str) -> None:
    """Clear the counter for a user (e.g. on disconnect)."""
    _buckets.pop(identifier, None)
