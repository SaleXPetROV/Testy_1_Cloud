"""Revoking login tokens (stolen / lost device) without single-session enforcement.

Every token carries `iat` (issue time, float seconds). A user document may carry
`tokens_valid_after`: any token issued before it is rejected — by ONE middleware in
front of every /api route (whatever handler decodes the token afterwards) and by the
websocket handlers. Several devices stay logged in at the same time; revocation
(password change / reset, «выйти на всех устройствах», 2FA off) ends all of them.
"""
import time
from typing import Any, Dict, Optional

_cache: Dict[str, tuple] = {}            # sub -> (expires_at, tokens_valid_after)
TTL = 30.0


async def valid_after(db, sub: str) -> float:
    hit = _cache.get(sub)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    u = await db.users.find_one({"$or": [{"id": sub}, {"email": sub}, {"wallet_address": sub}]},
                                {"_id": 0, "tokens_valid_after": 1})
    v = float((u or {}).get("tokens_valid_after") or 0)
    _cache[sub] = (now + TTL, v)
    return v


async def is_revoked(db, payload: Optional[Dict[str, Any]]) -> bool:
    if not payload or not payload.get("sub"):
        return False
    va = await valid_after(db, str(payload["sub"]))
    return bool(va) and float(payload.get("iat") or 0) < va


async def revoke_all(db, user_filter: Dict[str, Any]) -> float:
    """All tokens issued until now stop working. Returns the moment."""
    ts = time.time()
    await db.users.update_one(user_filter, {"$set": {"tokens_valid_after": ts}})       # two plain calls: portable
    u = await db.users.find_one(user_filter, {"_id": 0, "id": 1, "email": 1, "wallet_address": 1})
    for k in [k for k in (u or {}).values() if k]:
        _cache.pop(str(k), None)
    _cache.clear() if len(_cache) > 50000 else None
    return ts
