"""Security hardening regression tests.

1. nz_or() never lets an empty-valued $or clause match a stranger.
2. owner_key() never returns None.
3. startup_security_check() blocks production with weak/missing secrets.

    cd backend && python -m pytest tests/test_security_hardening.py -q
"""
import asyncio
import types

import pytest

from core.helpers import nz_or, owner_key
from security_checks import startup_security_check


def test_nz_or_drops_empty_valued_clauses():
    assert nz_or([{"wallet_address": None}, {"id": "u1"}]) == [{"id": "u1"}]
    assert nz_or([{"email": ""}, {"wallet_address": None}]) == [{"_id": "__no_match__"}]
    # a clause with all-non-empty values is kept
    assert nz_or([{"a": 1, "b": "x"}]) == [{"a": 1, "b": "x"}]


def test_nz_or_never_matches_everyone():
    # the whole point: with only empty identifiers, the query must match nothing
    out = nz_or([{"wallet_address": None}, {"email": None}])
    assert out and all(c == {"_id": "__no_match__"} for c in out)


def test_owner_key_prefers_wallet_then_id_never_none():
    u = types.SimpleNamespace(wallet_address="EQ...abc", id="uid-1")
    assert owner_key(u) == "EQ...abc"
    u2 = types.SimpleNamespace(wallet_address=None, id="uid-2")
    assert owner_key(u2) == "uid-2"
    u3 = types.SimpleNamespace(wallet_address="", id="uid-3")
    assert owner_key(u3) == "uid-3"


def test_empty_wallet_query_would_have_matched_a_stranger():
    """Demonstrates the original bug and that nz_or fixes it, using a fake store."""
    users = [{"id": "me", "wallet_address": None, "email": "me@x.io"},
             {"id": "other", "wallet_address": None, "email": "other@x.io"}]

    def find_one(flt):
        # minimal $or matcher
        conds = flt.get("$or", [flt])
        for u in users:
            for c in conds:
                if all(u.get(k) == v for k, v in c.items()):
                    return u
        return None

    # BEFORE: {"wallet_address": None} matches the first wallet-less user — a stranger
    assert find_one({"wallet_address": None})["id"] == "me" or True  # matches *someone*
    # AFTER: nz_or drops it, so a lookup that only had an empty wallet matches nobody
    assert find_one({"$or": nz_or([{"wallet_address": None}])}) is None
    # a proper id lookup still works
    assert find_one({"$or": nz_or([{"wallet_address": None}, {"id": "other"}])})["id"] == "other"


def test_startup_guard_blocks_production(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(RuntimeError):
        startup_security_check(admin_secret="admin-secret-key-2025", jwt_secret="x" * 40)
    with pytest.raises(RuntimeError):
        startup_security_check(admin_secret="", jwt_secret="x" * 40)
    with pytest.raises(RuntimeError):
        startup_security_check(admin_secret="strong-admin-secret-value-xyz", jwt_secret="short")
    # strong secrets pass
    startup_security_check(admin_secret="strong-admin-secret-value-xyz", jwt_secret="y" * 40)


def test_startup_guard_allows_dev(monkeypatch):
    for k in ("ENV", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.delenv(k, raising=False)
    # outside production weak secrets only warn, never raise
    startup_security_check(admin_secret="admin-secret-key-2025", jwt_secret="x" * 40)


def test_spot_trade_is_disabled_and_moves_no_money():
    """The old /trade/spot let one party debit the other's balance (and moved no resources)."""
    import asyncio, server
    from fastapi import HTTPException

    class U:  # minimal current_user
        id = "attacker"; wallet_address = "EQattacker"

    req = server.TradeResourceRequest(seller_business_id="s", buyer_id="victim", resource_type="energy", amount=10, price_per_unit=1)
    try:
        asyncio.run(server.spot_trade(req, U()))
        raised = None
    except HTTPException as e:
        raised = e.status_code
    assert raised == 410
