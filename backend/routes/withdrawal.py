"""
Withdrawal routes module
Handles all withdrawal-related endpoints with 2FA protection
"""
import uuid
import pyotp
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional

from core.dependencies import get_current_user
from core.models import User, WithdrawRequest, InstantWithdrawRequest
from core.helpers import get_user_identifiers, get_user_filter, nz_or
from game_systems import BankingSystem
from security.totp_crypto import decrypt_secret

logger = logging.getLogger(__name__)


def create_withdrawal_router(db):
    """Create withdrawal routes with database access"""
    
    router = APIRouter(prefix="/api", tags=["withdrawal"])
    
    @router.get("/banks")
    async def get_banks():
        """Get banks available for instant withdrawal"""
        banks = await db.businesses.find(
            {"business_type": {"$in": ["gram_bank", "dex", "bank"]}},
            {"_id": 0}
        ).to_list(50)
        return {"banks": banks}
    
    @router.post("/withdraw/instant")
    async def instant_withdrawal(
        data: InstantWithdrawRequest,
        request: Request,
        current_user: User = Depends(get_current_user)
    ):
        """Create instant withdrawal via bank"""
        bank_id = data.bank_id
        amount = data.amount
        totp_code = data.totp_code
        
        # Get user
        user = await db.users.find_one(
            {"id": current_user.id},
            {"_id": 0}
        )
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        # Check 2FA - REQUIRED for withdrawal
        totp_secret = user.get("two_factor_secret") or user.get("totp_secret")
        totp_secret = decrypt_secret(totp_secret) if totp_secret else totp_secret
        is_2fa_enabled = user.get("is_2fa_enabled", False)
        has_passkey = bool(user.get("passkeys") and len(user.get("passkeys", [])) > 0)
        
        if not is_2fa_enabled and not has_passkey:
            raise HTTPException(status_code=403, detail="Для вывода средств необходимо включить 2FA аутентификацию в настройках безопасности")
        
        # Verify 2FA code if user has TOTP enabled
        if is_2fa_enabled and totp_secret:
            if not totp_code:
                raise HTTPException(status_code=400, detail="Требуется код 2FA для мгновенного вывода")
            
            # Verify TOTP
            totp = pyotp.TOTP(totp_secret)
            
            if not totp.verify(totp_code.strip(), valid_window=3):
                raise HTTPException(status_code=400, detail="Неверный код 2FA")
        
        # Check balance
        if user.get("balance_ton", 0) < amount:
            raise HTTPException(status_code=400, detail="Недостаточно средств")
        
        # Get bank
        bank = await db.businesses.find_one({"id": bank_id}, {"_id": 0})
        if not bank or bank.get("business_type") not in ["gram_bank", "dex", "bank"]:
            raise HTTPException(status_code=404, detail="Банк не найден")
        
        # Check bank can process
        can_process, reason = BankingSystem.can_process_instant(bank, amount)
        if not can_process:
            raise HTTPException(status_code=400, detail=reason)
        
        user_id = user.get("id", str(user.get("_id")))
        
        # Create withdrawal
        withdrawal = BankingSystem.create_withdrawal_request(
            user_id,
            amount,
            "instant"
        )
        withdrawal["bank_id"] = bank_id
        withdrawal["bank_owner"] = bank.get("owner")
        withdrawal["type"] = "withdrawal"
        withdrawal["amount"] = -amount
        withdrawal["description"] = f"Мгновенный вывод {amount} TON через банк"
        
        # Calculate fees
        PLATFORM_FEE = 0.03
        platform_commission = amount * PLATFORM_FEE
        bank_fee = withdrawal["bank_fee"]
        net_amount = withdrawal["net_amount"]
        
        # Deduct from user balance
        user_filter = get_user_filter(user)
        await db.users.update_one(user_filter, {"$inc": {"balance_ton": -amount}})
        
        # Store withdrawal
        withdrawal_doc = {
            **withdrawal, 
            "tx_type": "instant_withdrawal",
            "user_wallet": user.get("wallet_address"),
            "user_id": user_id
        }
        await db.transactions.insert_one(withdrawal_doc)
        
        logger.info(f"✅ Instant withdrawal created: {amount} TON for user {user_id}")
        
        return {
            "status": "processing",
            "withdrawal_id": withdrawal["id"],
            "type": "instant",
            "amount": amount,
            "net_amount": withdrawal["net_amount"],
            "bank_fee": bank_fee,
            "platform_commission": withdrawal["platform_commission"],
            "new_balance": user.get("balance_ton", 0) - amount
        }
    
    @router.get("/withdrawals/queue")
    async def get_withdrawal_queue(current_user: User = Depends(get_current_user)):
        """Get user's withdrawal queue"""
        withdrawals = await db.transactions.find(
            {
                "user_id": current_user.id,
                "tx_type": {"$in": ["withdrawal", "instant_withdrawal"]}
            },
            {"_id": 0}
        ).sort("created_at", -1).to_list(20)
        return {"withdrawals": withdrawals}
    
    @router.post("/withdraw")
    async def create_withdraw(
        data: WithdrawRequest,
        request: Request,
        current_user: User = Depends(get_current_user)
    ):
        """Create standard withdrawal request with 2FA protection"""
        # Get user
        user = await db.users.find_one(
            {"id": current_user.id},
            {"_id": 0}
        )
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        # Check 2FA - REQUIRED for withdrawal
        totp_secret = user.get("two_factor_secret") or user.get("totp_secret")
        totp_secret = decrypt_secret(totp_secret) if totp_secret else totp_secret
        is_2fa_enabled = user.get("is_2fa_enabled", False)
        has_passkey = bool(user.get("passkeys") and len(user.get("passkeys", [])) > 0)
        
        if not is_2fa_enabled and not has_passkey:
            raise HTTPException(status_code=403, detail="Для вывода средств необходимо включить 2FA аутентификацию в настройках безопасности")
        
        # Verify 2FA code if user has TOTP enabled
        if is_2fa_enabled and totp_secret:
            if not data.totp_code:
                raise HTTPException(status_code=400, detail="Требуется код 2FA для вывода средств")
            
            # Verify TOTP
            totp = pyotp.TOTP(totp_secret)
            
            if not totp.verify(data.totp_code.strip() if data.totp_code else "", valid_window=3):
                raise HTTPException(status_code=400, detail="Неверный код 2FA")
        
        # Check wallet
        wallet = user.get("wallet_address")
        if not wallet:
            raise HTTPException(status_code=400, detail="Подключите кошелёк для вывода средств")
        
        # Check balance — account for credit debt and tender escrow
        balance_ton = float(user.get("balance_ton", 0) or 0)
        from frozen_tenders import effective_frozen_city
        frozen_city = await effective_frozen_city(db, user)
        frozen_ton_locked = frozen_city / 1000.0
        # Active credit debt
        try:
            active_credits = await db.credits.find(
                {"$or": nz_or([{"borrower_id": user.get("id")}, {"borrower_wallet": user.get("wallet_address")}]),
                 "status": {"$in": ["active", "overdue"]}},
                {"_id": 0}
            ).to_list(20)
        except Exception:
            active_credits = []
        total_debt = sum(c.get("remaining_amount") or c.get("remaining") or 0 for c in active_credits)
        available_for_withdraw = max(0.0, balance_ton - total_debt - frozen_ton_locked)
        if data.amount > available_for_withdraw + 1e-9:
            parts = [f"баланс {balance_ton:.2f}"]
            if total_debt > 0:
                parts.append(f"долг {total_debt:.2f}")
            if frozen_ton_locked > 0:
                parts.append(f"заморожено в контрактах {frozen_ton_locked:.4f}")
            breakdown = " − ".join(parts)
            raise HTTPException(
                status_code=400,
                detail=(f"Недостаточно средств. Доступно к выводу: {available_for_withdraw:.4f} TON ({breakdown})")
            )
        
        # Check minimum
        MIN_WITHDRAWAL = 1.0
        if data.amount < MIN_WITHDRAWAL:
            raise HTTPException(status_code=400, detail=f"Минимальная сумма вывода: {MIN_WITHDRAWAL} TON")
        
        user_id = user.get("id", str(user.get("_id")))
        
        # Create withdrawal — apply tax_break (patron) × gateway_code (resource) multipliers
        WITHDRAWAL_FEE = 0.03
        fee_rate = WITHDRAWAL_FEE
        try:
            # Import here to avoid circular dependency at module load
            from server import get_user_active_buffs_all  # type: ignore
            user_buffs = await get_user_active_buffs_all(user_id)
            for b in user_buffs:
                eff = (b or {}).get("effect") or {}
                if eff.get("type") == "withdrawal_fee_multiplier":
                    try:
                        fee_rate *= float(eff.get("value", 1.0))
                    except (TypeError, ValueError):
                        pass
        except Exception as _e:
            logger.warning(f"withdrawal buff lookup failed: {_e}")
        fee = round(data.amount * fee_rate, 6)
        net_amount = round(data.amount - fee, 6)
        
        withdrawal = {
            "id": str(uuid.uuid4()),
            "type": "withdrawal",
            "tx_type": "withdrawal",
            "user_id": user_id,
            "user_wallet": wallet,
            "amount": data.amount,
            "amount_ton": -data.amount,
            "fee": fee,
            "net_amount": net_amount,
            "to_address": wallet,
            "to_address_raw": user.get("raw_address", wallet),
            "status": "pending",
            "description": f"Вывод {data.amount} TON",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Deduct from balance
        user_filter = get_user_filter(user)
        await db.users.update_one(user_filter, {"$inc": {"balance_ton": -data.amount}})
        
        # Store withdrawal
        await db.transactions.insert_one({**withdrawal, "tx_type": "withdrawal"})
        
        logger.info(f"✅ Withdrawal created: {data.amount} TON for user {user_id}")

        # Anti-multi-account fingerprint on withdraw (best-effort)
        try:
            from antifraud import record_event as antifraud_record_event, verify_turnstile, get_client_ip
            ts_result = await verify_turnstile(getattr(data, "turnstile_token", None), get_client_ip(request))
            await antifraud_record_event(
                db,
                event_type="withdraw",
                request=request,
                user=user,
                visitor_id=getattr(data, "visitor_id", None),
                turnstile=ts_result,
                extra={"amount": data.amount, "kind": "standard"},
            )
        except Exception as e:
            logger.warning("antifraud.withdraw failed: %s", e)

        return {
            "status": "pending",
            "withdrawal_id": withdrawal["id"],
            "net_amount": net_amount,
            "to_address": wallet,
            "to_address_raw": user.get("raw_address", wallet),
            "new_balance": user.get("balance_ton", 0) - data.amount
        }
    
    return router
