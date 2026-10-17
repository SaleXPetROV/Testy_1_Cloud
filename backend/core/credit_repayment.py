"""
Per-transaction credit repayment.

Whenever a seller receives funds from a sale (resource market or land/business
market), this module withholds the borrower's configured
`salary_deduction_percent` and applies it to all of their active credits.

Rules implemented here:
  * Each active credit takes `gross_amount * salary_deduction_percent` from the
    seller's just-received income (capped to the credit's remaining debt).
  * If the lender is a private bank, the deducted amount is credited to the
    lender's balance.
  * Each deduction is recorded as a `credit_payment` transaction so it shows up
    in the user's history with full context.
  * Returns a summary that callers can attach to API responses so the frontend
    can warn the user "X% of this sale will go to credit repayment".

The functions are deliberately defensive: if anything goes wrong we log and
return zero so a credit-system bug never blocks the actual sale.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


async def get_active_credits(db, seller_id: str, seller_wallet: str | None = None) -> List[Dict[str, Any]]:
    """Return all active/overdue credits owned by the given borrower."""
    if not seller_id and not seller_wallet:
        return []
    or_clauses = []
    if seller_id:
        or_clauses.append({"borrower_id": seller_id})
    if seller_wallet:
        or_clauses.append({"borrower_wallet": seller_wallet})
    query = {
        "$or": or_clauses,
        "status": {"$in": ["active", "overdue"]},
        "remaining": {"$gt": 0},
    }
    return await db.credits.find(query, {"_id": 0}).to_list(50)


async def estimate_credit_deduction(
    db,
    seller_id: str,
    gross_amount: float,
    seller_wallet: str | None = None,
) -> Dict[str, Any]:
    """
    Pure read: how much of `gross_amount` would be redirected to credit
    repayments if the seller closed a sale right now. No DB writes.
    """
    try:
        if gross_amount <= 0:
            return {"has_credit": False, "total_deduction": 0.0, "credits": []}
        credits = await get_active_credits(db, seller_id, seller_wallet)
        if not credits:
            return {"has_credit": False, "total_deduction": 0.0, "credits": []}
        per_credit = []
        total = 0.0
        for credit in credits:
            pct = float(credit.get("salary_deduction_percent") or 0)
            if credit.get("is_doubled_rate"):
                pct *= 2
            remaining = float(credit.get("remaining") or 0)
            if pct <= 0 or remaining <= 0:
                continue
            raw = gross_amount * pct
            payment = round(min(raw, remaining), 6)
            if payment <= 0:
                continue
            total += payment
            per_credit.append({
                "credit_id": credit.get("id"),
                "lender_name": credit.get("lender_name") or "",
                "lender_type": credit.get("lender_type") or "government",
                "deduction_percent": round(pct * 100, 2),
                "amount": payment,
                "remaining_after": round(max(0.0, remaining - payment), 4),
            })
        return {
            "has_credit": bool(per_credit),
            "total_deduction": round(total, 6),
            "credits": per_credit,
        }
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("estimate_credit_deduction failed: %s", exc)
        return {"has_credit": False, "total_deduction": 0.0, "credits": []}


async def apply_credit_deduction(
    db,
    seller_id: str,
    gross_amount: float,
    *,
    seller_wallet: str | None = None,
    source: str = "sale",
    context: Dict[str, Any] | None = None,
) -> Tuple[float, List[Dict[str, Any]]]:
    """
    Apply credit deductions to the seller for one sale.

    * `gross_amount` is the amount the seller just received (post-tax).
    * Deducts each active credit's `salary_deduction_percent * gross_amount`
      (capped to its remaining debt) from the seller's balance.
    * Credits the deducted amount to the lender's balance (for bank credits).
    * Inserts a `credit_payment` transaction for every credit.

    Returns: (total_deducted_amount, [list of per-credit results]).
    """
    if gross_amount <= 0:
        return 0.0, []

    try:
        credits = await get_active_credits(db, seller_id, seller_wallet)
        if not credits:
            return 0.0, []

        now_iso = datetime.now(timezone.utc).isoformat()
        results: List[Dict[str, Any]] = []
        total_deducted = 0.0

        for credit in credits:
            pct = float(credit.get("salary_deduction_percent") or 0)
            if credit.get("is_doubled_rate"):
                pct *= 2
            remaining = float(credit.get("remaining") or 0)
            if pct <= 0 or remaining <= 0:
                continue

            raw = gross_amount * pct
            payment = round(min(raw, remaining), 6)
            if payment <= 0.0001:
                continue

            # 1) Debit the borrower (seller)
            borrower_filter_or = []
            if credit.get("borrower_id"):
                borrower_filter_or.append({"id": credit["borrower_id"]})
            if credit.get("borrower_wallet"):
                borrower_filter_or.append({"wallet_address": credit["borrower_wallet"]})
            if not borrower_filter_or:
                continue
            await db.users.update_one(
                {"$or": borrower_filter_or},
                {"$inc": {"balance_ton": -payment}},
            )

            # 2) Update the credit document
            new_remaining = round(remaining - payment, 6)
            new_paid = round(float(credit.get("paid") or 0) + payment, 6)
            update_set: Dict[str, Any] = {
                "remaining": max(0.0, new_remaining),
                "paid": new_paid,
                "last_payment": now_iso,
            }
            if new_remaining <= 0:
                update_set["status"] = "paid"
                update_set["remaining"] = 0
                update_set["is_doubled_rate"] = False
                update_set["overdue_since"] = None
            await db.credits.update_one({"id": credit["id"]}, {"$set": update_set})

            # 3) Split payment: interest goes to the bank, principal is a sink
            #    (goes to the government — i.e. nobody is credited). The rule is
            #    "pay interest first, then principal".
            #
            #    interest_total = original principal × interest_rate
            #    interest_remaining = max(0, interest_total - interest_paid_so_far)
            #    interest_part = min(interest_remaining, payment)
            #    principal_part = payment - interest_part
            #
            #    For government credits both parts are sink (legacy behaviour).
            interest_total = round(
                float(credit.get("amount") or 0) * float(credit.get("interest_rate") or 0),
                6,
            )
            # paid BEFORE this payment was applied
            interest_paid_so_far = float(credit.get("paid") or 0)
            interest_remaining = max(0.0, interest_total - interest_paid_so_far)
            interest_part = round(min(interest_remaining, payment), 6)
            # principal_part = payment - interest_part (intentionally not stored — sink)

            if credit.get("lender_type") == "bank" and credit.get("lender_id") and interest_part > 0:
                await db.users.update_one(
                    {"$or": [
                        {"id": credit["lender_id"]},
                        {"wallet_address": credit["lender_id"]},
                    ]},
                    {"$inc": {"balance_ton": interest_part}},
                )

            # 4) History entry — visible in /api/history/transactions
            tx_doc = {
                "id": str(uuid.uuid4()),
                "user_id": credit.get("borrower_id") or "",
                "type": "credit_payment",
                "tx_type": "credit_payment",
                "amount": -payment,
                "amount_ton": payment,
                "status": "completed",
                "created_at": now_iso,
                "credit_id": credit.get("id"),
                "lender_name": credit.get("lender_name") or "",
                "lender_type": credit.get("lender_type") or "government",
                "details": {
                    "lender_type": credit.get("lender_type"),
                    "lender_name": credit.get("lender_name") or "",
                    "credit_remaining_after": max(0.0, new_remaining),
                },
            }
            await db.transactions.insert_one(tx_doc)

            total_deducted += payment
            results.append({
                "credit_id": credit.get("id"),
                "lender_name": credit.get("lender_name") or "",
                "lender_type": credit.get("lender_type") or "government",
                "deduction_percent": round(pct * 100, 2),
                "amount": payment,
                "remaining_after": max(0.0, new_remaining),
                "fully_paid": new_remaining <= 0,
            })

            logger.info(
                "credit_payment: credit=%s borrower=%s -%s TON (source=%s)",
                str(credit.get("id"))[:8],
                str(seller_id)[:8],
                round(payment, 4),
                source,
            )

        return round(total_deducted, 6), results
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("apply_credit_deduction failed: %s", exc)
        return 0.0, []
