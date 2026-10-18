"""Welcome / registration bonus.

Every newly-registered user (email, Google, Telegram, wallet) receives a
one-time +0.5 TON credited to their BONUS balance. The grant is idempotent —
guarded by the `welcome_bonus_granted` flag — so it can never be applied twice
even if a registration path is retried.
"""
import logging

logger = logging.getLogger(__name__)

WELCOME_BONUS_TON = 0.5


async def ensure_welcome_bonus(db, user_filter: dict) -> bool:
    """Credit the one-time +0.5 TON welcome bonus to `bonus_balance`.

    Returns True when the bonus was actually granted (first time), False when it
    had already been granted before. Never raises — a bonus failure must not
    break the registration flow.
    """
    try:
        res = await db.users.update_one(
            {**user_filter, "welcome_bonus_granted": {"$ne": True}},
            {"$set": {"welcome_bonus_granted": True},
             "$inc": {"bonus_balance": WELCOME_BONUS_TON}},
        )
        return bool(res.modified_count)
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_welcome_bonus failed: %s", e)
        return False
