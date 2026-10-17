"""ONE rule for "is this business working right now".

A business produces (and wears down) only while its 8-hour shift is running —
level 0 included. Only tutorial (sandbox) and trial-centre businesses operate
on their own, without a shift.

This used to be copied in background_tasks.py, server.py and the frontend
ShiftButton, and the copies had to be changed by hand in sync. Everything now
calls this module; the frontend gets `auto_operates` from /my/businesses.
"""
from datetime import datetime, timezone
from typing import Optional

SHIFT_DURATION_HOURS = 8


def auto_operates(business: dict) -> bool:
    """True for businesses that work without a shift (tutorial / trial)."""
    return bool(business.get("tutorial") or business.get("is_trial"))


def shift_is_active(business: dict, now: Optional[datetime] = None) -> bool:
    """While False the business is idle: no production and no durability loss."""
    if auto_operates(business):
        return True
    se = business.get("shift_ends_at")
    if not se:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(str(se).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return now < dt
    except (ValueError, TypeError):
        return False
