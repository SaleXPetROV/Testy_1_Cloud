"""
Transaction History System
Handles all user transactions: deposits, withdrawals, purchases, sales
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import jwt  # PyJWT (python-jose: unpatched CVEs and not in requirements)
from jwt import PyJWTError as JWTError
import os
import logging

logger = logging.getLogger(__name__)

SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or ''
if not SECRET_KEY:
    from security_middleware import get_or_generate_jwt_secret
    SECRET_KEY = get_or_generate_jwt_secret()
ALGORITHM = "HS256"
from auth_cookie import CookieOrBearer
security = CookieOrBearer(auto_error=False)

# Transaction types
# explicit direction for types whose stored amount is always positive
FORCED_SIGN = {"city_pass_premium": -1, "rental_freeze": -1,
               "quest_reward": 1, "minigame_prize": 1, "rental_payout": 1, "rental_unfreeze": 1, "rental_deposit_to_owner": 1}
HIDDEN_FOR_PLAYER = {"rental_charge", "rental_commission",   # internal moves (already shown by the freeze)
                     "container_open"}                        # a chest opened: no money moved, not shown in the history

TRANSACTION_TYPES = {
    "city_pass_premium": {"name": "City Pass: премиум", "icon": "🎫", "color": "red", "sign": "-"},
    "quest_reward": {"name": "Награда за задание", "icon": "🎯", "color": "green", "sign": "+"},
    "minigame_prize": {"name": "Приз мини-игры", "icon": "🏆", "color": "green", "sign": "+"},
    "league_reward": {"name": "Награда лиги", "icon": "🏆", "color": "green", "sign": "+"},
    "alliance_create": {"name": "Создание альянса", "icon": "🛡️", "color": "red", "sign": "-"},
    "alliance_deposit": {"name": "Взнос в казну альянса", "icon": "🛡️", "color": "red", "sign": "-"},
    "alliance_payout": {"name": "Выплата из казны альянса", "icon": "🛡️", "color": "green", "sign": "+"},
    "alliance_disband": {"name": "Доля казны распущенного альянса", "icon": "🛡️", "color": "green", "sign": "+"},
    "container_open": {"name": "Открыт сундук", "icon": "🎁", "color": "blue", "sign": ""},
    "rental_freeze": {"name": "Аренда: заморозка", "icon": "🔒", "color": "red", "sign": "-"},
    "rental_unfreeze": {"name": "Аренда: разморозка", "icon": "🔓", "color": "green", "sign": "+"},
    "rental_payout": {"name": "Аренда: выплата владельцу", "icon": "🏢", "color": "green", "sign": "+"},
    "rental_deposit_to_owner": {"name": "Аренда: залог владельцу", "icon": "🏢", "color": "green", "sign": "+"},
    "deposit": {"name": "Пополнение", "icon": "💰", "color": "green", "sign": "+"},
    "withdrawal": {"name": "Вывод", "icon": "📤", "color": "red", "sign": "-"},
    "instant_withdrawal": {"name": "Мгновенный вывод", "icon": "⚡", "color": "red", "sign": "-"},
    "land_purchase": {"name": "Покупка земли", "icon": "🏞️", "color": "blue", "sign": "-"},
    "land_sale": {"name": "Продажа земли", "icon": "🏞️", "color": "green", "sign": "+"},
    "land_sale_listing": {"name": "Выставление земли на продажу", "icon": "🏷️", "color": "amber", "sign": "", "hidden": True},
    "plot_purchase": {"name": "Покупка участка", "icon": "🗺️", "color": "blue", "sign": "-", "hidden": True},
    "business_build": {"name": "Строительство бизнеса", "icon": "🏗️", "color": "purple", "sign": "-", "hidden": True},
    "business_upgrade": {"name": "Улучшение бизнеса", "icon": "⬆️", "color": "cyan", "sign": "-"},
    "business_purchase": {"name": "Покупка бизнеса", "icon": "🏢", "color": "blue", "sign": "-"},
    "resource_sale": {"name": "Продажа ресурсов", "icon": "📦", "color": "green", "sign": "+"},
    "resource_purchase": {"name": "Покупка ресурсов", "icon": "🛒", "color": "orange", "sign": "-"},
    "patron_fee": {"name": "Плата покровителю", "icon": "🤝", "color": "yellow", "sign": "-"},
    "warehouse_purchase": {"name": "Покупка склада", "icon": "🏭", "color": "blue", "sign": "-", "hidden": True},
    "warehouse_upgrade": {"name": "Улучшение склада", "icon": "📈", "color": "cyan", "sign": "-", "hidden": True},
    "tax": {"name": "Налог", "icon": "📋", "color": "red", "sign": "-", "hidden": True},
    "reward": {"name": "Награда", "icon": "🎁", "color": "gold", "sign": "+", "hidden": True},
    "trade": {"name": "Торговля", "icon": "💹", "color": "teal", "sign": "", "hidden": True},
    "repair": {"name": "Ремонт", "icon": "🔧", "color": "gray", "sign": "-"},
    "credit_taken": {"name": "Получение кредита", "icon": "🏦", "color": "blue", "sign": "+"},
    "credit_payment": {"name": "Погашение кредита", "icon": "💳", "color": "red", "sign": "-"},
    "business_seized": {"name": "Конфискация бизнеса", "icon": "⚖️", "color": "red", "sign": ""},
    "referral_bonus": {"name": "Реферальный бонус", "icon": "👥", "color": "green", "sign": "+", "hidden": True},
    "income_collection": {"name": "Сбор дохода", "icon": "💵", "color": "green", "sign": "+", "hidden": True},
    "business_sale": {"name": "Продажа бизнеса", "icon": "🏢", "color": "green", "sign": "+"},
    "promo_activation": {"name": "Активация промокода", "icon": "🎫", "color": "green", "sign": "+"},
    "contract_payment_in": {"name": "Продажа ресурсов", "icon": "📦", "color": "green", "sign": "+"},
    "contract_payment_out": {"name": "Покупка ресурсов", "icon": "🛒", "color": "orange", "sign": "-"},
}


def create_history_router(db):
    """Factory function to create transaction history routes"""
    
    history_router = APIRouter(prefix="/api/history", tags=["history"])
    
    async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        if not credentials:
            raise HTTPException(status_code=401, detail="Not authenticated")
        try:
            payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
            identifier: str = payload.get("sub")
            if not identifier:
                raise HTTPException(status_code=401, detail="Invalid token")
            token_sid = payload.get("sid")
            
            user_doc = await db.users.find_one({
                "$or": [
                    {"wallet_address": identifier},
                    {"email": identifier},
                    {"username": identifier}
                ]
            })
            
            if not user_doc:
                raise HTTPException(status_code=404, detail="User not found")
            
            current_sid = user_doc.get("session_id")
            # Single-session enforcement DISABLED — token valid until logout.
            if False and token_sid and current_sid and token_sid != current_sid:
                raise HTTPException(status_code=401, detail="SESSION_OVERRIDDEN")
            if token_sid and not current_sid:
                await db.users.update_one({"_id": user_doc["_id"]}, {"$set": {"session_id": token_sid}})
            
            return {
                "id": user_doc.get("id", str(user_doc.get("_id"))),
                "wallet_address": user_doc.get("wallet_address"),
                "email": user_doc.get("email"),
                "username": user_doc.get("username")
            }
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")
    
    @history_router.get("/transactions")
    async def get_transactions(
        page: int = Query(1, ge=1),
        limit: int = Query(20, ge=1, le=100),
        type_filter: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        current_user: dict = Depends(get_current_user)
    ):
        """Get paginated transaction history"""
        # Build identity-match: tx may store user reference under several keys
        # depending on legacy / new flows (market_purchase uses from_address+seller_id, etc.)
        uid = current_user["id"]
        wallet = current_user.get("wallet_address") or ""
        email = current_user.get("email") or ""
        identity_values = [v for v in (uid, wallet, email) if v]
        # Modern transactions (e.g. tender contract clearing) write a dedicated
        # `user_id` field that owns the entry — only the matching user should
        # see it. Legacy / shared transactions (market_purchase, etc.) have no
        # `user_id` field; for those we still fall back to buyer/seller/from/to
        # address matches.
        ownership_or = [
            {"user_id": uid},
            {"$and": [
                {"$or": [
                    {"user_id": {"$exists": False}},
                    {"user_id": None},
                ]},
                {"$or": [
                    {"from_address": {"$in": identity_values}},
                    {"to_address": {"$in": identity_values}},
                    {"buyer_id": {"$in": identity_values}},
                    {"seller_id": {"$in": identity_values}},
                ]},
            ]},
        ]
        query = {"$or": ownership_or, "tx_type": {"$nin": list(HIDDEN_FOR_PLAYER)}}   # internal rental moves hidden

        # Type filter (matches both legacy `tx_type` and new `type` field;
        # also accepts the unified label "resource_purchase" for both market_purchase docs).
        if type_filter and type_filter in TRANSACTION_TYPES:
            type_aliases = {
                "resource_purchase": ["resource_purchase", "market_purchase"],
                "resource_sale":     ["resource_sale", "market_purchase"],
            }.get(type_filter, [type_filter])
            query["$and"] = [{"$or": [
                {"type": {"$in": type_aliases}},
                {"tx_type": {"$in": type_aliases}},
            ]}]
        
        # Date filters
        if date_from:
            query["created_at"] = {"$gte": date_from}
        if date_to:
            if "created_at" in query:
                query["created_at"]["$lte"] = date_to
            else:
                query["created_at"] = {"$lte": date_to}
        
        # Get total count
        total = await db.transactions.count_documents(query)
        
        # Get transactions
        skip = (page - 1) * limit
        transactions = await db.transactions.find(
            query,
            {"_id": 0}
        ).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
        
        # Enrich with type info
        for tx in transactions:
            tx_type = tx.get("type") or tx.get("tx_type") or "trade"
            # Map tx_type from database to proper type
            if tx_type == "withdrawal" or tx.get("tx_type") == "withdrawal":
                tx_type = "withdrawal"
            elif tx_type == "instant_withdrawal" or tx.get("tx_type") == "instant_withdrawal":
                tx_type = "instant_withdrawal"
            elif tx_type == "deposit":
                tx_type = "deposit"
            # Resource market purchases — distinguish buyer vs seller perspective
            if tx_type == "market_purchase":
                buyer_match = tx.get("from_address") in identity_values or tx.get("buyer_id") in identity_values
                seller_match = tx.get("to_address") in identity_values or tx.get("seller_id") in identity_values
                # buyer perspective wins if both match (user buying their own listing is impossible)
                tx_type = "resource_purchase" if buyer_match else ("resource_sale" if seller_match else "trade")
            
            type_info = TRANSACTION_TYPES.get(tx_type, TRANSACTION_TYPES.get("trade", {"name": "Операция", "icon": "💱", "color": "gray", "sign": ""}))
            tx["tx_type"] = tx_type
            tx["type_name"] = type_info["name"]
            tx["type_icon"] = type_info["icon"]
            tx["type_color"] = type_info["color"]
            
            # Add human-readable status for withdrawals
            status = tx.get("status", "completed")
            tx["status_key"] = status or "completed"
            if tx_type in ["withdrawal", "instant_withdrawal"]:
                if status == "pending":
                    tx["status_display"] = "В ожидании"
                    tx["status_color"] = "yellow"
                elif status == "processing":
                    tx["status_display"] = "Обрабатывается"
                    tx["status_color"] = "blue"
                elif status == "completed":
                    tx["status_display"] = "Одобрено"
                    tx["status_color"] = "green"
                elif status == "failed":
                    tx["status_display"] = "Ошибка"
                    tx["status_color"] = "red"
                elif status == "rejected":
                    tx["status_display"] = "Отклонено"
                    tx["status_color"] = "red"
                else:
                    tx["status_display"] = status
                    tx["status_color"] = "gray"
            else:
                tx["status_display"] = "Выполнено"
                tx["status_color"] = "green"
            
            # Ensure amount field exists (fallback to amount_ton)
            if "amount" not in tx:
                tx["amount"] = tx.get("amount_ton", 0)
            
            # Ensure correct sign for amount based on transaction type
            amount = tx.get("amount", 0)
            sign = type_info.get("sign", "")
            
            # Force negative for withdrawals, positive for deposits
            if tx_type in FORCED_SIGN:
                tx["amount"] = FORCED_SIGN[tx_type] * abs(float(amount or 0))
            elif tx_type in ["withdrawal", "instant_withdrawal"] and amount > 0:
                tx["amount"] = -abs(amount)
            elif tx_type == "deposit" and amount < 0:
                tx["amount"] = abs(amount)
            elif tx_type == "resource_purchase":
                # Buyer pays: amount must be negative.
                tx["amount"] = -abs(amount)
            elif tx_type == "resource_sale":
                # Seller receives net (after tax AND credit deduction). Use the
                # explicit `seller_net_after_credit` if present (set by the
                # market_purchase handler); otherwise fall back to amount - tax.
                if "seller_net_after_credit" in tx and tx["seller_net_after_credit"] is not None:
                    tx["amount"] = float(tx["seller_net_after_credit"])
                else:
                    tax_val = float(tx.get("tax", 0) or 0)
                    tx["amount"] = abs(amount) - tax_val
        
        # Enrich details for resource / land / contract
        for tx in transactions:
            await _enrich_details(tx)
        
        return {
            "transactions": transactions,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
    
    @history_router.get("/transactions/{transaction_id}")
    async def get_transaction_details(transaction_id: str, current_user: dict = Depends(get_current_user)):
        """Get detailed transaction info"""
        uid = current_user["id"]
        wallet = current_user.get("wallet_address") or ""
        email = current_user.get("email") or ""
        identity_values = [v for v in (uid, wallet, email) if v]
        tx = await db.transactions.find_one(
            {
                "id": transaction_id,
                "$or": [
                    {"user_id": uid},
                    {"$and": [
                        {"$or": [{"user_id": {"$exists": False}}, {"user_id": None}]},
                        {"$or": [
                            {"from_address": {"$in": identity_values}},
                            {"to_address": {"$in": identity_values}},
                            {"buyer_id": {"$in": identity_values}},
                            {"seller_id": {"$in": identity_values}},
                        ]},
                    ]},
                ],
            },
            {"_id": 0}
        )
        
        if not tx:
            raise HTTPException(status_code=404, detail="Транзакция не найдена")
        
        tx_type = tx.get("type") or tx.get("tx_type") or "trade"
        if tx_type == "market_purchase":
            buyer_match = tx.get("from_address") in identity_values or tx.get("buyer_id") in identity_values
            tx_type = "resource_purchase" if buyer_match else "resource_sale"
        type_info = TRANSACTION_TYPES.get(tx_type, TRANSACTION_TYPES["trade"])
        tx["tx_type"] = tx_type
        tx["type_name"] = type_info["name"]
        tx["type_icon"] = type_info["icon"]
        tx["type_color"] = type_info["color"]

        # Match list endpoint: apply tax/sign so the detail amount equals what the user sees in the list.
        if "amount" not in tx:
            tx["amount"] = tx.get("amount_ton", 0)
        amount_val = float(tx.get("amount", 0) or 0)
        if tx_type in FORCED_SIGN:
            tx["amount"] = FORCED_SIGN[tx_type] * abs(amount_val)
        elif tx_type in ("withdrawal", "instant_withdrawal") and amount_val > 0:
            tx["amount"] = -abs(amount_val)
        elif tx_type == "deposit" and amount_val < 0:
            tx["amount"] = abs(amount_val)
        elif tx_type == "resource_purchase":
            tx["amount"] = -abs(amount_val)
        elif tx_type == "resource_sale":
            # Match the list endpoint (uses seller_net_after_credit when present).
            if "seller_net_after_credit" in tx and tx["seller_net_after_credit"] is not None:
                tx["amount"] = float(tx["seller_net_after_credit"])
            else:
                tax_val = float(tx.get("tax", 0) or 0)
                tx["amount"] = abs(amount_val) - tax_val
            # Surface what the seller actually received so UI can show breakdown.
            tx["seller_received"] = float(tx["amount"])
            # Keep amount_city in sync to avoid stale gross values in the detail.
            tx["amount_city"] = round(float(tx["amount"]) * 1000)
        
        await _enrich_details(tx)
        return tx
    
    async def _enrich_details(tx: dict) -> None:
        """Surface human-friendly `details` fields for resource/land/contract tx."""
        ttype = tx.get("tx_type") or tx.get("type")
        details = dict(tx.get("details") or {})

        # Credit payments: keep ONLY 3 user-facing keys regardless of what was
        # historically written (interest_part, principal_part, source,
        # deduction_percent, sale_amount_*, listing_id, resource, etc are all
        # stripped). The frontend translates these via labelMap.
        if ttype == "credit_payment":
            allowed = {"lender_type", "lender_name", "credit_remaining_after"}
            details = {k: v for k, v in details.items() if k in allowed and v is not None}
            tx["details"] = details
            return

        if ttype in ("resource_purchase", "resource_sale"):
            r = tx.get("resource_type") or details.get("resource_type")
            amt = tx.get("resource_amount") or details.get("resource_amount") or details.get("amount")
            if r:
                details["resource"] = r
            if amt:
                details["amount_units"] = amt

        if ttype in ("contract_payment_in", "contract_payment_out"):
            r = tx.get("resource_type") or details.get("resource_type")
            amt = tx.get("resource_amount") or details.get("resource_amount")
            if r:
                details["resource"] = r
            if amt:
                details["amount_units"] = amt
            if tx.get("contract_id"):
                details["contract_id"] = tx["contract_id"]
            if tx.get("buyer_username"):
                details["buyer"] = "@" + tx["buyer_username"]
            if tx.get("seller_username"):
                details["seller"] = "@" + tx["seller_username"]
            if tx.get("gross_city") is not None:
                details["gross_city"] = tx["gross_city"]
            if ttype == "contract_payment_in":
                if tx.get("net_city") is not None:
                    details["net_city"] = tx["net_city"]
                if tx.get("tax_city") is not None:
                    details["tax_city"] = tx["tax_city"]

        if ttype == "land_purchase":
            plot_id = details.get("plot_id") or tx.get("plot_id")
            city_id = details.get("city_id") or tx.get("city_id")
            x = details.get("x") if details.get("x") is not None else tx.get("x")
            y = details.get("y") if details.get("y") is not None else tx.get("y")
            if plot_id:
                plot = await db.plots.find_one({"id": plot_id}, {"_id": 0, "x": 1, "y": 1, "city_id": 1})
                if plot:
                    if "x" in plot and x is None:
                        x = plot["x"]
                    if "y" in plot and y is None:
                        y = plot["y"]
                    if not city_id:
                        city_id = plot.get("city_id")
            if x is not None:
                details["x"] = x
            if y is not None:
                details["y"] = y
            if city_id:
                city = await db.cities.find_one({"id": city_id}, {"_id": 0, "name": 1, "display_name": 1})
                if city:
                    details["city"] = city.get("display_name") or city.get("name") or city_id
                else:
                    details["city"] = city_id
            biz_q = None
            if plot_id:
                biz_q = {"plot_id": plot_id}
            elif x is not None and y is not None and city_id:
                biz_q = {"x": x, "y": y, "city_id": city_id}
            if biz_q:
                biz = await db.businesses.find_one(biz_q, {"_id": 0, "business_type": 1, "name": 1, "level": 1})
                if biz:
                    details["business_type"] = biz.get("business_type")
                    if biz.get("name"):
                        details["business_name"] = biz["name"]
                    if biz.get("level"):
                        details["business_level"] = biz["level"]

        if details:
            tx["details"] = details

    @history_router.get("/summary")
    async def get_transaction_summary(current_user: dict = Depends(get_current_user)):
        """Get summary of all transactions by type"""
        pipeline = [
            {"$match": {"user_id": current_user["id"]}},
            {"$group": {
                "_id": "$type",
                "count": {"$sum": 1},
                "total_amount": {"$sum": "$amount"}
            }},
            {"$sort": {"count": -1}}
        ]
        
        results = await db.transactions.aggregate(pipeline).to_list(50)
        
        summary = []
        for r in results:
            tx_type = r["_id"] or "trade"
            type_info = TRANSACTION_TYPES.get(tx_type, TRANSACTION_TYPES["trade"])
            summary.append({
                "type": tx_type,
                "type_name": type_info["name"],
                "type_icon": type_info["icon"],
                "count": r["count"],
                "total_amount": r["total_amount"]
            })
        
        # Get totals
        total_income = sum(s["total_amount"] for s in summary if s["total_amount"] > 0)
        total_expenses = sum(s["total_amount"] for s in summary if s["total_amount"] < 0)
        
        return {
            "summary": summary,
            "totals": {
                "income": total_income,
                "expenses": abs(total_expenses),
                "net": total_income + total_expenses
            }
        }
    
    @history_router.get("/types")
    async def get_transaction_types():
        """Get all available transaction types (excluding hidden ones)"""
        visible_types = {k: v for k, v in TRANSACTION_TYPES.items() if not v.get("hidden")}
        return {"types": visible_types}
    
    return history_router


async def log_transaction(db, user_id: str, tx_type: str, amount: float, details: Dict[str, Any] = None):
    """Helper function to log a transaction"""
    tx = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "type": tx_type,
        "amount": amount,
        "details": details or {},
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.transactions.insert_one(tx)
    return tx
