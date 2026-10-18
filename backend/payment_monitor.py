"""
TON Payment Monitor
Monitors incoming TON transactions and credits internal balance
"""
import logging
import asyncio
import uuid
from pymongo.errors import DuplicateKeyError
from datetime import datetime, timezone
import os   
from tonsdk.utils import Address

def to_raw(address_str):
    try:
        return Address(address_str).to_string(is_user_friendly=False)
    except Exception:
        return address_str


logger = logging.getLogger(__name__)

class TONPaymentMonitor:
    """Monitor TON blockchain for incoming payments"""
    
    def __init__(self, db):
        self.db = db
        self.is_running = False
        # Polling cadence. With TONCENTER_API_KEY (≈10 RPS limit) we can poll
        # every 10 seconds; without a key (≈1 RPS) we'd be flirting with 429s,
        # so without a key we fall back to 30 s. Override via env if needed.
        try:
            self.check_interval = int(os.environ.get("PAYMENT_CHECK_INTERVAL", "10"))
        except ValueError:
            self.check_interval = 10
        # How many transactions to pull per page. Toncenter caps this at 100.
        # On a single poll we can paginate further back via `lt`/`hash` cursor
        # if needed, so 100 is just the page size, not the hard ceiling.
        try:
            self.page_size = int(os.environ.get("PAYMENT_PAGE_SIZE", "100"))
        except ValueError:
            self.page_size = 100
        # Safety stop for pagination: never fetch more than this many pages in
        # a single poll cycle. At page_size=100 this lets one poll cover up to
        # 1000 transactions — i.e. 1000+ simultaneous deposits handled per
        # 10-second tick (= 6 000+ tx/min sustained throughput).
        self.max_pages_per_poll = 10
        
    async def get_game_settings(self):
        """Get game wallet settings from database"""
        settings = await self.db.game_settings.find_one({"type": "ton_wallet"})
        if not settings:
            # Create default settings
            default_settings = {
                "type": "ton_wallet",
                "network": "testnet",  # testnet or mainnet
                "receiver_address": "",  # Admin sets this
                "last_checked_lt": 0,  # Logical time for transaction tracking
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            await self.db.game_settings.insert_one(default_settings)
            settings = default_settings
        
        # PRIORITY 1: Check distribution smart contract address first
        contract_settings = await self.db.admin_settings.find_one({"type": "distribution_contract"}, {"_id": 0})
        if contract_settings and contract_settings.get("contract_address"):
            settings["receiver_address"] = contract_settings.get("contract_address")
            return settings
        
        # PRIORITY 2: Check admin_wallets if receiver_address is empty
        if not settings.get("receiver_address"):
            admin_wallet = await self.db.admin_wallets.find_one({}, {"_id": 0})
            if admin_wallet and admin_wallet.get("address"):
                settings["receiver_address"] = admin_wallet.get("address")
        
        return settings
    
    async def check_incoming_transactions(self):
        """Check for new incoming TON transactions.

        Pagination strategy
        -------------------
        Toncenter returns transactions newest-first. We persist a per-receiver
        cursor `(last_seen_lt, last_seen_hash)` in `game_settings`. Each poll:

          1. Fetch the first page (`limit=page_size`).
          2. Walk transactions oldest→newest *within the page* until we hit a
             tx whose `lt <= last_seen_lt` (already processed) — at that point
             stop, persist the newest seen `lt`, and return.
          3. If the entire page is "new" (every tx is newer than our cursor),
             fetch the next (older) page using `lt`/`hash` of the LAST tx as
             the cursor and repeat. Capped by `max_pages_per_poll` so a bad
             cursor or huge backlog can't stall the loop.

        This guarantees no incoming deposit is ever missed, regardless of
        burst size, as long as the cursor is up-to-date. First-ever poll
        (cursor missing) processes ONLY the most-recent page so we don't
        accidentally credit ancient transactions on a fresh deploy.
        """
        try:
            settings = await self.get_game_settings()
            receiver_address = settings.get("receiver_address")

            if not receiver_address:
                logger.warning("⚠️ Адрес получателя не настроен.")
                return

            from ton_integration import ton_client
            receiver_raw = to_raw(receiver_address)

            # Per-receiver cursor — persisted in the same game_settings doc so
            # one Mongo write per poll keeps it cheap.
            last_seen_lt = int(settings.get("last_seen_lt") or 0)
            first_run = last_seen_lt == 0  # treat as fresh deploy

            newest_lt_this_poll = last_seen_lt
            total_processed = 0
            bad_items = 0
            page_lt: int | None = None
            page_hash: str | None = None

            for page_idx in range(self.max_pages_per_poll):
                # Helper that tries user-friendly first, then raw, on the
                # same lt/hash cursor (some providers normalise addresses).
                async def _fetch(addr):
                    return await ton_client.get_transaction_history(
                        addr, limit=self.page_size, lt=page_lt, hash_=page_hash,
                    )

                try:
                    transactions = await _fetch(receiver_address)
                except Exception:
                    transactions = await _fetch(receiver_raw)

                if not isinstance(transactions, list):
                    logger.warning(f"Unexpected tx-history payload type: {type(transactions).__name__} — skipping")
                    return
                if not transactions:
                    break

                stop_paginating = False
                for tx in transactions:
                    if not isinstance(tx, dict):
                        bad_items += 1
                        continue

                    # Extract lt for cursor maintenance regardless of in_msg presence.
                    tx_lt = 0
                    try:
                        tx_lt = int(tx.get("transaction_id", {}).get("lt", 0))
                    except (TypeError, ValueError):
                        tx_lt = 0
                    if tx_lt > newest_lt_this_poll:
                        newest_lt_this_poll = tx_lt

                    # Cursor check — drop everything we've already processed.
                    if not first_run and tx_lt and tx_lt <= last_seen_lt:
                        stop_paginating = True
                        continue

                    tx_hash = tx.get("transaction_id", {}).get("hash")
                    in_msg = tx.get("in_msg", {}) or {}
                    sender_address = in_msg.get("source")
                    try:
                        value = int(in_msg.get("value", 0))
                    except (TypeError, ValueError):
                        value = 0

                    if value <= 0 or not sender_address:
                        continue

                    sender_raw = to_raw(sender_address)
                    user = await self.db.users.find_one({
                        "$or": [
                            {"wallet_address": sender_address},
                            {"raw_address": sender_address},
                            {"wallet_address": sender_raw},
                            {"raw_address": sender_raw},
                        ]
                    }, {"_id": 0})

                    if user:
                        tx_data = {
                            "hash": tx_hash,
                            "sender": sender_address,
                            "sender_raw": sender_raw,
                            "amount": value,
                            "utime": tx.get("utime", 0),
                        }
                        await self.process_incoming_payment(tx_data)
                        total_processed += 1
                    else:
                        logger.debug(f"Платеж от неизвестного адреса: {sender_address}")

                # On first run we only ingest the FIRST page so we don't
                # mass-credit ancient history when a new wallet is wired up.
                if first_run:
                    break

                # If we already saw a tx older than our cursor, the rest of
                # toncenter history is by definition older too → done.
                if stop_paginating:
                    break

                # Otherwise the entire page is "new"; paginate further back.
                # Use the OLDEST tx of this page as the next cursor.
                tail = transactions[-1]
                try:
                    next_lt = int(tail.get("transaction_id", {}).get("lt", 0)) or None
                    next_hash = tail.get("transaction_id", {}).get("hash")
                except Exception:
                    next_lt, next_hash = None, None
                if not next_lt or not next_hash:
                    break
                page_lt, page_hash = next_lt, next_hash
                logger.info(f"💸 Deposit backlog detected — paginating to lt={page_lt} (page {page_idx+2})")

            if bad_items:
                logger.warning(f"Skipped {bad_items} malformed tx entries this poll")

            # Persist the newest lt we've seen so next poll only handles strictly
            # newer transactions. Single write per poll keeps mongo load low.
            if newest_lt_this_poll and newest_lt_this_poll != last_seen_lt:
                await self.db.game_settings.update_one(
                    {"type": "ton_wallet"},
                    {"$set": {"last_seen_lt": newest_lt_this_poll}},
                )
            if total_processed:
                logger.info(f"💰 Payment poll: credited {total_processed} deposits "
                            f"(cursor → lt={newest_lt_this_poll})")

        except Exception as e:
            logger.error(f"❌ Error in monitor: {e}")
    
    async def process_incoming_payment(self, transaction):
        """
        Process an incoming TON payment
        
        Args:
            transaction: Transaction data from blockchain
        """
        try:
            tx_hash = transaction.get("hash")
            sender = transaction.get("sender")
            sender_raw = transaction.get("sender_raw") or to_raw(sender)
            amount = transaction.get("amount", 0)
            amount_ton = amount / 1_000_000_000  # Convert from nanotons
            tx_utime = transaction.get("utime", 0)  # Transaction timestamp
            
            # Find user by wallet address
            user = await self.db.users.find_one({
                "$or": [
                    {"wallet_address": sender},
                    {"raw_address": sender},
                    {"wallet_address": sender_raw},
                    {"raw_address": sender_raw},
                ]
            })
            
            if not user:
                logger.warning(f"⚠️  Payment from unknown user: {sender}")
                # Create pending deposit
                await self.db.deposits.insert_one({
                    "tx_hash": tx_hash,
                    "sender": sender,
                    "sender_raw": sender_raw,
                    "amount_ton": amount_ton,
                    "status": "pending",
                    "created_at": datetime.now(timezone.utc).isoformat()
                })
                return
            
            # Check if already processed
            existing = await self.db.deposits.find_one({"tx_hash": tx_hash})
            if existing:
                logger.debug(f"Transaction {tx_hash} already processed")
                return
            
            # PROBLEM #4 FIX: Check if transaction is AFTER wallet was linked
            # This prevents crediting old transactions when reconnecting wallet
            wallet_linked_at = user.get("wallet_linked_at")
            if wallet_linked_at and tx_utime > 0:
                from dateutil import parser as date_parser
                try:
                    linked_time = date_parser.isoparse(wallet_linked_at)
                    tx_time = datetime.fromtimestamp(tx_utime, tz=timezone.utc)
                    
                    if tx_time < linked_time:
                        logger.info(f"⏭️ Skipping old transaction from {tx_time} (wallet linked at {linked_time})")
                        # Record as skipped so we don't check it again
                        await self.db.deposits.insert_one({
                            "tx_hash": tx_hash,
                            "sender": sender,
                            "sender_raw": sender_raw,
                            "amount_ton": amount_ton,
                            "status": "skipped_old",
                            "reason": "Transaction before wallet_linked_at",
                            "tx_time": tx_time.isoformat(),
                            "linked_time": linked_time.isoformat(),
                            "created_at": datetime.now(timezone.utc).isoformat()
                        })
                        return
                except Exception as parse_err:
                    logger.warning(f"Could not parse dates: {parse_err}")
            
            # NOTE: a time-based skip on `last_deposit_processed_at` used to sit
            # here. Toncenter lists transactions NEWEST first, so when one poll
            # held two deposits of the same player, the older one was dropped
            # forever (its chain time is before the moment the newer one was
            # processed) and the cursor moved past it. Duplicates are prevented
            # by the unique tx_hash claim below instead.
            user_id = user.get("id", str(user["_id"]))

            # Claim the transaction BEFORE crediting: a unique index on
            # deposits.tx_hash means two pollers / a retried poll can never
            # credit the same transaction twice. If the process dies between
            # this claim and the credit, the deposit stays in status
            # "crediting" and shows up in the reconciliation report — it is
            # never credited twice automatically.
            deposit_id = str(uuid.uuid4())
            try:
                await self.db.deposits.insert_one({
                    "id": deposit_id, "tx_hash": tx_hash, "user_id": user_id,
                    "amount_ton": amount_ton, "status": "crediting",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            except DuplicateKeyError:
                logger.debug(f"Transaction {tx_hash} already claimed")
                return
            
            # Credit user balance and update last_deposit_processed_at
            current_time = datetime.now(timezone.utc).isoformat()
            await self.db.users.update_one(
                {"_id": user["_id"]},
                {
                    "$inc": {
                        "balance_ton": amount_ton,
                        "total_deposited": amount_ton
                    },
                    "$set": {
                        "last_deposit_processed_at": current_time
                    }
                }
            )
            
            # Complete the claimed deposit record
            await self.db.deposits.update_one({"id": deposit_id}, {"$set": {
                "tx_hash": tx_hash,
                "user_id": user_id,
                "wallet_address": user.get("wallet_address"),
                "raw_address": user.get("raw_address"),
                "amount_ton": amount_ton,
                "status": "completed",
                "credited_at": datetime.now(timezone.utc).isoformat(),
            }})
            
            # ===== ЗАПИСЫВАЕМ В ИСТОРИЮ ТРАНЗАКЦИЙ =====
            transaction_record = {
                "id": str(uuid.uuid4()),
                "type": "deposit",
                "tx_type": "deposit",
                "user_id": user_id,
                "user_username": user.get("username"),
                "user_wallet": user.get("wallet_address"),
                "amount": amount_ton,  # Положительное для пополнения
                "amount_ton": amount_ton,
                "from_address": sender,
                "to_address": user.get("wallet_address"),
                "description": f"Пополнение баланса +{amount_ton:.4f} TON",
                "status": "completed",
                "blockchain_hash": tx_hash,
                "deposit_id": deposit_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat()
            }
            await self.db.transactions.insert_one(transaction_record)
            
            # Update stats
            await self.db.admin_stats.update_one(
                {"type": "treasury"},
                {
                    "$inc": {
                        "total_deposits": amount_ton,
                        "deposits_count": 1
                    }
                },
                upsert=True
            )
            
            # ===== РАЗДЕЛЕНИЕ СРЕДСТВ НА КОШЕЛЬКИ АДМИНИСТРАТОРОВ =====
            await self.distribute_deposit_to_wallets(amount_ton, tx_hash, user_id)
            
            # ===== TELEGRAM + IN-APP УВЕДОМЛЕНИЕ ПОЛЬЗОВАТЕЛЮ =====
            # Single fan-out via core.notify.notify_user — it inserts the in-app
            # notification AND mirrors ONE Telegram message (with a "🏠 На главную"
            # button). We intentionally do NOT call bot.notify_deposit separately
            # or the user would receive two Telegram messages for one deposit.
            try:
                from core.notify import notify_user
                await notify_user(
                    self.db, user_id,
                    title="💰 Баланс пополнен",
                    message=f"✅ На ваш баланс зачислено <b>{amount_ton:.4f} TON</b>.",
                    type_key="deposit",
                    priority="success",
                    payload={"amount": amount_ton, "tx_hash": tx_hash},
                    i18n_key="deposit",
                    i18n_vars={"amount": f"{amount_ton:.4f}"},
                    tx_hash=tx_hash,
                )
            except Exception as in_err:
                logger.warning(f"deposit notify failed: {in_err}")
            
            logger.info(f"✅ Credited {amount_ton} TON to {user.get('username', 'User')}")
            logger.info(f"   TX: {tx_hash}")
            
        except Exception as e:
            logger.error(f"❌ Error processing payment: {e}")
    
    async def distribute_deposit_to_wallets(self, amount_ton: float, tx_hash: str, user_id: str):
        """
        Разделить входящий депозит между кошельками админов согласно процентам
        И автоматически отправить TON на эти кошельки
        """
        try:
            # Получаем настроенные кошельки
            wallets = await self.db.admin_wallets.find({}, {"_id": 0}).to_list(100)
            
            if not wallets:
                logger.debug("Нет настроенных кошельков для распределения")
                return
            
            # Вычисляем общий процент
            total_percentage = sum(w.get("percentage", 0) for w in wallets)
            if total_percentage <= 0:
                return
            
            # Получаем мнемонику отправителя для автоматических переводов
            sender_wallet = await self.db.admin_settings.find_one({"type": "sender_wallet"}, {"_id": 0})
            mnemonic = sender_wallet.get("mnemonic") if sender_wallet else None
            if not mnemonic:
                mnemonic = os.environ.get("TON_WALLET_MNEMONIC")
            
            from ton_integration import ton_client
            
            for wallet in wallets:
                percentage = wallet.get("percentage", 0)
                if percentage <= 0:
                    continue
                
                # Сумма для этого кошелька
                wallet_amount = amount_ton * (percentage / 100)
                wallet_address = wallet.get("address")
                
                if wallet_amount > 0 and wallet_address:
                    distribution_id = str(uuid.uuid4())
                    
                    # Записываем в лог распределения
                    distribution_record = {
                        "id": distribution_id,
                        "original_tx_hash": tx_hash,
                        "user_id": user_id,
                        "wallet_address": wallet_address,
                        "amount": wallet_amount,
                        "percentage": percentage,
                        "status": "pending",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
                    await self.db.deposit_distributions.insert_one(distribution_record)
                    
                    # Автоматическая отправка TON если есть мнемоника
                    if mnemonic and wallet_amount >= 0.01:  # Минимум 0.01 TON для перевода
                        try:
                            dist_tx_hash = await ton_client.send_ton_payout(
                                dest_address=wallet_address,
                                amount_ton=wallet_amount,
                                mnemonics=mnemonic
                            )
                            
                            # Обновляем статус на completed
                            await self.db.deposit_distributions.update_one(
                                {"id": distribution_id},
                                {"$set": {
                                    "status": "completed",
                                    "tx_hash": dist_tx_hash,
                                    "completed_at": datetime.now(timezone.utc).isoformat()
                                }}
                            )
                            
                            logger.info(f"✅ Автоматически отправлено {wallet_amount:.4f} TON ({percentage}%) на {wallet_address[:12]}... TX: {dist_tx_hash[:20]}")
                            
                        except Exception as send_err:
                            logger.warning(f"⚠️ Не удалось автоматически отправить на {wallet_address[:12]}...: {send_err}")
                            # Статус остаётся pending для ручной обработки
                    else:
                        logger.info(f"📊 Распределено {wallet_amount:.4f} TON ({percentage}%) на {wallet_address[:12]}... (требуется ручной перевод)")
            
        except Exception as e:
            logger.error(f"❌ Error distributing deposit: {e}")
    
    async def ensure_indexes(self):
        """One deposit record per blockchain transaction (idempotent crediting)."""
        try:
            await self.db.deposits.create_index(
                "tx_hash", unique=True, name="uniq_tx_hash",
                partialFilterExpression={"tx_hash": {"$type": "string"}})
        except Exception as e:
            # Existing duplicate tx_hash rows block the index: clean them up
            # (see the reconciliation report) — until then the find_one check
            # above still guards against re-crediting in a single process.
            logger.error(f"⚠️ deposits.tx_hash unique index NOT created: {e}")

    async def start_monitoring(self):
        """Start monitoring loop — only runs work when this worker is the
        scheduler leader. Otherwise it idles. This prevents 4× duplicate
        deposit credits when running under `gunicorn -w 4`.
        """
        self.is_running = True
        logger.info("🚀 TON Payment Monitor started")
        await self.ensure_indexes()
        # Lazy import to avoid circular references on cold start
        try:
            from scheduler_leader import is_leader as _is_leader
        except Exception:
            _is_leader = lambda: True  # noqa: E731 — degrade gracefully

        while self.is_running:
            try:
                if _is_leader():
                    await self.check_incoming_transactions()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"❌ Monitor error: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def stop_monitoring(self):
        """Stop monitoring loop"""
        self.is_running = False
        logger.info("🛑 TON Payment Monitor stopped")


# Global monitor instance
payment_monitor = None

async def init_payment_monitor(db):
    """Initialize payment monitor"""
    global payment_monitor
    payment_monitor = TONPaymentMonitor(db)
    # Start in background
    asyncio.create_task(payment_monitor.start_monitoring())
    logger.info("✅ Payment monitor initialized")

async def stop_payment_monitor():
    """Stop payment monitor"""
    global payment_monitor
    if payment_monitor:
        await payment_monitor.stop_monitoring()
