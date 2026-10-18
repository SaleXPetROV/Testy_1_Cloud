"""Round 3 hard-mode 2FA gate — CRITICAL flow that actually toggles admin.two_factor_secret.

Safety net: uses a try/finally that always disables 2FA and deletes two_factor_secret,
so even if any assertion fails the admin account is restored.
"""
import os
import sys
import asyncio
from pathlib import Path

import pyotp
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")


def test_hardmode_2fa_gate_full_flow():
    asyncio.run(_run_hardmode_flow())


async def _run_hardmode_flow():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    secret = pyotp.random_base32()

    # 1. Login (BEFORE enabling 2FA — otherwise middleware would need TOTP)
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    token = r.json()["token"]
    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    admin_doc = await db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 1, "two_factor_secret": 1, "is_2fa_enabled": 1})
    assert admin_doc, "admin user not found"
    original_secret = admin_doc.get("two_factor_secret")
    original_enabled = admin_doc.get("is_2fa_enabled", False)

    try:
        # 2. Enable 2FA on admin doc
        await db.users.update_one(
            {"email": ADMIN_EMAIL},
            {"$set": {"is_2fa_enabled": True, "two_factor_secret": secret}},
        )

        # 3. POST /api/admin/telegram-settings WITHOUT X-Admin-TOTP → 401 'TOTP required'
        r_no_totp = requests.post(f"{BASE_URL}/api/admin/telegram-settings", headers=hdrs, json={})
        assert r_no_totp.status_code == 401, f"expected 401, got {r_no_totp.status_code}: {r_no_totp.text}"
        assert "TOTP required" in r_no_totp.text, f"body: {r_no_totp.text}"

        # 4. POST with WRONG TOTP → 401 'Invalid TOTP'
        r_wrong = requests.post(
            f"{BASE_URL}/api/admin/telegram-settings",
            headers={**hdrs, "X-Admin-TOTP": "000000"},
            json={},
        )
        assert r_wrong.status_code == 401, f"expected 401 for wrong TOTP, got {r_wrong.status_code}"
        assert "Invalid TOTP" in r_wrong.text

        # 5. POST with CORRECT TOTP → passes middleware (route may 200/404/422 but NOT 401 TOTP)
        code = pyotp.TOTP(secret).now()
        r_ok = requests.post(
            f"{BASE_URL}/api/admin/telegram-settings",
            headers={**hdrs, "X-Admin-TOTP": code},
            json={},
        )
        assert r_ok.status_code != 401 or "TOTP" not in r_ok.text, \
            f"correct TOTP still rejected: {r_ok.status_code} {r_ok.text[:300]}"

        # 6. GET /api/admin/telegram-settings still works WITHOUT TOTP (reads exempt)
        r_get = requests.get(f"{BASE_URL}/api/admin/telegram-settings", headers=hdrs)
        assert r_get.status_code != 401 or "TOTP" not in r_get.text, \
            "GET should be exempt from admin-2FA gate"

        # 7. Whitelist: /api/auth/login still works with no TOTP header
        r_login = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PW},
        )
        # login may require 2FA at the auth layer (requires_2fa=true), but MUST NOT
        # be gated by the admin-middleware for missing X-Admin-TOTP.
        assert r_login.status_code in (200, 202), f"whitelisted /api/auth/login gated: {r_login.status_code} {r_login.text[:200]}"

    finally:
        # 8. TEARDOWN — always restore
        restore = {
            "is_2fa_enabled": bool(original_enabled),
        }
        if original_secret is None:
            await db.users.update_one(
                {"email": ADMIN_EMAIL},
                {"$set": restore, "$unset": {"two_factor_secret": ""}},
            )
        else:
            restore["two_factor_secret"] = original_secret
            await db.users.update_one({"email": ADMIN_EMAIL}, {"$set": restore})
        client.close()
