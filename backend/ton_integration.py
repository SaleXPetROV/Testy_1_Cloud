"""
TON Blockchain Integration Module
Handles real TON mainnet transactions
"""
import os
import asyncio
import logging
from typing import Optional, Dict
from tonsdk.contract.wallet import WalletVersionEnum, Wallets
from tonsdk.utils import bytes_to_b64str, to_nano
import base64
import json
import httpx

logger = logging.getLogger(__name__)

# TON Configuration
TON_MAINNET_CONFIG = "https://ton.org/global-config.json"
TON_TESTNET = False  # Set to False for mainnet


class PayoutAmbiguous(Exception):
    """The payout MAY have been broadcast (lost response / seqno already used).
    Callers must NOT refund automatically — mark the payout for review."""

    def __init__(self, msg_hash: str = "", reason: str = ""):
        self.msg_hash = msg_hash or ""
        super().__init__(f"payout outcome unknown: {reason}")

class TONClient:
    def __init__(self):
        self.initialized = False
        
    async def init(self):
        if self.initialized: return
        try:
            # Инициализация клиента (для работы send_ton_payout)
            self.initialized = True
            logger.info("✅ TON Client initialized for transfers")
        except Exception as e:
            logger.error(f"❌ Failed to init: {e}")

    async def send_ton_payout(self, dest_address: str, amount_ton: float, mnemonics: str, user_username: str = ""):
        """Отправка TON через API Toncenter с автоопределением версии кошелька"""
        try:
            api_key = os.environ.get("TONCENTER_API_KEY") or ""
            toncenter_endpoint = os.environ.get("TONCENTER_API_ENDPOINT", "https://toncenter.com/api/v2").rstrip('/')
            # Defensive normalisation: this code appends REST paths
            # (/getAddressBalance, /getWalletInformation, /sendBoc). A common
            # misconfiguration sets TONCENTER_API_ENDPOINT to the JSON-RPC URL
            # ".../api/v2/jsonRPC", which would produce invalid URLs like
            # ".../jsonRPC/getAddressBalance" and break every payout + balance
            # check. Strip the /jsonRPC suffix so payouts work regardless.
            for _suf in ("/jsonRPC", "/jsonrpc", "/jsonRpc"):
                if toncenter_endpoint.endswith(_suf):
                    toncenter_endpoint = toncenter_endpoint[: -len(_suf)]
                    break
            
            from tonsdk.crypto import mnemonic_to_wallet_key
            from tonsdk.contract.wallet import WalletV4ContractR2, WalletV3ContractR2
            
            mnemonics_list = mnemonics.strip().split()
            if len(mnemonics_list) != 24:
                raise Exception(f"Неверное количество слов в мнемонике: {len(mnemonics_list)} (нужно 24)")
            
            pub_k, priv_k = mnemonic_to_wallet_key(mnemonics_list)
            
            # Создаём оба варианта кошельков
            wallet_v4 = WalletV4ContractR2(public_key=pub_k, private_key=priv_k, workchain=0)
            wallet_v3 = WalletV3ContractR2(public_key=pub_k, private_key=priv_k, workchain=0)
            
            addr_v4 = wallet_v4.address.to_string(True, True, False)
            addr_v3 = wallet_v3.address.to_string(True, True, False)
            
            logger.info(f"📢 V4R2 адрес: {addr_v4}")
            logger.info(f"📢 V3R2 адрес: {addr_v3}")
            
            # Helper function for API calls with retry
            async def api_call_with_retry(client, url, params, headers, max_retries=3):
                for attempt in range(max_retries):
                    resp = await client.get(url, params=params, headers=headers)
                    if resp.status_code == 429:
                        logger.warning(f"⚠️ Rate limited (429), retry {attempt + 1}/{max_retries}...")
                        await asyncio.sleep(1 + attempt)  # Progressive delay
                        continue
                    return resp.json()
                return {"result": {}}  # Return empty on failure

            # Reliable balance via the LIGHT getAddressBalance endpoint — the same
            # one the admin balance card uses. getWalletInformation (used before
            # for BOTH addresses back-to-back) was throttled to HTTP 429 without
            # an API key and reported balance 0, which falsely raised "оба
            # кошелька пусты" and BLOCKED legitimate withdrawals.
            async def addr_balance(client, addr, headers):
                try:
                    r = await client.get(f"{toncenter_endpoint}/getAddressBalance",
                                          params={"address": addr}, headers=headers)
                    if r.status_code == 200:
                        j = r.json()
                        if j.get("ok"):
                            return int(j.get("result", 0) or 0) / 1e9
                except Exception as _e:
                    logger.warning(f"getAddressBalance failed for {addr}: {_e}")
                return 0.0

            _wallet = None
            wallet_address = None

            async with httpx.AsyncClient(timeout=15.0) as client:
                headers = {"X-API-Key": api_key} if api_key else {}

                # 1) Cheap, reliable balances first. The V3R2 wallet is only
                #    queried when V4R2 cannot cover the payout: one request less
                #    on the common path, and fewer 429s from Toncenter without
                #    an API key (free tier is ~1 request/second).
                balance_v4 = await addr_balance(client, addr_v4, headers)
                balance_v3 = 0.0
                if balance_v4 < amount_ton + 0.01:
                    await asyncio.sleep(0.25)
                    balance_v3 = await addr_balance(client, addr_v3, headers)
                logger.info(f"📊 Балансы: V4R2={balance_v4}, V3R2={balance_v3}")
                if not api_key:
                    logger.warning("⚠️ TONCENTER_API_KEY не задан: Toncenter ограничивает ~1 запрос/сек, выплаты могут ждать из-за 429")

                # 2) Choose the funded wallet (prefer V4R2). Checks balance
                #    BEFORE attempting to send.
                if balance_v4 >= amount_ton + 0.01:
                    _wallet, wallet_address, chosen_balance = wallet_v4, addr_v4, balance_v4
                elif balance_v3 >= amount_ton + 0.01:
                    _wallet, wallet_address, chosen_balance = wallet_v3, addr_v3, balance_v3
                elif balance_v4 > 0:
                    _wallet, wallet_address, chosen_balance = wallet_v4, addr_v4, balance_v4
                elif balance_v3 > 0:
                    _wallet, wallet_address, chosen_balance = wallet_v3, addr_v3, balance_v3
                else:
                    raise Exception(
                        f"На кошельке для вывода недостаточно средств.\n"
                        f"V4R2: {addr_v4} (баланс: {balance_v4})\n"
                        f"V3R2: {addr_v3} (баланс: {balance_v3})\n"
                        f"Пополните кошелёк для вывода."
                    )

                # 3) Insufficient-funds guard (amount + gas).
                if chosen_balance < amount_ton + 0.01:
                    raise Exception(
                        f"Недостаточно средств на кошельке вывода. "
                        f"Баланс: {chosen_balance:.4f} TON, нужно: {amount_ton + 0.01:.4f} TON (сумма + газ)."
                    )

                # 4) seqno/state for the CHOSEN wallet only (fewer heavy calls =
                #    less rate-limiting). Retry handles transient 429s.
                info = await api_call_with_retry(
                    client, f"{toncenter_endpoint}/getWalletInformation",
                    {"address": wallet_address}, headers
                )
                result = info.get("result", {}) if isinstance(info, dict) else {}
                if not isinstance(result, dict):
                    result = {}
                seqno = result.get("seqno", 0) or 0
                logger.info(f"📊 Используем адрес: {wallet_address}, seqno={seqno}, balance={chosen_balance}")

            # Создаем сообщение о переводе с комментарием
            comment_text = f"GRAM City Entertainment @{user_username}" if user_username else "GRAM City Entertainment"
            
            # Создаём payload с комментарием
            from tonsdk.boc import Cell
            from tonsdk.utils import bytes_to_b64str as _b2b
            
            comment_cell = Cell()
            comment_cell.bits.write_uint(0, 32)  # op = 0 for simple text comment
            comment_cell.bits.write_string(comment_text)
            
            query = _wallet.create_transfer_message(
                to_addr=dest_address,
                amount=to_nano(amount_ton, 'ton'),
                seqno=int(seqno),
                payload=comment_cell
            )

            # Compute the deterministic external-message hash BEFORE sending it
            # to Toncenter — `sendBoc` doesn't return a usable tx hash (only
            # confirms the message was accepted), so if we relied on the API
            # response we'd end up storing the string "sent_success" as the
            # hash. `Cell.bytes_hash()` gives us the 32-byte SHA-256 of the
            # message, which is exactly what TON explorers (Tonviewer, Tonscan)
            # accept in both hex and base64url form.
            msg_cell = query['message']
            try:
                _hash_bytes = msg_cell.bytes_hash()
                msg_hash_hex = _hash_bytes.hex()
            except Exception as _hex_e:
                logger.warning(f"Failed to compute msg hash: {_hex_e}")
                msg_hash_hex = None

            # 5. Отправляем BOC в сеть
            boc = bytes_to_b64str(msg_cell.to_boc(False))
            
            # Retry logic for sendBoc
            max_retries = 3
            retry_delay = 2
            last_error = None
            
            transport_failed = False   # a request may have reached the network
            for attempt in range(max_retries):
                async with httpx.AsyncClient(timeout=15.0) as client:
                    try:
                        resp = await client.post(f"{toncenter_endpoint}/sendBoc", json={"boc": boc}, headers=headers)
                        res_data = resp.json()
                    except (httpx.TimeoutException, httpx.TransportError, ValueError) as _te:
                        # No answer: the BOC may or may not have been broadcast.
                        # Re-sending the SAME signed message is safe — its seqno
                        # makes the network accept it at most once.
                        transport_failed = True
                        logger.warning(f"⚠️ sendBoc transport error (attempt {attempt + 1}/{max_retries}): {_te}")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    if resp.status_code == 200 and res_data.get("ok"):
                        # Prefer the message hash we computed locally — this is
                        # the same value tonviewer.com/transaction/<hash> uses.
                        # Fall back to the toncenter-provided hash only if our
                        # computation failed for some reason.
                        api_hash = (res_data.get("result", {}) or {}).get("hash")
                        tx_hash = msg_hash_hex or api_hash or ""
                        logger.info(f"✅ УСПЕХ! Хэш: {tx_hash}")
                        return tx_hash
                    elif resp.status_code == 429:
                        # Rate limited - wait and retry
                        logger.warning(f"⚠️ Rate limited (429), attempt {attempt + 1}/{max_retries}, waiting {retry_delay}s...")
                        last_error = "Rate limit exceeded. Слишком много запросов к сети TON."
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        error_msg = res_data.get("error", "Unknown blockchain error")
                        logger.error(f"❌ Сеть отклонила BOC: {error_msg}")
                        
                        # Более понятные сообщения об ошибках
                        if "unpack account state" in str(error_msg).lower():
                            raise Exception("Кошелёк отправителя не активирован или пуст. Пополните его TON и повторите.")
                        elif "not enough" in str(error_msg).lower():
                            raise Exception("Недостаточно средств на кошельке отправителя.")
                        elif "seqno" in str(error_msg).lower():
                            if transport_failed:
                                # an earlier attempt with this very message got through
                                raise PayoutAmbiguous(msg_hash_hex, "seqno already used after a lost response")
                            raise Exception("Ошибка последовательности транзакции. Попробуйте позже.")
                        else:
                            raise Exception(f"Ошибка сети TON: {error_msg}")
            
            # All retries exhausted
            if transport_failed:
                raise PayoutAmbiguous(msg_hash_hex, "no response from the network after sending")
            raise Exception(last_error or "Превышен лимит запросов к TON API. Добавьте TONCENTER_API_KEY для увеличения лимитов.")

        except Exception as e:
            logger.error(f"❌ Критическая ошибка в send_ton_payout: {e}")
            raise e

    async def get_transaction_history(self, address: str, limit: int = 20,
                                       lt: int | None = None, hash_: str | None = None):
        """Получение истории транзакций для payment_monitor.py.

        Supports pagination via toncenter's ``lt`` + ``hash`` cursor — passing the
        ``lt``/``hash`` of the OLDEST tx of the previous page fetches the next
        (older) page. This lets payment_monitor scan further back than the
        default 20-tx window when the deposit burst is large (e.g. 400+
        simultaneous players topping up).

        Toncenter sometimes responds with ``{"ok": false, "result": "<err>"}``
        when rate-limited; iterating over a string would yield 1-character
        "tx" entries downstream. We defensively coerce non-list results to
        an empty list.
        """
        try:
            import httpx
            api_key = os.environ.get("TONCENTER_API_KEY") or ""
            headers = {"X-API-Key": api_key} if api_key else {}
            params = {"address": address, "limit": str(limit)}
            if lt is not None and hash_ is not None:
                params["lt"] = str(lt)
                params["hash"] = hash_
            url = "https://toncenter.com/api/v2/getTransactions"
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(url, headers=headers, params=params)
                if r.status_code != 200:
                    if r.status_code == 429:
                        logger.warning("⚠️ Toncenter rate-limited (429) — skipping this poll")
                    else:
                        logger.warning(f"⚠️ Toncenter HTTP {r.status_code}: {r.text[:200]}")
                    return []
                try:
                    data = r.json()
                except Exception:
                    return []
                if not isinstance(data, dict):
                    return []
                if not data.get("ok", True):
                    logger.debug(f"Toncenter error: {data.get('error', data)}")
                    return []
                result = data.get("result", [])
                if not isinstance(result, list):
                    return []
                return [tx for tx in result if isinstance(tx, dict)]
        except Exception as e:
            logger.error(f"Failed to fetch history: {e}")
            return []

    async def check_incoming_transactions(self):
        try:
            settings = await self.get_game_settings()
            receiver_address = settings.get("receiver_address")
            if not receiver_address: return

            # Получаем историю транзакций кошелька проекта
            transactions = await ton_client.get_transaction_history(receiver_address)
            
            for tx in transactions:
                # 1. Проверяем, не обрабатывали ли мы этот tx_hash раньше
                # 2. Ищем в комментарии (payload) ID пользователя
                # 3. Если нашли, вызываем:
                # await self.process_payment(user_id, amount, tx_hash)
                pass
        except Exception as e:
            logger.error(f"Error in monitor: {e}")

# Global TON client instance
ton_client = TONClient()

async def init_ton_client():
    """Initialize TON client on startup"""
    await ton_client.init()

async def close_ton_client():
    """Close TON client on shutdown"""
    await ton_client.close()

# Helper functions
def ton_to_nano(amount: float) -> int:
    """Convert TON to nanoTON"""
    return int(amount * 1e9)

def nano_to_ton(amount: int) -> float:
    """Convert nanoTON to TON"""
    return amount / 1e9

def validate_ton_address(address: str) -> bool:
    """
    Validate TON address format
    
    Args:
        address: TON wallet address
        
    Returns:
        True if valid
    """
    # TON addresses are typically 48 characters
    # Format: EQxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    if not address:
        return False
    
    if len(address) != 48:
        return False
    
    if not address.startswith(('EQ', 'UQ')):
        return False
    
    return True
