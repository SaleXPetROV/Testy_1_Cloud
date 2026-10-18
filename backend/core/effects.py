"""ONE rule for boosters: not more than MAX_ACTIVE effects at the same time.

Counted effects: «Автозапуск смен» (users.auto_shift_until), «Защита склада» (decay_protected_until),
«×2 XP» (xp_x2_until) and every active tier-3 resource buff (users.active_resource_buffs).
Extending an effect that is already running does not add a new one, so it is always allowed.
«Ремонт всех бизнесов» is instant and not counted.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MAX_ACTIVE = 2
TIMED = {"auto_shift": "auto_shift_until", "warehouse_guard": "decay_protected_until", "xp_x2": "xp_x2_until"}


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def active_effects(user: Dict[str, Any], now: Optional[datetime] = None) -> List[str]:
    """Keys of the effects running now: 'auto_shift', 'warehouse_guard', 'xp_x2', 't3:<resource>'."""
    now = now or datetime.now(timezone.utc)
    out = [k for k, f in TIMED.items() if (_parse((user or {}).get(f)) or now) > now]
    for b in (user or {}).get("active_resource_buffs") or []:
        t = _parse(b.get("expires_at"))
        if t and t > now:
            out.append(f"t3:{b.get('resource_id')}")
    return out


def can_activate(user: Dict[str, Any], key: str, now: Optional[datetime] = None) -> bool:
    """key: 'auto_shift' | 'warehouse_guard' | 'xp_x2' | 't3:<resource>'."""
    act = active_effects(user, now)
    return key in act or len(act) < MAX_ACTIVE


LIMIT_DETAIL = "boosters_limit"          # the app shows «Одновременно могут работать только 2 усилителя»
