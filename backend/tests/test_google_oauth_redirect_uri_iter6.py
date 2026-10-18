"""Iteration 6 — Google OAuth redirect_uri whitelist fix (F27) + Telegram miniapp regression.

Covers:
  * POST /api/auth/google/callback  redirect_uri validation (400 'Invalid redirect_uri'
    must NOT trigger for legitimate same-origin callback URLs)
  * request Origin/Referer trust for custom domains
  * open-redirect (foreign origin), wrong path, URL fragment -> 400
  * GET/POST /api/auth/google/init  (PKCE bootstrap)
  * REGRESSION: POST /api/auth/telegram/miniapp valid/tampered initData
"""
import os

import pytest
import requests
from dotenv import dotenv_values

_fe = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = f"{BASE_URL}/api"

CALLBACK = "/auth/google/callback"


def _detail(r):
    try:
        d = r.json()
        return str(d.get("detail") or d.get("message") or d)
    except Exception:
        return r.text[:300]


def _post_cb(redirect_uri, headers=None, code="x"):
    return requests.post(
        f"{API}/auth/google/callback",
        json={"code": code, "redirect_uri": redirect_uri},
        headers=headers or {},
        timeout=30,
    )


# ---------- redirect_uri validation (the fix) ----------
class TestGoogleRedirectUriValidation:
    def test_preview_origin_callback_passes_validation(self):
        r = _post_cb(f"{BASE_URL}{CALLBACK}")
        d = _detail(r)
        assert r.status_code != 400, f"redirect_uri rejected: {r.status_code} {d}"
        assert "Invalid redirect_uri" not in d
        assert "not configured" in d.lower(), f"expected 'not configured', got {r.status_code} {d}"
        assert r.status_code in (500, 503), f"unexpected status {r.status_code}: {d}"

    def test_request_origin_trusted_custom_domain_direct_backend(self):
        """Origin trust verified against the backend directly.

        NOTE: through the preview k8s ingress the inbound `Origin` header is NOT
        forwarded as-is, so the Origin-only path cannot be asserted externally
        (see test_request_origin_not_forwarded_by_ingress). Real browsers also
        send `Referer`, which IS forwarded and is trusted as well.
        """
        r = requests.post(
            "http://localhost:8001/api/auth/google/callback",
            json={"code": "x", "redirect_uri": "https://gramcity.app/auth/google/callback"},
            headers={"Origin": "https://gramcity.app"}, timeout=30)
        d = _detail(r)
        assert "Invalid redirect_uri" not in d, f"custom-domain Origin not trusted: {r.status_code} {d}"
        assert "not configured" in d.lower(), f"got {r.status_code} {d}"

    def test_request_origin_not_forwarded_by_ingress(self):
        """Documents the environment limitation (informational, expected 400)."""
        r = _post_cb("https://gramcity.app/auth/google/callback",
                     headers={"Origin": "https://gramcity.app"})
        assert r.status_code == 400  # ingress rewrites/strips Origin -> falls back to reject

    def test_referer_trusted_custom_domain(self):
        r = _post_cb("https://gramcity.app/auth/google/callback",
                     headers={"Referer": "https://gramcity.app/auth"})
        d = _detail(r)
        assert "Invalid redirect_uri" not in d, f"Referer origin not trusted: {r.status_code} {d}"

    def test_foreign_origin_blocked(self):
        r = _post_cb("https://evil.com/auth/google/callback")
        assert r.status_code == 400, f"open redirect allowed! {r.status_code} {_detail(r)}"
        assert "Invalid redirect_uri" in _detail(r)

    def test_foreign_redirect_with_our_origin_header_blocked(self):
        r = _post_cb("https://evil.com/auth/google/callback",
                     headers={"Origin": BASE_URL})
        assert r.status_code == 400, f"{r.status_code} {_detail(r)}"
        assert "Invalid redirect_uri" in _detail(r)

    def test_trusted_origin_wrong_path_blocked(self):
        r = _post_cb("https://gramcity.app/evil", headers={"Origin": "https://gramcity.app"})
        assert r.status_code == 400, f"non-callback path allowed! {r.status_code} {_detail(r)}"
        assert "Invalid redirect_uri" in _detail(r)

    def test_fragment_blocked(self):
        r = _post_cb("https://gramcity.app/auth/google/callback#x",
                     headers={"Origin": "https://gramcity.app"})
        assert r.status_code == 400, f"fragment allowed! {r.status_code} {_detail(r)}"
        assert "Invalid redirect_uri" in _detail(r)

    def test_non_http_scheme_blocked(self):
        r = _post_cb("javascript:alert(1)")
        assert r.status_code == 400
        assert "Invalid redirect_uri" in _detail(r)

    def test_empty_or_missing_redirect_uri(self):
        r = _post_cb("")
        assert r.status_code in (400, 422), f"{r.status_code} {_detail(r)}"
        r2 = requests.post(f"{API}/auth/google/callback", json={"code": "x"}, timeout=30)
        assert r2.status_code in (400, 422), f"{r2.status_code} {_detail(r2)}"

    def test_bad_state_rejected_before_config(self):
        r = requests.post(f"{API}/auth/google/callback", json={
            "code": "x", "redirect_uri": f"{BASE_URL}{CALLBACK}", "state": "bogus-state-xyz",
        }, timeout=30)
        assert r.status_code == 400
        assert "OAuth state" in _detail(r)


# ---------- PKCE bootstrap ----------
class TestGoogleInit:
    def test_get_not_supported(self):
        """Endpoint is POST-only (frontend uses POST) — GET returns 405."""
        r = requests.get(f"{API}/auth/google/init", timeout=30)
        assert r.status_code == 405

    @pytest.mark.parametrize("method", ["post"])
    def test_init_returns_pkce(self, method):
        r = getattr(requests, method)(f"{API}/auth/google/init", timeout=30)
        assert r.status_code == 200, f"{r.status_code} {_detail(r)}"
        data = r.json()
        for k in ("state", "code_challenge", "code_challenge_method"):
            assert k in data, f"missing {k} in {data}"
            assert isinstance(data[k], str) and data[k]
        assert data["code_challenge_method"] == "S256"
        assert "_id" not in data

    def test_init_state_unique(self):
        s1 = requests.post(f"{API}/auth/google/init", timeout=30).json()["state"]
        s2 = requests.post(f"{API}/auth/google/init", timeout=30).json()["state"]
        assert s1 != s2

    def test_init_state_is_consumable_once(self):
        state = requests.post(f"{API}/auth/google/init", timeout=30).json()["state"]
        body = {"code": "x", "redirect_uri": f"{BASE_URL}{CALLBACK}", "state": state}
        r1 = requests.post(f"{API}/auth/google/callback", json=body, timeout=30)
        # valid state consumed -> falls through to config error, not 400
        assert "OAuth state" not in _detail(r1), f"fresh state rejected: {r1.status_code} {_detail(r1)}"
        r2 = requests.post(f"{API}/auth/google/callback", json=body, timeout=30)
        assert r2.status_code == 400 and "OAuth state" in _detail(r2), \
            f"state replay not blocked: {r2.status_code} {_detail(r2)}"


# ---------- Telegram miniapp regression ----------
class TestTelegramMiniappRegression:
    TG_ID = 990600601

    @pytest.fixture(scope="class", autouse=True)
    def cleanup(self):
        yield
        try:
            import sys
            sys.path.insert(0, "/app/backend/tests")
            from _iter4_tg_fixtures import cleanup as tg_cleanup
            print("tg cleanup:", tg_cleanup([self.TG_ID]))
        except Exception as e:
            print(f"cleanup skipped: {e}")

    def _init_data(self, tg_id=None):
        import sys
        sys.path.insert(0, "/app/backend/tests")
        from test_tg_miniapp_auth_resilience_iter_current import build_init_data
        return build_init_data(tg_id or self.TG_ID, first_name="Iter6", username="iter6_qa")

    def test_valid_initdata_choice_required(self):
        r = requests.post(f"{API}/auth/telegram/miniapp",
                          json={"init_data": self._init_data()}, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {_detail(r)}"
        data = r.json()
        assert data.get("status") in ("choice_required", "ok"), data
        assert "_id" not in data

    def test_tampered_hash_rejected(self):
        init_data = self._init_data()
        bad = init_data[:-4] + "dead" if not init_data.endswith("dead") else init_data[:-4] + "beef"
        r = requests.post(f"{API}/auth/telegram/miniapp",
                          json={"init_data": bad}, timeout=30)
        assert r.status_code in (400, 401), f"tampered accepted: {r.status_code} {_detail(r)}"

    def test_garbage_initdata_rejected(self):
        r = requests.post(f"{API}/auth/telegram/miniapp",
                          json={"init_data": "garbage=1"}, timeout=30)
        assert r.status_code in (400, 401), f"{r.status_code} {_detail(r)}"
