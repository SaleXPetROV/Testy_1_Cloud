"""Iteration 2 bug-fix verification:
   BUG #1: JWT TTL extended to 365 days
   Regression: Rally broadcast → testuser notifications (promoBroadcast i18n key)
"""
import os
import time
from datetime import datetime, timezone

import pytest
import requests
from jose import jwt

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to frontend env at runtime
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL"):
                    BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
    except Exception:
        pass

ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER = {"email": "testuser@example.com", "password": "Test1234!"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login {creds['email']} → {r.status_code}: {r.text[:400]}"
    data = r.json()
    assert "token" in data, data
    return data["token"]


# ─── BUG #1 — JWT TTL 365 days ─────────────────────────────────────────
class TestJWTLongTTL:
    def test_user_token_ttl_is_about_365_days(self):
        token = _login(USER)
        payload = jwt.get_unverified_claims(token)
        assert "exp" in payload
        exp_ts = int(payload["exp"])
        now_ts = int(datetime.now(timezone.utc).timestamp())
        delta_days = (exp_ts - now_ts) / 86400.0
        # Expect ~365, allow tolerance (must be at least 300 to prove it's not 7)
        assert delta_days > 300, f"JWT TTL only {delta_days:.1f} days (expected ~365)"
        assert delta_days < 400, f"JWT TTL {delta_days:.1f} days looks unreasonable"

    def test_admin_token_ttl_is_about_365_days(self):
        token = _login(ADMIN)
        payload = jwt.get_unverified_claims(token)
        exp_ts = int(payload["exp"])
        now_ts = int(datetime.now(timezone.utc).timestamp())
        delta_days = (exp_ts - now_ts) / 86400.0
        assert delta_days > 300, f"Admin JWT TTL only {delta_days:.1f} days"

    def test_token_valid_across_multiple_requests(self):
        token = _login(USER)
        headers = {"Authorization": f"Bearer {token}"}
        # Simulate multiple "reloads"
        for i in range(5):
            r = requests.get(f"{BASE_URL}/api/auth/me", headers=headers, timeout=15)
            assert r.status_code == 200, f"iteration {i}: /auth/me → {r.status_code}: {r.text[:200]}"
            data = r.json()
            assert data.get("email") == USER["email"], data
            time.sleep(0.2)


# ─── REGRESSION — Rally broadcast still works ──────────────────────────
class TestRallyBroadcastRegression:
    def test_admin_broadcast_and_user_receives_notification(self):
        admin_token = _login(ADMIN)
        user_token = _login(USER)
        admin_h = {"Authorization": f"Bearer {admin_token}"}
        user_h = {"Authorization": f"Bearer {user_token}"}

        # Ensure campaign is active (best-effort - endpoint may or may not need start)
        # Try broadcast — if it 400s with "no active campaign", start one
        r = requests.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast",
            headers=admin_h, json={}, timeout=30,
        )
        if r.status_code == 400 and "campaign" in r.text.lower():
            # try to start a campaign
            start = requests.post(
                f"{BASE_URL}/api/admin/promo/referral-rally/start",
                headers=admin_h,
                json={"days": 7, "prizes_ton": [100, 50, 20], "per_active_ton": 1.5},
                timeout=30,
            )
            assert start.status_code in (200, 201), f"start → {start.status_code}: {start.text[:400]}"
            r = requests.post(
                f"{BASE_URL}/api/admin/promo/referral-rally/broadcast",
                headers=admin_h, json={}, timeout=30,
            )

        assert r.status_code == 200, f"broadcast → {r.status_code}: {r.text[:400]}"
        body = r.json()
        assert body.get("ok") is True or "subscribers" in body, body

        # Poll user notifications for promoBroadcast payload
        found = None
        for _ in range(8):
            nr = requests.get(f"{BASE_URL}/api/notifications", headers=user_h, timeout=15)
            assert nr.status_code == 200, nr.text[:200]
            items = nr.json()
            # response may be list OR object
            if isinstance(items, dict):
                items = items.get("notifications") or items.get("items") or []
            for n in items:
                payload = n.get("payload") or {}
                if (
                    n.get("type") == "promo_announcement"
                    and payload.get("i18n_key") == "promoBroadcast"
                ):
                    found = n
                    break
            if found:
                break
            time.sleep(1.0)
        assert found is not None, "No promo_announcement with i18n_key=promoBroadcast found in testuser notifications"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
