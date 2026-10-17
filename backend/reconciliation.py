"""GRAM City — payments reconciliation («Сверка» in the admin).

Answers two questions every day (and on demand):

1. Can the project pay everyone?
   liabilities = all players' REAL balances + withdrawals waiting to be paid
   assets      = on-chain balance of the project wallets (Toncenter)
   coverage    = assets − liabilities  (negative = not enough TON to pay out)

2. Is anything stuck or uncertain?
   • deposits in status "crediting" (claimed but the credit did not finish);
   • deposits from unknown senders ("pending");
   • withdrawals stuck in "processing" longer than STUCK_MINUTES;
   • withdrawals in "needs_review" (payout sent or possibly sent, bookkeeping
     failed — never refunded automatically).

For the review items the admin gets explicit actions, each an atomic status
transition so a double click can never pay twice:
   deposit  "crediting"    → credit   (credit now)        | dismiss
   withdraw "needs_review" → confirm  (mark completed)    | refund (return to balance)

A daily job runs the report and messages the admins in Telegram when coverage
is below the threshold or something needs review.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

STUCK_MINUTES = 15
DEFAULT_SETTINGS = {
    "wallets": [],                 # extra project wallet addresses to count as assets
    "alert_coverage_ton": 0.0,     # alert when coverage < this (TON)
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def get_settings(db) -> Dict[str, Any]:
    doc = await db.admin_settings.find_one({"type": "reconciliation"}, {"_id": 0}) or {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in doc.items() if k in DEFAULT_SETTINGS}}


async def project_wallets(db) -> List[str]:
    """Deposit/receiver addresses from the game settings + admin-added ones."""
    out: List[str] = []
    for doc in await db.game_settings.find({"type": {"$in": ["ton_wallet", "contract"]}}, {"_id": 0}).to_list(10):
        for k in ("receiver_address", "wallet_address", "address", "deposit_address", "contract_address"):
            v = doc.get(k)
            if isinstance(v, str) and len(v) > 20:
                out.append(v)
    for a in await db.admin_wallets.find({}, {"_id": 0, "address": 1, "wallet_address": 1}).to_list(100):
        v = a.get("address") or a.get("wallet_address")
        if isinstance(v, str) and len(v) > 20:
            out.append(v)
    out += [w for w in (await get_settings(db))["wallets"] if isinstance(w, str) and len(w) > 20]
    return list(dict.fromkeys(out))


async def onchain_balance(address: str) -> Optional[float]:
    endpoint = os.environ.get("TONCENTER_API_ENDPOINT", "https://toncenter.com/api/v2").rstrip("/")
    headers = {"X-API-Key": os.environ["TONCENTER_API_KEY"]} if os.environ.get("TONCENTER_API_KEY") else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{endpoint}/getAddressBalance", params={"address": address}, headers=headers)
            if r.status_code == 200 and r.json().get("ok"):
                return int(r.json().get("result", 0) or 0) / 1e9
    except Exception as e:
        logger.warning(f"reconciliation: balance of {address[:10]}… failed: {e}")
    return None


async def report(db) -> Dict[str, Any]:
    now = _now()
    s = await get_settings(db)
    # liabilities
    # sums computed by MongoDB (one aggregation each) instead of streaming
    # every user / transaction document into Python
    agg = await db.users.aggregate([{"$group": {"_id": None,
                                                "real": {"$sum": "$balance_ton"},
                                                "bonus": {"$sum": "$bonus_balance"}}}]).to_list(1)
    real = float((agg[0] if agg else {}).get("real", 0) or 0)
    bonus = float((agg[0] if agg else {}).get("bonus", 0) or 0)
    # withdrawals waiting to be paid: amount_ton (new records) or amount (old records)
    _wq = {"tx_type": {"$in": ["withdrawal", "instant_withdrawal"]}, "status": {"$in": ["pending", "processing"]}}
    _a1 = await db.transactions.aggregate([{"$match": {**_wq, "amount_ton": {"$exists": True}}},
                                           {"$group": {"_id": None, "s": {"$sum": "$amount_ton"}}}]).to_list(1)
    _a2 = await db.transactions.aggregate([{"$match": {**_wq, "amount_ton": {"$exists": False}}},
                                           {"$group": {"_id": None, "s": {"$sum": "$amount"}}}]).to_list(1)
    pending_w = float((_a1[0] if _a1 else {}).get("s", 0) or 0) + float((_a2[0] if _a2 else {}).get("s", 0) or 0)
    # money frozen for rentals is still the players' money -> a liability
    aggf = await db.users.aggregate([{"$group": {"_id": None, "s": {"$sum": "$frozen_ton"}}}]).to_list(1)
    pending_w += float((aggf[0] if aggf else {}).get("s", 0) or 0)
    # assets
    wallets = []
    assets = 0.0
    unknown = 0
    for a in await project_wallets(db):
        b = await onchain_balance(a)
        wallets.append({"address": a, "balance_ton": b})
        if b is None:
            unknown += 1
        else:
            assets += b
    liabilities = round(real + pending_w, 6)
    coverage = round(assets - liabilities, 6) if wallets and unknown < len(wallets) else None
    # review items
    stuck_cutoff = _iso(now - timedelta(minutes=STUCK_MINUTES))
    crediting = await db.deposits.find({"status": "crediting", "created_at": {"$lt": stuck_cutoff}}, {"_id": 0}).to_list(200)
    unknown_dep = await db.deposits.find({"status": "pending"}, {"_id": 0}).sort("created_at", -1).to_list(50)
    processing = await db.transactions.find({"tx_type": "withdrawal", "status": "processing",
                                             "processing_started": {"$lt": stuck_cutoff}}, {"_id": 0}).to_list(200)
    review = await db.transactions.find({"status": "needs_review"}, {"_id": 0}).sort("needs_review_at", -1).to_list(200)
    alerts = []
    if coverage is not None and coverage < float(s["alert_coverage_ton"]):
        alerts.append({"level": "critical", "text": f"Не хватает TON на кошельках проекта: покрытие {coverage:.4f} TON."})
    if wallets and unknown:
        alerts.append({"level": "warning", "text": f"Не удалось получить баланс {unknown} из {len(wallets)} кошельков (Toncenter)."})
    if not wallets:
        alerts.append({"level": "warning", "text": "Не задано ни одного кошелька проекта — покрытие не считается. Добавьте адреса в настройках сверки."})
    if crediting:
        alerts.append({"level": "warning", "text": f"Пополнений, зачисление которых не завершилось: {len(crediting)}."})
    if processing:
        alerts.append({"level": "warning", "text": f"Выводов, зависших в обработке дольше {STUCK_MINUTES} мин: {len(processing)}."})
    if review:
        alerts.append({"level": "critical", "text": f"Выводов, требующих проверки (выплата могла уйти): {len(review)}."})
    return {
        "at": _iso(now),
        "liabilities": {"real_balances_ton": round(real, 6), "pending_withdrawals_ton": round(pending_w, 6),
                        "total_ton": liabilities, "bonus_balances_ton": round(bonus, 6)},
        "assets": {"wallets": wallets, "total_ton": round(assets, 6)},
        "coverage_ton": coverage,
        "review": {
            "deposits_crediting": crediting, "deposits_unknown_sender": unknown_dep,
            "withdrawals_processing": processing, "withdrawals_needs_review": review,
        },
        "alerts": alerts, "settings": s,
    }


# ───────────────────────────── admin actions (atomic) ─────────────────────────────
async def _log(db, admin, action: str, target: str, extra: Dict[str, Any]) -> None:
    try:
        await db.admin_logs.insert_one({"id": str(uuid.uuid4()), "action": action, "target": target,
                                        "admin": getattr(admin, "username", None) or getattr(admin, "id", None),
                                        "details": extra, "timestamp": _iso(_now())})
    except Exception:
        pass


async def resolve_deposit(db, admin, deposit_id: str, action: str) -> Dict[str, Any]:
    if action not in ("credit", "dismiss"):
        raise HTTPException(status_code=400, detail="action must be credit or dismiss")
    new_status = "completed" if action == "credit" else "dismissed"
    d = await db.deposits.find_one_and_update({"id": deposit_id, "status": "crediting"},
                                              {"$set": {"status": new_status, "resolved_at": _iso(_now()),
                                                        "resolved_by": getattr(admin, "id", None)}})
    if not d:
        raise HTTPException(status_code=409, detail="Пополнение уже обработано")
    if action == "credit":
        amt = float(d.get("amount_ton", 0) or 0)
        await db.users.update_one({"id": d["user_id"]}, {"$inc": {"balance_ton": amt, "total_deposited": amt}})
    await _log(db, admin, f"deposit_{action}", deposit_id, {"amount_ton": d.get("amount_ton"), "user_id": d.get("user_id")})
    return {"ok": True, "status": new_status}


async def resolve_withdrawal(db, admin, tx_id: str, action: str) -> Dict[str, Any]:
    if action not in ("confirm", "refund"):
        raise HTTPException(status_code=400, detail="action must be confirm or refund")
    new_status = "completed" if action == "confirm" else "refunded"
    t = await db.transactions.find_one_and_update(
        {"id": tx_id, "status": {"$in": ["needs_review", "processing"]}},
        {"$set": {"status": new_status, "resolved_at": _iso(_now()), "resolved_by": getattr(admin, "id", None),
                  **({"completed_at": _iso(_now())} if action == "confirm" else {})}})
    if not t:
        raise HTTPException(status_code=409, detail="Заявка уже обработана")
    if action == "refund":
        amt = float(t.get("amount_ton", t.get("amount", 0)) or 0)
        if t.get("user_id"):
            await db.users.update_one({"id": t["user_id"]}, {"$inc": {"balance_ton": amt}})
    await _log(db, admin, f"withdrawal_{action}", tx_id, {"amount_ton": t.get("amount_ton"), "user_id": t.get("user_id"),
                                                         "blockchain_hash": t.get("blockchain_hash")})
    return {"ok": True, "status": new_status}


async def daily_check(db) -> Dict[str, Any]:
    """Scheduled: run the report, message admins if something is wrong."""
    rep = await report(db)
    bad = [a for a in rep["alerts"] if a["level"] in ("critical", "warning")]
    if bad:
        try:
            from core.notify import notify_user_background
            text = "\n".join("• " + a["text"] for a in bad)
            async for adm in db.users.find({"is_admin": True}, {"_id": 0, "id": 1}):
                notify_user_background(db, adm["id"], title="🧾 Сверка платежей: нужна проверка",
                                       message=text, type_key="reconciliation_alert", priority="warning")
        except Exception as e:
            logger.warning(f"reconciliation alert failed: {e}")
    await db.reconciliation_runs.insert_one({"at": rep["at"], "coverage_ton": rep["coverage_ton"],
                                             "liabilities_ton": rep["liabilities"]["total_ton"],
                                             "assets_ton": rep["assets"]["total_ton"],
                                             "alerts": [a["text"] for a in rep["alerts"]]})
    return {"alerts": len(bad)}


def create_reconciliation_router(db, get_current_admin) -> APIRouter:
    r = APIRouter(prefix="/api/admin/reconciliation", tags=["reconciliation"])

    @r.get("/report")
    async def get_report(_=Depends(get_current_admin)):
        rep = await report(db)
        rep["history"] = await db.reconciliation_runs.find({}, {"_id": 0}).sort("at", -1).limit(14).to_list(14)
        return rep

    @r.put("/settings")
    async def put_settings(patch: Dict[str, Any], _=Depends(get_current_admin)):
        upd = {}
        if "wallets" in patch:
            if not isinstance(patch["wallets"], list) or any(not isinstance(w, str) for w in patch["wallets"]):
                raise HTTPException(status_code=400, detail="wallets must be a list of addresses")
            upd["wallets"] = [w.strip() for w in patch["wallets"] if w.strip()]
        if "alert_coverage_ton" in patch:
            try:
                upd["alert_coverage_ton"] = float(patch["alert_coverage_ton"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="alert_coverage_ton must be a number")
        await db.admin_settings.update_one({"type": "reconciliation"}, {"$set": {"type": "reconciliation", **upd}}, upsert=True)
        return await get_settings(db)

    @r.post("/deposits/{deposit_id}/{action}")
    async def act_deposit(deposit_id: str, action: str, admin=Depends(get_current_admin)):
        return await resolve_deposit(db, admin, deposit_id, action)

    @r.post("/withdrawals/{tx_id}/{action}")
    async def act_withdrawal(tx_id: str, action: str, admin=Depends(get_current_admin)):
        return await resolve_withdrawal(db, admin, tx_id, action)

    @r.post("/run")
    async def run_now(_=Depends(get_current_admin)):
        return await daily_check(db)

    return r
