"""Reconcile the per-user tender escrow counter.

`users.frozen_city_for_tenders` is a running counter incremented when a tender
contract becomes active and decremented when it ends. In practice it can DRIFT
(a broken/completed contract whose decrement didn't fully match, or rounding),
leaving a stale positive residue. That residue then shows up in the withdrawal
modal as "Заморожено в контрактах" even when the user has NO active contracts.

`effective_frozen_city` returns the amount that is ACTUALLY frozen: if the user
has no active tender contract holding escrow, the answer is 0 and we self-heal
the stored counter. Otherwise we trust the stored counter (reconstructing exact
per-role reserves from every contract is fragile and unnecessary for the fix).
"""

# Contract statuses that still hold escrow against the user's balance.
ACTIVE_TENDER_STATES = ["ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES", "PROPOSED"]


async def effective_frozen_city(db, user) -> float:
    """Return the real frozen escrow in $CITY for this user (0 when no active
    contracts). Self-heals a drifted counter down to 0 in that case."""
    stored = float((user or {}).get("frozen_city_for_tenders", 0) or 0)
    if stored <= 0:
        return 0.0
    ids = [v for v in {user.get("id"), user.get("wallet_address")} if v]
    if not ids:
        return stored
    q = {
        "status": {"$in": ACTIVE_TENDER_STATES},
        "$or": [
            {"seller_id": {"$in": ids}},
            {"buyer_id": {"$in": ids}},
            {"seller_wallet": {"$in": ids}},
            {"buyer_wallet": {"$in": ids}},
        ],
    }
    try:
        cnt = await db.tender_contracts.count_documents(q)
    except Exception:
        return stored
    if cnt == 0:
        try:
            await db.users.update_one(
                {"id": user.get("id")},
                {"$set": {"frozen_city_for_tenders": 0}},
            )
        except Exception:
            pass
        return 0.0
    return stored
