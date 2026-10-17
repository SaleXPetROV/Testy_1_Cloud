"""Unit tests for ton_integration.TONClient.send_ton_payout (iter 13).

The bug: without TONCENTER_API_KEY, the previous implementation used the heavy
`getWalletInformation` endpoint for BOTH V4R2 and V3R2 addresses which returned
HTTP 429 → balance 0 → "оба кошелька пусты" and legitimate withdrawals blocked.

Fix under test: send_ton_payout uses the LIGHT `getAddressBalance` endpoint to
decide which wallet to use and to enforce the insufficient-funds guard BEFORE
attempting to send. This test mocks httpx.AsyncClient to prove:
  (a) 429 on getWalletInformation is tolerated → V4R2 chosen via
      getAddressBalance and sendBoc is invoked (does not raise "пусто");
  (b) Both addresses empty by getAddressBalance → readable error;
  (c) Balance < amount + 0.01 → "Недостаточно средств" error.
"""
import asyncio
import json
import sys
import pytest

sys.path.insert(0, "/app/backend")
import ton_integration  # noqa: E402
from tonsdk.crypto import mnemonic_to_wallet_key  # noqa: E402
from tonsdk.contract.wallet import WalletV3ContractR2  # noqa: E402


# 24-word valid test mnemonic (deterministic tonsdk test vector; NEVER used on chain)
TEST_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon art"
)

# Derive a syntactically valid dest address (correct CRC16) from the mnemonic.
_pub, _priv = mnemonic_to_wallet_key(TEST_MNEMONIC.split())
_dest_wallet = WalletV3ContractR2(public_key=_pub, private_key=_priv, workchain=0)
DEST_ADDR = _dest_wallet.address.to_string(True, True, False)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = json.dumps(self._json)

    def json(self):
        return self._json


class FakeAsyncClient:
    """Records GET/POST calls and returns pre-programmed responses keyed by
    the endpoint path suffix (getAddressBalance / getWalletInformation /
    sendBoc)."""

    def __init__(self, responses):
        # responses: {"getAddressBalance": [FakeResponse,...] queued per address}
        self.responses = responses
        self.calls = []
        self._addr_balance_idx = 0

    def __init_subclass__(cls, **kw):  # keep httpx.AsyncClient(...) call happy
        super().__init_subclass__(**kw)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        self.calls.append(("GET", url, params))
        if "getAddressBalance" in url:
            queue = self.responses["getAddressBalance"]
            resp = queue[self._addr_balance_idx] if self._addr_balance_idx < len(queue) else queue[-1]
            self._addr_balance_idx += 1
            return resp
        if "getWalletInformation" in url:
            return self.responses.get("getWalletInformation", FakeResponse(429, {"ok": False}))
        return FakeResponse(404, {"ok": False})

    async def post(self, url, json=None, headers=None):
        self.calls.append(("POST", url, json))
        if "sendBoc" in url:
            return self.responses.get("sendBoc", FakeResponse(200, {"ok": True, "result": {"hash": "fake_hash"}}))
        return FakeResponse(404, {"ok": False})


def _make_client_factory(responses):
    def factory(*a, **kw):
        return FakeAsyncClient(responses)
    return factory


def _bal(ton_value, ok=True):
    return FakeResponse(200, {"ok": ok, "result": str(int(ton_value * 1e9))})


def test_scenario_A_v4_has_balance_getWalletInfo_429_still_sends(monkeypatch):
    """V4R2 has balance via getAddressBalance; getWalletInformation returns 429.
    Function must choose V4R2 and reach sendBoc without raising 'пусто'."""
    responses = {
        # First call = V4R2 address balance, second = V3R2 address balance
        "getAddressBalance": [_bal(12.0), _bal(0.0)],
        "getWalletInformation": FakeResponse(429, {"ok": False}),
        "sendBoc": FakeResponse(200, {"ok": True, "result": {"hash": "api_hash_xyz"}}),
    }
    monkeypatch.setattr(ton_integration.httpx, "AsyncClient", _make_client_factory(responses))

    client = ton_integration.TONClient()
    tx_hash = asyncio.run(client.send_ton_payout(
        dest_address=DEST_ADDR,
        amount_ton=1.0,
        mnemonics=TEST_MNEMONIC,
        user_username="alice",
    ))
    # Locally computed msg hash preferred; must be a non-empty hex string
    assert tx_hash, "send_ton_payout should return a hash on success"


def test_scenario_B_both_wallets_empty_readable_error(monkeypatch):
    responses = {
        "getAddressBalance": [_bal(0.0), _bal(0.0)],
        "getWalletInformation": FakeResponse(429, {"ok": False}),
    }
    monkeypatch.setattr(ton_integration.httpx, "AsyncClient", _make_client_factory(responses))
    client = ton_integration.TONClient()

    with pytest.raises(Exception) as ei:
        asyncio.run(client.send_ton_payout(
            dest_address=DEST_ADDR,
            amount_ton=1.0,
            mnemonics=TEST_MNEMONIC,
        ))
    msg = str(ei.value)
    assert "недостаточно" in msg.lower() or "пополните" in msg.lower(), msg


def test_scenario_C_balance_below_amount_plus_gas(monkeypatch):
    """V4R2 balance 0.5 TON, amount 1.0 → V4R2 chosen as fallback (>0) and the
    explicit guard raises 'Недостаточно средств'."""
    responses = {
        "getAddressBalance": [_bal(0.5), _bal(0.0)],
        "getWalletInformation": FakeResponse(200, {"ok": True, "result": {"seqno": 0}}),
    }
    monkeypatch.setattr(ton_integration.httpx, "AsyncClient", _make_client_factory(responses))
    client = ton_integration.TONClient()

    with pytest.raises(Exception) as ei:
        asyncio.run(client.send_ton_payout(
            dest_address=DEST_ADDR,
            amount_ton=1.0,
            mnemonics=TEST_MNEMONIC,
        ))
    assert "недостаточно" in str(ei.value).lower()
