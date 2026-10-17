"""ITER7 SECURITY: username-only fallback removed from _find_user_by_telegram.

Covers:
  * Attacker with DIFFERENT telegram_id but SAME username must NOT log into
    an existing account (must get choice_required).
  * Returning user with SAME telegram_id but CHANGED username still auto-logins
    into the same account.
  * Legacy username-only users row (no telegram_id fields) is NOT auto-matched.
  * Regression: new id -> choice_required, create -> token + /auth/me,
    second login same id -> ok, tampered/garbage/missing hash -> 401.
  * Regression: Google OAuth redirect_uri validation (quick check).
"""
import asyncio
import time
import uuid

import pytest
import requests

from test_tg_miniapp_auth_resilience_iter_current import (
    API,
    BASE_URL,
    DB_NAME,
    MONGO_URL,
    build_init_data,
    cleanup_tg,
)

UNIQ = uuid.uuid4().hex[:8]
BASE_ID = 950_000_000 + int(time.time()) % 9_000_000


def _mongo():
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(MONGO_URL)


def _run(coro):
    return asyncio.run(coro)


def _insert_legacy(username):
    async def _do():
        cli = _mongo()
        doc = {
            "id": f"TEST_legacy_{UNIQ}",
            "username": f"TEST_legacy_{UNIQ}",
            "display_name": "TEST legacy",
            "telegram_username": username,
            "balance_ton": 0.0,
            "language": "en",
            "registration_method": "telegram",
        }
        await cli[DB_NAME].users.insert_one(doc)
        cli.close()
    _run(_do())


def _delete_by_id(user_id):
    async def _do():
        cli = _mongo()
        res = await cli[DB_NAME].users.delete_many({"id": user_id})
        cli.close()
        return res.deleted_count
    return _run(_do())


def _find_by_username_field(username):
    async def _do():
        cli = _mongo()
        docs = await cli[DB_NAME].users.find(
            {"telegram_username": username}, {"_id": 0, "id": 1, "telegram_id": 1}
        ).to_list(20)
        cli.close()
        return docs
    return _run(_do())


def _post_miniapp(init_data, create=False):
    url = f"{API}/auth/telegram/miniapp/create" if create else f"{API}/auth/telegram/miniapp"
    return requests.post(url, json={"init_data": init_data}, timeout=45)


# --------------------------------------------------------------------------- #
# 1. PRIMARY SECURITY TEST: same username, different telegram_id
# --------------------------------------------------------------------------- #
class TestUsernameFallbackRemoved:
    victim_username = f"victim_{UNIQ}"
    victim_id = BASE_ID + 11
    attacker_id = BASE_ID + 12

    @classmethod
    def teardown_class(cls):
        cleanup_tg(cls.victim_id)
        cleanup_tg(cls.attacker_id)

    def test_attacker_same_username_different_id_cannot_login(self):
        # (1) victim account created
        victim_init = build_init_data(self.victim_id, first_name="Victim",
                                      username=self.victim_username)
        r = _post_miniapp(victim_init, create=True)
        assert r.status_code == 200, r.text
        vdata = r.json()
        assert vdata.get("status") == "ok", vdata
        vtoken = vdata.get("access_token") or vdata.get("token")
        assert isinstance(vtoken, str) and vtoken
        victim_user_id = (vdata.get("user") or {}).get("id")
        assert victim_user_id

        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {vtoken}"}, timeout=30)
        assert me.status_code == 200, me.text
        assert me.json().get("id") == victim_user_id

        # (2) attacker: different telegram_id, SAME username
        atk_init = build_init_data(self.attacker_id, first_name="Attacker",
                                   username=self.victim_username)
        ra = _post_miniapp(atk_init)
        assert ra.status_code == 200, ra.text
        adata = ra.json()
        assert adata.get("status") == "choice_required", (
            f"SECURITY: username fallback still active -> {adata}"
        )
        assert not adata.get("access_token") and not adata.get("token"), adata
        assert (adata.get("telegram") or {}).get("id") == str(self.attacker_id)

        # victim account untouched / still owned by original tg id
        docs = _find_by_username_field(self.victim_username)
        assert len(docs) == 1, docs
        assert docs[0]["id"] == victim_user_id
        assert str(docs[0]["telegram_id"]) == str(self.victim_id)


# --------------------------------------------------------------------------- #
# 2. Returning user with CHANGED username still auto-logins
# --------------------------------------------------------------------------- #
class TestReturningUserChangedUsername:
    tg_id = BASE_ID + 21

    @classmethod
    def teardown_class(cls):
        cleanup_tg(cls.tg_id)

    def test_same_id_new_username_logs_into_same_account(self):
        old_u = f"old_{UNIQ}"
        new_u = f"new_{UNIQ}"
        r = _post_miniapp(build_init_data(self.tg_id, username=old_u), create=True)
        assert r.status_code == 200, r.text
        created = r.json()
        uid = (created.get("user") or {}).get("id")
        assert uid

        r2 = _post_miniapp(build_init_data(self.tg_id, username=new_u))
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2.get("status") == "ok", d2
        token = d2.get("access_token") or d2.get("token")
        assert token
        assert (d2.get("user") or {}).get("id") == uid
        assert (d2.get("user") or {}).get("telegram_username") == new_u
        assert d2.get("is_new_signup") is False

        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30)
        assert me.status_code == 200
        assert me.json().get("id") == uid


# --------------------------------------------------------------------------- #
# 3. Legacy username-only row is NOT auto-logged-in
# --------------------------------------------------------------------------- #
class TestLegacyUsernameOnlyRow:
    tg_id = BASE_ID + 31
    legacy_username = f"legacy_{UNIQ}"
    legacy_doc_id = f"TEST_legacy_{UNIQ}"

    @classmethod
    def teardown_class(cls):
        _delete_by_id(cls.legacy_doc_id)
        cleanup_tg(cls.tg_id)

    def test_legacy_row_not_matched(self):
        _insert_legacy(self.legacy_username)
        r = _post_miniapp(build_init_data(self.tg_id, username=self.legacy_username))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "choice_required", (
            f"SECURITY: legacy username-only row auto-matched -> {data}"
        )
        assert not data.get("access_token") and not data.get("token")
        # legacy doc untouched (no telegram_id injected)
        docs = _find_by_username_field(self.legacy_username)
        assert len(docs) == 1 and docs[0]["id"] == self.legacy_doc_id, docs
        assert "telegram_id" not in docs[0]


# --------------------------------------------------------------------------- #
# 4. Regression: normal miniapp flow + signature validation
# --------------------------------------------------------------------------- #
class TestMiniappRegression:
    tg_id = BASE_ID + 41

    @classmethod
    def teardown_class(cls):
        cleanup_tg(cls.tg_id)

    def test_new_id_choice_then_create_then_login(self):
        init = build_init_data(self.tg_id, username=f"reg_{UNIQ}")
        r1 = _post_miniapp(init)
        assert r1.status_code == 200, r1.text
        assert r1.json().get("status") == "choice_required", r1.json()

        r2 = _post_miniapp(init, create=True)
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2.get("status") == "ok" and d2.get("is_new_signup") is True, d2
        token = d2.get("access_token") or d2.get("token")
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30)
        assert me.status_code == 200, me.text

        r3 = _post_miniapp(init)
        assert r3.status_code == 200, r3.text
        d3 = r3.json()
        assert d3.get("status") == "ok", d3
        assert d3.get("is_new_signup") is False
        assert (d3.get("user") or {}).get("id") == (d2.get("user") or {}).get("id")

    @pytest.mark.parametrize("bad", ["tampered", "garbage", "nohash", "empty"])
    def test_invalid_signature_rejected(self, bad):
        good = build_init_data(BASE_ID + 42, username=f"bad_{UNIQ}")
        if bad == "tampered":
            payload = good[:-4] + "dead"
        elif bad == "garbage":
            payload = "user=%7B%22id%22%3A1%7D&auth_date=1&hash=abc"
        elif bad == "nohash":
            payload = "&".join(p for p in good.split("&") if not p.startswith("hash="))
        else:
            payload = ""
        r = _post_miniapp(payload)
        assert r.status_code in (400, 401, 422), f"{bad} -> {r.status_code} {r.text[:200]}"


# --------------------------------------------------------------------------- #
# 5. Regression: Google OAuth redirect_uri validation (quick)
# --------------------------------------------------------------------------- #
class TestGoogleRedirectUri:
    def test_same_host_callback_not_configured(self):
        r = requests.post(f"{API}/auth/google/callback",
                          json={"code": "x", "redirect_uri": f"{BASE_URL}/auth/google/callback"},
                          timeout=30)
        assert r.status_code == 503, f"{r.status_code} {r.text[:200]}"
        assert "configur" in r.text.lower(), r.text[:200]

    def test_foreign_origin_rejected(self):
        r = requests.post(f"{API}/auth/google/callback",
                          json={"code": "x", "redirect_uri": "https://evil.example.com/auth/google/callback"},
                          timeout=30)
        assert r.status_code == 400, f"{r.status_code} {r.text[:200]}"
        assert "redirect_uri" in r.text.lower(), r.text[:200]
