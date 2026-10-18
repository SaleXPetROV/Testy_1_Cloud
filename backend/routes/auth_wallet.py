"""Wallet authentication + user plot/business accessors.

Split from server.py (AUTH ROUTES section, ~290 lines).
"""
from datetime import datetime, timezone
import json
import logging
import os

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any

from core.dependencies import get_current_user
from frozen_tenders import effective_frozen_city
from core.models import User
from core.helpers import (
    get_user_identifiers as _helper_gui,
    to_raw,
    to_user_friendly,
    normalize_wallet,
    resolve_business_config,
    resolve_owner_keys,
    owner_businesses_query,
)
from core.ton_proof import (
    verify_ton_proof, TonProofError, is_ton_proof_required,
    TON_PROOF_MAX_AGE_SEC,
)
from business_config import BUSINESSES

# Meta Conversions API (CAPI) — server-side Lead tracking on registration
from meta_capi import send_capi_registration_event

logger = logging.getLogger(__name__)


class WalletVerifyRequest(BaseModel):
    address: str
    proof: Optional[Dict[str, Any]] = None
    language: str = "en"
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    referral_code: Optional[str] = None
    fbp: Optional[str] = None
    fbc: Optional[str] = None
    # 2FA: when the wallet's owner has TOTP enabled, verify-wallet returns
    # {requires_2fa: true} on the first call; the frontend then re-submits
    # the same request with `totp_code` (or a one-time backup code) filled in.
    totp_code: Optional[str] = None
    # ton_proof — hex-encoded ed25519 pubkey from wallet.account.publicKey
    # (cross-checked against walletStateInit). Optional in permissive mode,
    # required when TON_PROOF_REQUIRED=1.
    public_key: Optional[str] = None


def create_auth_wallet_router(db):
    router = APIRouter(prefix="/api", tags=["auth-wallet"])

    async def get_user_identifiers(current_user):
        return await _helper_gui(db, current_user)


    @router.get("/auth/wallet/proof-payload")
    async def issue_ton_proof_payload():
        """Issue a single-use nonce for ton_proof. The frontend feeds this
        into `TonConnectUI.setConnectRequestParameters({tonProof: <nonce>})`
        BEFORE the user connects a wallet, and later returns the same value
        inside the `proof.payload` field so we can bind the proof to this
        specific session and prevent replay/harvesting attacks.
        """
        import secrets
        payload = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        # Store with a 15-min TTL; consumed on successful /verify-wallet.
        # Using a separate collection so it can't collide with other nonces.
        await db.wallet_proof_payloads.insert_one({
            "payload": payload,
            "created_at": now.isoformat(),
            "expires_at": (now.timestamp() + TON_PROOF_MAX_AGE_SEC),
        })
        return {"payload": payload, "ttl_sec": TON_PROOF_MAX_AGE_SEC}


    async def _peek_proof_payload(payload: str) -> bool:
        """Non-destructive check that a nonce still exists and hasn't expired.
        The actual delete happens at ``_consume_proof_payload`` right BEFORE
        we hand out the session token — otherwise the multi-step 2FA flow
        (verify-wallet → requires_2fa → verify-wallet with totp_code) would
        burn the nonce on the first hop and the second one would 401 as
        'payload invalid or expired'."""
        if not payload:
            return False
        doc = await db.wallet_proof_payloads.find_one({"payload": payload})
        if not doc:
            return False
        try:
            if float(doc.get("expires_at") or 0) < datetime.now(timezone.utc).timestamp():
                return False
        except Exception:
            return False
        return True


    async def _consume_proof_payload(payload: str) -> bool:
        """Atomically consume a nonce. Returns True if the payload was valid
        and not expired; deletes it so it can't be reused."""
        if not payload:
            return False
        doc = await db.wallet_proof_payloads.find_one_and_delete({"payload": payload})
        if not doc:
            return False
        exp = doc.get("expires_at")
        try:
            if float(exp) < datetime.now(timezone.utc).timestamp():
                return False
        except Exception:
            return False
        return True


    @router.post("/auth/verify-wallet")
    async def verify_wallet(request: WalletVerifyRequest, http_request: Request):
        """Verify wallet connection with DEBUG logging"""
        try:
            is_new_user = False
            # S6: sanitized logging — no raw password/email echoes
            logger.info(f"[AUTH] verify-wallet address={request.address} username={request.username} email={'***' if request.email else None}")

            raw_input = (request.address or "").strip()
            if not raw_input:
                raise HTTPException(status_code=400, detail="Wallet address required")

            # Canonical normalization — raw (0:hex) is the single source of truth.
            wallet_address, raw_addr = normalize_wallet(raw_input)
            if not wallet_address or not raw_addr:
                print(f"❌ Ошибка нормализации адреса: {raw_input}")
                raise HTTPException(status_code=400, detail="Invalid TON address format")

            # ── ton_proof verification ────────────────────────────────────
            # Cryptographic proof that the caller CONTROLS the private key
            # of `wallet_address`. Without this, anyone who knows a wallet's
            # public address could log in as its owner.
            #
            # IMPORTANT: We verify the proof (signature + freshness + domain
            # + nonce existence) on EVERY request, but only CONSUME the
            # nonce when we actually issue a token. This lets the two-step
            # wallet-2FA flow re-submit the same proof with `totp_code`
            # without hitting "payload invalid or expired".
            proof_required = is_ton_proof_required()
            claimed_payload = ""
            if request.proof:
                claimed_payload = str(request.proof.get("payload") or "")
                if not await _peek_proof_payload(claimed_payload):
                    raise HTTPException(status_code=401, detail="ton_proof payload invalid or expired")
                # Bag #1 fallback: a deployed wallet may send NO walletStateInit.
                # Fetch the ed25519 pubkey on-chain (Toncenter, network+key from
                # env) so we can still verify against a TRUSTED key. Never raises.
                _state_init = request.proof.get("state_init") or request.proof.get("stateInit")
                _onchain_pk = None
                if not _state_init:
                    try:
                        from core.ton_proof import fetch_onchain_pubkey
                        _onchain_pk = await fetch_onchain_pubkey(wallet_address)
                    except Exception as _e:
                        logger.warning("on-chain pubkey fetch failed for %s: %s", wallet_address, _e)
                try:
                    import time as _time
                    verify_ton_proof(
                        address=wallet_address,
                        proof=request.proof,
                        now_ts=int(_time.time()),
                        expected_payload=claimed_payload,
                        trusted_pubkey_hint=request.public_key,
                        onchain_pubkey_fallback=_onchain_pk,
                    )
                except TonProofError as e:
                    logger.warning("ton_proof rejected for %s: %s", wallet_address, e)
                    raise HTTPException(status_code=401, detail=f"ton_proof verification failed: {e}")
            elif proof_required:
                raise HTTPException(status_code=401, detail="ton_proof required")
            else:
                logger.warning("verify-wallet: no ton_proof supplied (permissive mode) for %s", wallet_address)

            # Find the wallet's OWNER (match on canonical raw first, then any
            # historical user-friendly form to catch legacy/non-normalized rows).
            user_doc = await db.users.find_one({
                "$or": [
                    {"raw_address": raw_addr},
                    {"wallet_address": wallet_address},
                    {"wallet_address": raw_input},
                ]
            })
            # Diagnostic trail so we can later prove which account any given
            # /auth/verify-wallet call actually resolved to.
            logger.info(
                "[AUTH] verify-wallet resolution: raw=%s uf=%s owner_username=%s owner_email=%s",
                raw_addr, wallet_address,
                (user_doc or {}).get("username"),
                (user_doc or {}).get("email"),
            )

            if not user_doc:
                print("ℹ️ Пользователь не найден в БД. Попытка регистрации...")

                if not request.username:
                    print("⚠️ Регистрация прервана: не указан username")
                    return {
                        "status": "need_username",
                        "message": "Username required for registration",
                        "wallet_address": wallet_address
                    }

                # Проверка уникальности username (case-insensitive)
                from auth_handler import username_ci_query as _uci
                existing_username = await db.users.find_one(_uci(request.username))
                if existing_username:
                    print(f"❌ Ошибка: Username {request.username} уже занят")
                    raise HTTPException(status_code=400, detail="Имя пользователя уже занято")

                # Проверка уникальности Email (если он прислан)
                if request.email:
                    existing_email = await db.users.find_one({"email": request.email})
                    if existing_email:
                        print(f"❌ Ошибка: Email {request.email} уже занят")
                        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")

                # Импортируем функцию генерации аватара
                from auth_handler import generate_avatar_from_initials, pwd_context, build_registration_device_fields, resolve_referrer_id, referral_fields

                # Генерируем аватар из username
                avatar = generate_avatar_from_initials(request.username)

                # Хешируем пароль если он есть
                hashed_password = None
                if request.password:
                    hashed_password = pwd_context.hash(request.password)

                _dev_fields, _login_entry = build_registration_device_fields(http_request)
                _referrer_id = await resolve_referrer_id(
                    db, request.referral_code, new_email=request.email, new_wallet=wallet_address
                )

                # Формируем объект для записи
                import uuid
                new_user = {
                    "id": str(uuid.uuid4()),
                    "wallet_address": wallet_address,
                    "raw_address": raw_addr,
                    "wallet_linked_at": datetime.now(timezone.utc).isoformat(),  # Track when wallet was linked
                    "username": request.username,
                    "display_name": request.username,
                    "email": request.email,
                    "hashed_password": hashed_password,
                    "avatar": avatar,
                    "language": request.language or "en",
                    "is_admin": False,
                    "balance_ton": 0.0,
                    "level": 1,
                    "xp": 0,
                    "total_turnover": 0,
                    "total_income": 0.0,
                    "registration_method": "ton",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_login": datetime.now(timezone.utc).isoformat(),
                    "plots_owned": [],
                    "businesses_owned": [],
                    **_dev_fields,
                    **referral_fields(_referrer_id),
                    "login_history": [_login_entry],
                }

                # --- ЛОГ ПЕРЕД ЗАПИСЬЮ В БД ---
                print("📝 ПОПЫТКА ЗАПИСИ В MONGODB:")
                print(json.dumps({**new_user, "hashed_password": "***" if hashed_password else None}, indent=2, ensure_ascii=False))

                try:
                    # Race guard: re-check the wallet wasn't claimed between the
                    # initial lookup and now — enforces "1 wallet → 1 account".
                    dup = await db.users.find_one({
                        "$or": [
                            {"raw_address": raw_addr},
                            {"wallet_address": wallet_address},
                        ]
                    })
                    if dup:
                        user_doc = dup
                        is_new_user = False
                    else:
                        result = await db.users.insert_one(new_user)
                        try:
                            import analytics
                            await analytics.track(new_user["id"], "register", channel="wallet")
                            await analytics.mark_active(new_user["id"])
                        except Exception:
                            pass
                        print(f"✅ УСПЕШНО ЗАПИСАНО. ID: {result.inserted_id}")
                        try:
                            from b2b_partners import tag_user_with_partner
                            await tag_user_with_partner(db, new_user["id"], request.referral_code)
                        except Exception:
                            pass
                        user_doc = new_user
                        is_new_user = True
                        # Demo (Sandbox): credit +50 000 $CITY to the referrer's
                        # DEMO balance for this new referral (never touches real).
                        if _referrer_id:
                            try:
                                from demo_service import credit_demo_referral
                                await credit_demo_referral(db, _referrer_id)
                            except Exception as _demo_ref_err:
                                logger.warning(f"[demo] referral credit failed: {_demo_ref_err}")
                        # Meta CAPI: fire Lead event for new TON Connect user (fire-and-forget)
                        await send_capi_registration_event(
                            new_user, http_request,
                            fbp=getattr(request, "fbp", None), fbc=getattr(request, "fbc", None),
                        )
                except HTTPException:
                    raise
                except Exception as db_err:
                    print(f"❌ КРИТИЧЕСКАЯ ОШИБКА MONGODB: {db_err}")
                    raise HTTPException(status_code=500, detail=f"Database error: {str(db_err)}")
            else:
                print(f"✅ Пользователь найден: {user_doc.get('username')}. Вход в аккаунт-владельца кошелька.")
                # ── 2FA gate ──────────────────────────────────────────────
                # Any account (email/Google/wallet) with TOTP enabled MUST
                # complete 2FA before we hand out a session token. This is
                # the same contract the /auth/login flow uses.
                if user_doc.get("is_2fa_enabled") and user_doc.get("two_factor_secret"):
                    if not request.totp_code:
                        return {
                            "status": "requires_2fa",
                            "requires_2fa": True,
                            "user_id": user_doc.get("id", str(user_doc.get("_id"))),
                            "wallet_address": wallet_address,
                            "message": "Требуется код 2FA",
                        }
                    # Verify TOTP; fall back to one-time backup codes on mismatch.
                    import pyotp as _pyotp
                    import hashlib as _hashlib
                    from security.totp_crypto import decrypt_secret as _decrypt_totp
                    _totp = _pyotp.TOTP(_decrypt_totp(user_doc["two_factor_secret"]))
                    submitted = str(request.totp_code).strip()
                    if not _totp.verify(submitted, valid_window=1):
                        # Backup-code fallback: stored SHA-256 upper-case hashes.
                        code_hash = _hashlib.sha256(submitted.upper().encode()).hexdigest()
                        backup_codes = list(user_doc.get("backup_codes") or [])
                        if code_hash in backup_codes:
                            backup_codes.remove(code_hash)
                            await db.users.update_one(
                                {"_id": user_doc["_id"]},
                                {"$set": {"backup_codes": backup_codes}},
                            )
                        else:
                            raise HTTPException(status_code=401, detail="Неверный код 2FA")

                update_data = {
                    "last_login": datetime.now(timezone.utc).isoformat(),
                    "language": request.language,
                    # Heal any legacy / non-canonical wallet forms so future
                    # lookups always hit the fast path.
                    "wallet_address": wallet_address,
                    "raw_address": raw_addr,
                }
                # NOTE: existing wallet → we ONLY log in. We never attach a new
                # email/password from the login form to someone else's account.
                await db.users.update_one({"_id": user_doc["_id"]}, {"$set": update_data})
                user_doc.update(update_data)

            # Создаем токен. Session handling:
            # A wallet login is frequently fired MULTIPLE times for one user
            # action (React StrictMode, effect re-runs, TonConnect reconnect,
            # network retries) — each with its own fresh nonce, so each one
            # passes the single-use nonce check. If every call ROTATED the
            # session, the token handed to the browser by call #1 would be
            # invalidated by call #2 → /auth/me 401 `session_invalidated` →
            # the user is kicked instantly and the redirect re-triggers the
            # whole thing in a loop (exactly what the logs showed).
            #
            # Fix: logging in with YOUR OWN wallet REUSES the account's existing
            # session id (deterministic, race-free) and never self-kicks. A new
            # session id is minted only when the account has none yet. Fresh
            # sessions for email/Google login still rotate & kick as before.
            if claimed_payload:
                if not await _consume_proof_payload(claimed_payload):
                    raise HTTPException(status_code=401, detail="ton_proof payload invalid or expired")
            from auth_handler import create_token, rotate_user_session
            _existing_sid = user_doc.get("session_id")
            if _existing_sid:
                _sid = _existing_sid  # reuse — never self-kick on wallet login
            else:
                _sid = await rotate_user_session(db, {"_id": user_doc["_id"]})
            token = create_token(data={"sub": wallet_address}, session_id=_sid)
            print(f"🎫 JWT токен сгенерирован для: {wallet_address} (reuse_session={bool(_existing_sid)})")

            return {
                "status": "ok",
                "token": token,
                "is_new_user": is_new_user,
                "user": {
                    "id": user_doc.get("id", str(user_doc.get("_id"))),
                    "username": user_doc.get("username"),
                    "display_name": user_doc.get("display_name") or user_doc.get("username"),
                    "wallet_address": wallet_address,
                    "email": user_doc.get("email"),
                    "avatar": user_doc.get("avatar"),
                    "level": user_doc.get("level", 1),
                    "is_admin": user_doc.get("is_admin", False)
                }
            }

        except Exception as e:
            # Preserve intended HTTP status codes (400 duplicate username, 400 duplicate email,
            # 400 invalid TON address, etc.) — earlier this branch wrapped ALL
            # HTTPException raises into 500, hiding legitimate 4xx errors from the UI.
            if isinstance(e, HTTPException):
                raise
            print(f"💥 ОШИБКА В РОУТЕ verify_wallet: {str(e)}")
            logger.error("Full traceback: ", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/auth/me")
    async def get_current_user_info(current_user: User = Depends(get_current_user)):
        """Get current user info"""
        import time as _t
        _t0 = _t.monotonic()
        try:
            return await _build_me_response(current_user)
        except HTTPException:
            raise
        except Exception as e:
            # ANY unexpected error here returns HTTP 500, and the frontend
            # treats 5xx as "transient" and RETRIES FOREVER → the endless
            # "99%" preloader. Log the full traceback so the real cause is
            # visible in the server log instead of silently spinning.
            logger.error("[AUTH99] /auth/me CRASHED after %.0fms: %s",
                         (_t.monotonic() - _t0) * 1000, e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"/auth/me failed: {e}")

    async def _build_me_response(current_user: User):
        import time as _t
        _t0 = _t.monotonic()
        # Ищем пользователя по id (индекс, есть у каждого аккаунта); старые поля — только запасной путь
        user_doc = await db.users.find_one({"id": current_user.id}) if getattr(current_user, "id", None) else None
        if not user_doc and current_user.wallet_address:
            user_doc = await db.users.find_one({"wallet_address": current_user.wallet_address})
        if not user_doc and current_user.email:
            user_doc = await db.users.find_one({"email": current_user.email})
        if not user_doc and current_user.username:
            user_doc = await db.users.find_one({"username": current_user.username})

        if not user_doc:
            logger.warning("[AUTH99] /auth/me user NOT FOUND (wallet=%s email=%s username=%s)",
                           current_user.wallet_address, current_user.email, current_user.username)
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # Одноразовый приветственный бонус +0.5 TON (идемпотентно). Начисляется
        # «лениво» при первой авторизованной загрузке — так покрываются ВСЕ
        # способы регистрации (email, Google, Telegram, кошелёк) без правок в
        # каждом пути регистрации.
        try:
            from core.welcome import ensure_welcome_bonus, WELCOME_BONUS_TON
            if user_doc.get("id") and await ensure_welcome_bonus(db, {"id": user_doc["id"]}):
                user_doc["bonus_balance"] = float(user_doc.get("bonus_balance") or 0) + WELCOME_BONUS_TON
        except Exception:
            pass

        def _sf(v, default=0.0):
            try:
                if v is None or v == "":
                    return default
                return float(v)
            except (ValueError, TypeError):
                return default

        raw = user_doc.get("raw_address") or to_raw(user_doc.get("wallet_address") or "")
        display = user_doc.get("wallet_address")

        # Определяем тип аутентификации
        has_password = bool(user_doc.get("hashed_password"))
        has_google = bool(user_doc.get("google_id"))
        has_wallet = bool(user_doc.get("wallet_address"))

        if has_google:
            auth_type = "google"
        elif user_doc.get("auth_provider") == "telegram" and not has_password and not has_wallet:
            auth_type = "telegram"
        elif has_wallet and not has_password:
            auth_type = "wallet"
        else:
            auth_type = "email"

        # Check 2FA status
        has_2fa = bool(user_doc.get("is_2fa_enabled", False))
        has_two_factor_secret = bool(user_doc.get("two_factor_secret"))
        has_passkeys = bool(user_doc.get("passkeys") and len(user_doc.get("passkeys", [])) > 0)

        # P1.2: During the tutorial the practice buffer (added at /tutorial/start)
        # must be VISIBLE so the user can actually "buy" land and complete the
        # interactive steps. The buffer is 50 TON == 50,000 $CITY (1 TON = 1000
        # $CITY). It is fully removed by the snapshot rollback at
        # /finish, /reset and /abandon, restoring the exact pre-tutorial balance.
        raw_balance = _sf(user_doc.get("balance_ton"))
        displayed_balance = raw_balance
        # Reconciled tender escrow (0 when no active contracts; self-heals drift).
        _eff_frozen_city = await effective_frozen_city(db, user_doc)

        logger.info("[AUTH99] /auth/me OK user=%s balance=%s bonus=%s businesses=%s plots=%s took=%.0fms",
                    user_doc.get("id"), displayed_balance,
                    user_doc.get("bonus_balance", 0.0),
                    len(user_doc.get("businesses_owned") or []),
                    len(user_doc.get("plots_owned") or []),
                    (_t.monotonic() - _t0) * 1000)

        _blk_reason = ""
        if user_doc.get("is_blocked"):
            _raw_reason = user_doc.get("block_reason") or "Нарушение правил"
            _ulang = user_doc.get("language") or "en"
            try:
                from translation_service import translate_cached
                _blk_reason = await translate_cached(db, _raw_reason, _ulang, source_lang="ru")
            except Exception:
                _blk_reason = _raw_reason

        return {
            "id": user_doc.get("id", str(user_doc.get("_id"))),
            "is_blocked": bool(user_doc.get("is_blocked", False)),
            "block_reason": _blk_reason,
            "block_reason_original": user_doc.get("block_reason") or "",
            "username": user_doc.get("username"),
            "display_name": user_doc.get("display_name") or user_doc.get("username"),
            "email": user_doc.get("email"),
            "avatar": user_doc.get("avatar"),
            "profile_frame": user_doc.get("profile_frame"),       # cosmetic reward of the mini-game
            "alliance_id": user_doc.get("alliance_id"),
            "alliance_name": user_doc.get("alliance_name"),
            "alliance_tag": user_doc.get("alliance_tag"),
            "alliance_emblem": user_doc.get("alliance_emblem"),
            "wallet_address": user_doc.get("wallet_address"),
            "wallet_address_raw": raw,
            "wallet_address_display": display,
            "language": user_doc.get("language", "en"),
            "has_graduated_zero": bool(user_doc.get("has_graduated_zero", False)),
            "level": user_doc.get("level", 1),
            "xp": user_doc.get("xp", 0),
            "balance_ton": displayed_balance,
            "bonus_balance": _sf(user_doc.get("bonus_balance")),
            "frozen_for_tenders_ton": round(_eff_frozen_city / 1000.0, 6),
            "frozen_for_tenders_city": _eff_frozen_city,
            "total_turnover": user_doc.get("total_turnover", 0.0),
            "total_income": user_doc.get("total_income", 0.0),
            "plots_owned": user_doc.get("plots_owned", []),
            "businesses_owned": user_doc.get("businesses_owned", []),
            "is_admin": user_doc.get("is_admin", False),
            "is_bank": user_doc.get("is_bank", False),
            "is_2fa_enabled": has_2fa or has_two_factor_secret,
            "has_passkeys": has_passkeys,
            "max_plots": 999 if user_doc.get("is_admin", False) or user_doc.get("is_bank", False) or user_doc.get("role") in ["ADMIN", "BANK"] else 3,
            "auth_type": auth_type,
            # Telegram linking — surfaced so SettingsPage can show the binding state.
            "telegram_username": user_doc.get("telegram_username"),
            "telegram_chat_id": user_doc.get("telegram_chat_id"),
            "telegram_notifications": user_doc.get("telegram_notifications", False),
            # Unified linked flag (mirrors the quest-verify check) so the client
            # can gate Telegram-required actions before redirecting.
            "telegram_linked": bool(
                user_doc.get("telegram_id")
                or user_doc.get("telegram_user_id")
                or user_doc.get("telegram_chat_id")
            ),
            "auth_provider": user_doc.get("auth_provider"),
        }

    @router.get("/users/me/plots")
    async def get_my_plots(current_user: User = Depends(get_current_user)):
        """Получить все участки пользователя"""
        ui = await get_user_identifiers(current_user)
        if not ui["user"]:
            return {"plots": [], "total": 0}

        user_ids = ui["ids"]
        plots = []

        # Ищем участки в старой коллекции plots
        old_plots = await db.plots.find({
            "$or": [{"owner": uid} for uid in user_ids]
        }, {"_id": 0}).to_list(100)

        for plot in old_plots:
            city = await db.cities.find_one({"id": plot.get("city_id")}, {"_id": 0, "name": 1})
            plot["city_name"] = city.get("name", "GRAM Island") if city else "GRAM Island"

            # Add business info if exists
            if plot.get("business_id"):
                business = await db.businesses.find_one({"id": plot["business_id"]}, {"_id": 0})
                if business:
                    biz_config = resolve_business_config(business.get("business_type"))
                    plot["business_type"] = business.get("business_type")
                    plot["business_name"] = biz_config.get("name", business.get("business_type"))
                    plot["business_cost"] = business.get("base_cost_ton", biz_config.get("base_cost_ton", 0))

            plots.append(plot)

        # Ищем участки на GRAM Island
        island_plots = await db.plots.find({
            "island_id": "ton_island",
            "$or": [{"owner": uid} for uid in user_ids]
        }, {"_id": 0}).to_list(100)

        for plot in island_plots:
            zone_name = plot.get('zone', 'outer')
            plot["city_name"] = "GRAM Island"
            plot["island_id"] = "ton_island"

            # Add business info - check both business_id and inline business
            if plot.get("business_id"):
                business = await db.businesses.find_one({"id": plot["business_id"]}, {"_id": 0})
                if business:
                    biz_config = resolve_business_config(business.get("business_type"))
                    plot["business_type"] = business.get("business_type")
                    plot["business_name"] = biz_config.get("name", business.get("business_type"))
                    plot["business_cost"] = business.get("base_cost_ton", biz_config.get("base_cost_ton", 0))
            elif plot.get("business"):
                # Inline business data (from pre-assigned purchase)
                biz = plot["business"]
                plot["business_type"] = biz.get("type")
                plot["business_name"] = biz.get("name")
                plot["business_cost"] = plot.get("price_ton", 0)
                plot["business_icon"] = biz.get("icon")
                plot["business_tier"] = biz.get("tier", 1)
                plot["business_level"] = biz.get("level", 1)
                plot["monthly_income_ton"] = biz.get("monthly_income_ton", 0)
                plot["monthly_income_city"] = biz.get("monthly_income_city", 0)

            # Check if already in plots list
            if not any(p.get("id") == plot.get("id") for p in plots):
                plots.append(plot)

        return {"plots": plots, "total": len(plots)}

    @router.get("/users/me/businesses")
    async def get_my_businesses(current_user: User = Depends(get_current_user)):
        """Получить все бизнесы пользователя"""
        _wallet_owner_keys = await resolve_owner_keys(db, current_user.id) or [current_user.id]
        if current_user.wallet_address:
            _wallet_owner_keys = list(set(_wallet_owner_keys + [current_user.wallet_address]))
        query = owner_businesses_query(_wallet_owner_keys)

        businesses = await db.businesses.find(query, {"_id": 0}).to_list(100)

        # Добавляем информацию о типе бизнеса
        for biz in businesses:
            bt = resolve_business_config(biz.get("business_type")) or {}
            biz["produces"] = bt.get("produces")
            biz["consumes"] = bt.get("consumes", [])
            biz["tier"] = bt.get("tier", 1)

        return {"businesses": businesses, "total": len(businesses)}



    @router.post("/admin/seed-test-users")
    async def seed_test_users(http_request: Request):
        """Create/update the two test accounts (admin + regular user).

        Protected by the ADMIN_SECRET shared secret sent in the
        ``X-Admin-Secret`` header (or ?secret= query). Idempotent.
        """
        import hashlib as _hashlib
        import hmac as _hmac
        if os.environ.get("ENV", "").lower() == "production":
            raise HTTPException(status_code=404, detail="Not found")          # never on the live server
        secret = os.environ.get("ADMIN_SECRET", "")
        provided = http_request.headers.get("X-Admin-Secret", "")             # header only: URLs end up in logs
        if not secret or not _hmac.compare_digest(provided.encode(), secret.encode()):
            raise HTTPException(status_code=403, detail="Forbidden")

        from auth_handler import pwd_context, generate_avatar_from_initials
        import uuid as _uuid

        seed_defs = [
            {
                "username": "SanyaNazarov",
                "email": "sanyanazarov212@gmail.com",
                "password": os.environ.get("SEED_ADMIN_PASSWORD", ""),
                "is_admin": True,
                "roles": ["superadmin"],
                "balance_ton": 1230.0,
                "level": 10,
                "display_name": "Sanya Admin",
                "telegram_chat_id": "100000001",
            },
            {
                "username": "testuser",
                "email": "testuser@example.com",
                "password": os.environ.get("SEED_USER_PASSWORD", ""),
                "is_admin": False,
                "roles": [],
                "balance_ton": 100.0,
                "level": 1,
                "display_name": "Test User",
            },
        ]

        results = []
        for u in seed_defs:
            existing = await db.users.find_one({
                "$or": [{"username": u["username"]}, {"email": u["email"]}]
            })
            base_set = {
                "hashed_password": pwd_context.hash(u["password"]),
                "is_admin": u["is_admin"],
                "roles": u.get("roles", []),
                "balance_ton": u["balance_ton"],
                "level": u["level"],
                "display_name": u["display_name"],
                "tutorial_active": False,
                "tutorial_completed": True,
            }
            if u.get("telegram_chat_id"):
                base_set["telegram_chat_id"] = u["telegram_chat_id"]
            if existing:
                await db.users.update_one({"_id": existing["_id"]}, {"$set": base_set})
                results.append({"email": u["email"], "action": "updated", "is_admin": u["is_admin"]})
            else:
                doc = {
                    "id": str(_uuid.uuid4()),
                    "username": u["username"],
                    "email": u["email"],
                    "avatar": generate_avatar_from_initials(u["username"]),
                    "language": "ru",
                    "registration_method": "email",
                    "email_verified": True,
                    "is_2fa_enabled": False,
                    "two_factor_secret": None,
                    "backup_codes": [],
                    "xp": 0,
                    "total_turnover": 0,
                    "total_income": 0.0,
                    "plots_owned": [],
                    "businesses_owned": [],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_login": datetime.now(timezone.utc).isoformat(),
                    **base_set,
                }
                await db.users.insert_one(doc)
                try:
                    import analytics
                    await analytics.track(doc["id"], "register", channel="wallet")
                    await analytics.mark_active(doc["id"])
                except Exception:
                    pass
                results.append({"email": u["email"], "action": "created", "is_admin": u["is_admin"]})

        return {"status": "ok", "users": results}


    return router
