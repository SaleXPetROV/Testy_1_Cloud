"""Iteration 10 — PRIMARY: ton_proof allow-list must ALWAYS trust the native
Telegram Wallet proxy hosts (walletbot.net + *.walletbot.net).

Covers:
  * core.ton_proof._get_allowed_domains() always contains walletbot entries
  * core.ton_proof._domain_allowed() wildcard/exact/negative matching
  * verify_ton_proof() domain branch: evil.com -> "domain 'evil.com' not allowed",
    proxy.walletbot.net -> passes the domain check (fails later on pubkey/sig)
  * REGRESSIONS: TON manifest, Google callback 401 surfacing, Telegram miniapp
    auth + username fallback removal
"""
import base64
import os
import sys
import time

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/backend/tests")

from core.ton_proof import (  # noqa: E402
    TonProofError,
    _domain_allowed,
    _get_allowed_domains,
    verify_ton_proof,
)

_fe = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = _base.rstrip("/")
API = f"{BASE_URL}/api"
TIMEOUT = 45

# a syntactically valid mainnet address (raw form) for the verify path
SAMPLE_ADDR = "0:" + "ab" * 32


def _proof(domain_value: str, ts=None):
    return {
        "timestamp": int(ts or time.time()),
        "domain": {"lengthBytes": len(domain_value), "value": domain_value},
        "signature": base64.b64encode(b"\x01" * 64).decode(),
        "payload": "nonce-iter10",
    }


# ───────────────────── _get_allowed_domains ─────────────────────
class TestAllowedDomains:
    def test_walletbot_always_present_no_env(self, monkeypatch):
        monkeypatch.delenv("TON_PROOF_ALLOWED_DOMAINS", raising=False)
        allowed = _get_allowed_domains()
        assert "walletbot.net" in allowed, allowed
        assert "*.walletbot.net" in allowed, allowed
        # dev defaults still there when env unset
        assert "localhost" in allowed, allowed

    def test_walletbot_always_present_with_env(self, monkeypatch):
        monkeypatch.setenv("TON_PROOF_ALLOWED_DOMAINS", "gramcity.app")
        allowed = _get_allowed_domains()
        assert allowed >= {"gramcity.app", "walletbot.net", "*.walletbot.net"}, allowed
        # explicit env replaces dev defaults
        assert "localhost" not in allowed, allowed

    def test_env_multi_domain_parsing(self, monkeypatch):
        monkeypatch.setenv("TON_PROOF_ALLOWED_DOMAINS", " GramCity.app , www.gramcity.app ,")
        allowed = _get_allowed_domains()
        assert "gramcity.app" in allowed and "www.gramcity.app" in allowed, allowed


# ───────────────────── _domain_allowed ─────────────────────
class TestDomainAllowed:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("TON_PROOF_ALLOWED_DOMAINS", "gramcity.app")
        self.allowed = _get_allowed_domains()

    @pytest.mark.parametrize(
        "domain",
        ["proxy.walletbot.net", "walletbot.net", "a.b.walletbot.net", "PROXY.WalletBot.net", "gramcity.app"],
    )
    def test_allowed(self, domain):
        assert _domain_allowed(domain, self.allowed) is True, domain

    @pytest.mark.parametrize(
        "domain",
        ["evil.com", "gramcity.games", "walletbot.net.evil.com", "notwalletbot.net", "", None],
    )
    def test_not_allowed(self, domain):
        assert _domain_allowed(domain, self.allowed) is False, domain


# ───────────────────── verify_ton_proof domain branch ─────────────────────
class TestVerifyDomainBranch:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("TON_PROOF_ALLOWED_DOMAINS", "gramcity.app")

    def test_evil_domain_rejected(self):
        with pytest.raises(TonProofError) as ei:
            verify_ton_proof(SAMPLE_ADDR, _proof("evil.com"), int(time.time()),
                             expected_payload="nonce-iter10")
        assert "domain 'evil.com' not allowed" in str(ei.value), str(ei.value)

    def test_gramcity_games_rejected(self):
        with pytest.raises(TonProofError) as ei:
            verify_ton_proof(SAMPLE_ADDR, _proof("gramcity.games"), int(time.time()),
                             expected_payload="nonce-iter10")
        assert "not allowed" in str(ei.value)

    def test_walletbot_proxy_passes_domain_check(self):
        """proxy.walletbot.net must NOT fail the domain check — it may still
        fail later (no pubkey / bad signature) which is expected."""
        with pytest.raises(TonProofError) as ei:
            verify_ton_proof(SAMPLE_ADDR, _proof("proxy.walletbot.net"), int(time.time()),
                             expected_payload="nonce-iter10")
        msg = str(ei.value)
        assert "not allowed" not in msg, f"domain check wrongly rejected walletbot: {msg}"
        assert ("public key" in msg or "signature" in msg), msg

    def test_configured_domain_passes_domain_check(self):
        with pytest.raises(TonProofError) as ei:
            verify_ton_proof(SAMPLE_ADDR, _proof("gramcity.app"), int(time.time()),
                             expected_payload="nonce-iter10")
        assert "not allowed" not in str(ei.value), str(ei.value)

    def test_stale_timestamp_still_rejected(self):
        with pytest.raises(TonProofError) as ei:
            verify_ton_proof(SAMPLE_ADDR, _proof("proxy.walletbot.net", ts=time.time() - 999999),
                             int(time.time()))
        assert "timestamp" in str(ei.value), str(ei.value)

    def test_nonce_mismatch_rejected_for_walletbot(self):
        with pytest.raises(TonProofError) as ei:
            verify_ton_proof(SAMPLE_ADDR, _proof("proxy.walletbot.net"), int(time.time()),
                             expected_payload="other-nonce")
        assert "payload/nonce mismatch" in str(ei.value), str(ei.value)


# ───────────────────── REGRESSION: TON manifest ─────────────────────
class TestManifestRegression:
    def test_manifest(self):
        r = requests.get(f"{API}/tonconnect-manifest-v3.json", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        m = r.json()
        assert m["url"] == BASE_URL, m
        assert m["iconUrl"] == f"{BASE_URL}/tonconnect-icon-v2.png", m
        assert "gramcity.games" not in r.text, r.text[:300]

    def test_icon_reachable(self):
        r = requests.get(f"{BASE_URL}/tonconnect-icon-v2.png", timeout=TIMEOUT)
        assert r.status_code == 200, r.status_code


# ───────────────────── REGRESSION: Google callback ─────────────────────
class TestGoogleRegression:
    def test_callback_401_with_google_reason(self):
        r = requests.post(
            f"{API}/auth/google/callback",
            json={"code": "fake_iter10", "redirect_uri": f"{BASE_URL}/auth/google/callback"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 401, f"{r.status_code}: {r.text[:400]}"
        detail = r.json().get("detail", "")
        assert detail.startswith("Failed to exchange authorization code with Google:"), detail
        assert "invalid_client" in detail, detail
        assert "Auth error" not in detail, detail

    def test_foreign_redirect_uri_400(self):
        r = requests.post(
            f"{API}/auth/google/callback",
            json={"code": "fake_iter10", "redirect_uri": "https://evil.com/auth/google/callback"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 400, f"{r.status_code}: {r.text[:300]}"
        assert "Invalid redirect_uri" in r.json().get("detail", ""), r.text[:300]


# ───────────────────── REGRESSION: Telegram miniapp ─────────────────────
from test_tg_miniapp_auth_resilience_iter_current import build_init_data, cleanup_tg  # noqa: E402


class TestTelegramRegression:
    TG_ID = 910100001
    TG_ID2 = 910100002
    USERNAME = "iter10_shared_user"

    @pytest.fixture(scope="class", autouse=True)
    def _cleanup(self):
        cleanup_tg(self.TG_ID)
        cleanup_tg(self.TG_ID2)
        yield
        cleanup_tg(self.TG_ID)
        cleanup_tg(self.TG_ID2)

    def test_01_new_user_choice_required(self):
        init = build_init_data(self.TG_ID, first_name="Iter10", username=self.USERNAME)
        r = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("status") == "choice_required", r.json()

    def test_02_create_and_me(self):
        init = build_init_data(self.TG_ID, first_name="Iter10", username=self.USERNAME)
        r = requests.post(f"{API}/auth/telegram/miniapp/create", json={"init_data": init}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("status") == "ok", d
        token = d.get("token") or d.get("access_token")
        assert token, d
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        assert me.status_code == 200, me.text[:300]

    def test_03_returning_user_ok(self):
        init = build_init_data(self.TG_ID, first_name="Iter10", username=self.USERNAME)
        r = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("status") == "ok", r.json()

    def test_04_tampered_hash_rejected(self):
        init = build_init_data(self.TG_ID, first_name="Iter10", username=self.USERNAME)
        tampered = init[:-4] + "dead"
        r = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": tampered}, timeout=TIMEOUT)
        assert r.status_code in (400, 401), f"{r.status_code}: {r.text[:300]}"

    def test_05_username_fallback_removed(self):
        """Different telegram_id with the SAME username must NOT log into the
        existing account."""
        init = build_init_data(self.TG_ID2, first_name="Iter10b", username=self.USERNAME)
        r = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("status") == "choice_required", r.json()
