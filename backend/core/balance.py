"""Единая логика списания $CITY/TON: сначала бонусный баланс, затем реальный.

Правило: «Недостаточно средств» — только если бонус + доступный реальный
баланс меньше стоимости. Иначе списываем весь бонус, остаток — с реального.
Атомарно (find_one_and_update), без ошибок округления float.
"""
from __future__ import annotations

from typing import Any, Dict

from pymongo import ReturnDocument

EPS = 1e-9
CITY_PER_TON = 1000.0


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def split_amounts(bonus: float, real_available: float, amount: float) -> Dict[str, Any]:
    """Расчёт частей платежа. bonus/real_available/amount — в TON."""
    bonus = max(0.0, _f(bonus))
    real_available = max(0.0, _f(real_available))
    amount = _f(amount)
    if bonus + real_available + EPS < amount:
        return {"ok": False, "from_bonus": 0.0, "from_real": 0.0}
    if bonus >= amount:
        return {"ok": True, "from_bonus": amount, "from_real": 0.0}
    # Списываем ВЕСЬ бонус ровно по сохранённому значению (без округления),
    # остаток — с реального (с защитой от погрешности float).
    from_real = amount - bonus
    if from_real > real_available:
        from_real = real_available
    return {"ok": True, "from_bonus": bonus, "from_real": from_real}


async def debit_user_split(
    db,
    match: dict,
    amount: float,
    *,
    use_bonus: bool = True,
    respect_frozen: bool = True,
    extra_update: dict | None = None,
) -> Dict[str, Any]:
    """Атомарное списание `amount` TON: бонус → реальный.

    Возвращает {ok, from_bonus, from_real, bonus_balance, balance_ton} либо
    {ok: False, reason: 'insufficient'|'user_not_found'|'race', bonus_balance, balance_ton}.
    `extra_update` — дополнительные операторы ($push/$set/...) в том же апдейте.
    """
    amount = _f(amount)
    # Legacy/drifted accounts may store balance fields as explicit `null`.
    # Mongo `$inc` fails on null and `$gte` filters never match it, so the
    # real-balance leg of a split payment would silently break. Coerce to a
    # numeric 0 first (idempotent, only touches null values).
    # Safety guard: a match like {"wallet_address": None} selects ANY user without
    # a wallet (every email-only player) — debiting with it could charge a
    # stranger. Refuse such matches instead of touching someone else's balance.
    if not match or any(v is None or v == "" for v in match.values()):
        return {"ok": False, "reason": "user_not_found", "bonus_balance": 0.0, "balance_ton": 0.0}
    await db.users.update_one({**match, "bonus_balance": None}, {"$set": {"bonus_balance": 0.0}})
    await db.users.update_one({**match, "balance_ton": None}, {"$set": {"balance_ton": 0.0}})
    proj = {"_id": 0, "bonus_balance": 1, "balance_ton": 1, "frozen_city_for_tenders": 1}
    if amount <= 0:
        u = await db.users.find_one(match, proj)
        if u is None:
            return {"ok": False, "reason": "user_not_found"}
        if extra_update:
            await db.users.update_one(match, extra_update)
        return {"ok": True, "from_bonus": 0.0, "from_real": 0.0,
                "bonus_balance": _f(u.get("bonus_balance")), "balance_ton": _f(u.get("balance_ton"))}

    for _ in range(4):
        u = await db.users.find_one(match, proj)
        if not u:
            return {"ok": False, "reason": "user_not_found"}
        bonus = _f(u.get("bonus_balance")) if use_bonus else 0.0
        real = _f(u.get("balance_ton"))
        frozen = _f(u.get("frozen_city_for_tenders")) / CITY_PER_TON if respect_frozen else 0.0
        real_available = max(0.0, real - frozen)
        parts = split_amounts(bonus, real_available, amount)
        if not parts["ok"]:
            return {"ok": False, "reason": "insufficient", "bonus_balance": bonus,
                    "balance_ton": real, "available": bonus + real_available}
        from_bonus, from_real = parts["from_bonus"], parts["from_real"]

        filt: dict = dict(match)
        inc: dict = {}
        if from_bonus > 0:
            filt["bonus_balance"] = {"$gte": from_bonus - EPS}
            inc["bonus_balance"] = -from_bonus
        if from_real > 0:
            filt["balance_ton"] = {"$gte": from_real + frozen - EPS}
            inc["balance_ton"] = -from_real
        update: dict = {"$inc": inc} if inc else {}
        for k, v in (extra_update or {}).items():
            if k == "$inc":
                update.setdefault("$inc", {}).update(v)
            else:
                update[k] = v
        try:
            res = await db.users.find_one_and_update(
                filt, update, return_document=ReturnDocument.AFTER, projection=proj,
            )
        except Exception as e:                       # FerretDB (test setups): findAndModify without "fields"
            if getattr(e, "code", None) != 238:
                raise
            res = await db.users.find_one_and_update(filt, update, return_document=ReturnDocument.AFTER)
        if res:
            return {"ok": True, "from_bonus": from_bonus, "from_real": from_real,
                    "bonus_balance": _f(res.get("bonus_balance")), "balance_ton": _f(res.get("balance_ton"))}
    return {"ok": False, "reason": "race"}


async def refund_split(db, match: dict, from_bonus: float, from_real: float) -> None:
    """Откат списания (например, если следующий шаг покупки не удался)."""
    inc = {}
    if _f(from_bonus) > 0:
        inc["bonus_balance"] = _f(from_bonus)
    if _f(from_real) > 0:
        inc["balance_ton"] = _f(from_real)
    if inc:
        await db.users.update_one(match, {"$inc": inc})


def total_available_ton(user_doc: dict, respect_frozen: bool = True) -> float:
    """Бонус + реальный (минус заморозка по контрактам) в TON."""
    if not user_doc:
        return 0.0
    bonus = _f(user_doc.get("bonus_balance"))
    real = _f(user_doc.get("balance_ton"))
    frozen = _f(user_doc.get("frozen_city_for_tenders")) / CITY_PER_TON if respect_frozen else 0.0
    return bonus + max(0.0, real - frozen)


def insufficient_detail(lang: str | None, need_ton: float, have_ton: float) -> dict:
    """Структурированная ошибка «Недостаточно средств» (локализуется фронтом и бэком)."""
    from core.notif_i18n import label
    need_city = round(need_ton * CITY_PER_TON, 2)
    have_city = round(max(0.0, have_ton) * CITY_PER_TON, 2)
    return {
        "code": "insufficient_funds",
        "need_city": need_city,
        "have_city": have_city,
        "message": label("insufficient_funds_detail", lang).format(need=f"{need_city:g}", have=f"{have_city:g}"),
    }
