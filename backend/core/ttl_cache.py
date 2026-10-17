"""Tiny in-process TTL cache for hot, rarely-changing reads (admin configs).

Every game event used to read several config documents (leagues, City Pass,
City Market, comeback) from MongoDB. They change only when an admin saves them,
so each process keeps them for a few seconds; saving invalidates at once.
With several workers another worker sees the change within `ttl` seconds.
"""
import time
from typing import Any, Awaitable, Callable, Dict, Tuple

_store: Dict[str, Tuple[float, Any, Any]] = {}


async def cached(key: str, ttl: float, loader: Callable[[], Awaitable[Any]], owner: Any = None) -> Any:
    """`owner` (e.g. the db object) is kept referenced by the entry and checked
    with `is`, so an id(...) reused by a NEW object can never hit a stale entry."""
    hit = _store.get(key)
    now = time.monotonic()
    if hit and hit[0] > now and hit[2] is owner:
        return hit[1]
    value = await loader()
    _store[key] = (now + ttl, value, owner)
    return value


def invalidate(prefix: str = "") -> None:
    for k in [k for k in _store if k.startswith(prefix)]:
        _store.pop(k, None)
