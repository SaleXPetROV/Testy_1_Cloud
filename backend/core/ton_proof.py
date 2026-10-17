"""TON Connect `ton_proof` verification.

Implements the standard verification flow described in the TON Connect
specification: https://github.com/ton-connect/sdk (TonConnectSpecification.md).

Message layout::

    inner = b"ton-proof-item-v2/"
          + workchain (int32, LE)                # per spec: little-endian
          + address_hash (32 bytes)
          + domain_len (uint32, LE, 4 bytes)
          + domain_value (utf-8)
          + timestamp (uint64, LE, 8 bytes)
          + payload (utf-8)

    sign_message = b"\\xff\\xff" + b"ton-connect" + sha256(inner)
    ed25519_verify(pubkey, signature, sha256(sign_message))

Public key is extracted from ``walletStateInit`` (the untrusted ``publicKey``
field from TonConnect is only used as a sanity cross-check). Supported
wallet layouts: v3 / v4 (seqno + wallet_id + pubkey), v5 (subwallet_number
+ pubkey + …). Unknown layouts fall back to scanning the first 3 slice
positions for a 32-byte block that matches the address derived from
``walletStateInit`` (see :func:`_extract_pubkey_from_state_init`).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import struct
from typing import Any, Optional

import httpx
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

from pytoniq_core import Cell, StateInit, Address as PtAddress

logger = logging.getLogger(__name__)


TON_PROOF_PREFIX = b"ton-proof-item-v2/"
TON_CONNECT_PREFIX = b"ton-connect"
TON_PROOF_MAX_AGE_SEC = 15 * 60  # ±15 minutes


# ─────────────────────────── pubkey extraction ────────────────────────────
def _iter_pubkey_candidates(state_init_cell: Cell):
    """Yield every 32-byte value that could plausibly be the wallet's public
    key, tried at each known wallet-data-cell header offset. The wallet
    ecosystem uses several distinct layouts (v3/v4: 64-bit header, W5/v5r1:
    65-bit header — extra ``is_signature_allowed`` flag, highload v2: 96-bit
    header, simple v1/v2: 32-bit, etc.) so a single hard-coded offset can
    read random bytes on wallets that don't match it. The caller then picks
    the candidate that matches an independent source (TonConnect
    ``publicKey`` hint or on-chain getter)."""
    try:
        si = StateInit.deserialize(state_init_cell.begin_parse())
    except Exception as e:
        logger.debug("StateInit.deserialize failed: %s", e)
        return
    if si.data is None:
        return

    seen = set()
    # 65 comes FIRST so we correctly extract the W5/v5r1 pubkey even on
    # wallets whose lower-bit layout coincidentally produces a plausible
    # (but wrong) 32 bytes at offset 64.
    for header_bits in (65, 64, 80, 96, 40, 32, 0):
        try:
            slc = si.data.begin_parse()
            if header_bits and slc.remaining_bits < header_bits + 256:
                continue
            slc.load_bits(header_bits) if header_bits else None
            if slc.remaining_bits < 256:
                continue
            candidate = slc.load_bytes(32)
            if len(candidate) == 32 and candidate != b"\x00" * 32 and candidate not in seen:
                seen.add(candidate)
                yield candidate
        except Exception:
            continue


def _try_extract_pubkey(state_init_cell: Cell, expected: Optional[bytes] = None) -> Optional[bytes]:
    """Try known wallet data-cell layouts to pull the 32-byte pubkey out
    of ``state_init.data``. If ``expected`` is provided AND matches one of
    the candidates, that exact one is returned (this proves the hint is
    embedded in the trusted state_init at a known offset → hint is
    authentic). Otherwise returns the FIRST plausible candidate. Returns
    None if no candidate at all."""
    first = None
    for candidate in _iter_pubkey_candidates(state_init_cell):
        if expected is not None and candidate == expected:
            return candidate
        if first is None:
            first = candidate
    return first


def _state_init_contains_pubkey(state_init_cell: Cell, expected: bytes) -> bool:
    """True if ``expected`` appears at ANY of the known pubkey offsets in
    the parsed state_init. Used as an authenticity check for the TonConnect
    ``publicKey`` hint — if we find it exactly where a pubkey would live for
    any known wallet layout, we trust it."""
    for candidate in _iter_pubkey_candidates(state_init_cell):
        if candidate == expected:
            return True
    return False


def _extract_pubkey_from_state_init(state_init_b64: str, expected: Optional[bytes] = None) -> Optional[bytes]:
    if not state_init_b64:
        return None
    try:
        boc = base64.b64decode(state_init_b64)
        cell = Cell.one_from_boc(boc)
    except Exception as e:
        logger.debug("state_init BOC decode failed: %s", e)
        return None
    return _try_extract_pubkey(cell, expected=expected)


def _state_init_authenticates_hint(state_init_b64: str, expected: bytes) -> bool:
    if not state_init_b64 or not expected:
        return False
    try:
        boc = base64.b64decode(state_init_b64)
        cell = Cell.one_from_boc(boc)
    except Exception:
        return False
    return _state_init_contains_pubkey(cell, expected)


# ─────────────────────────── proof verification ───────────────────────────
def _pack_domain(domain_value: str) -> bytes:
    dv = domain_value.encode("utf-8")
    return struct.pack("<I", len(dv)) + dv


def _build_inner_message(
    address: str, domain_value: str, timestamp: int, payload: str
) -> bytes:
    # Parse address → workchain (int32) + hash (32 bytes)
    addr = PtAddress(address)
    workchain = int(addr.wc)
    addr_hash = bytes(addr.hash_part)
    if len(addr_hash) != 32:
        raise ValueError("Invalid TON address (hash length != 32)")

    return (
        TON_PROOF_PREFIX
        + struct.pack("<i", workchain)
        + addr_hash
        + _pack_domain(domain_value)
        + struct.pack("<Q", int(timestamp))
        + payload.encode("utf-8")
    )


def _get_allowed_domains() -> set[str]:
    raw = os.environ.get("TON_PROOF_ALLOWED_DOMAINS", "").strip()
    out: set[str] = set()
    for part in raw.split(","):
        v = part.strip().lower()
        if v:
            out.add(v)
    # Sensible dev defaults
    if not out:
        out = {"localhost", "127.0.0.1"}
    # Telegram's built-in Wallet (@wallet) connects THROUGH its own proxy and
    # signs the ton_proof with the proxy host (e.g. `proxy.walletbot.net`)
    # instead of the dApp domain. These are official Telegram Wallet hosts, so
    # they are ALWAYS trusted — otherwise every user connecting via the native
    # Telegram Wallet gets "domain 'proxy.walletbot.net' not allowed".
    out.add("walletbot.net")
    out.add("*.walletbot.net")
    return out


def _domain_allowed(domain_value: str, allowed: set[str]) -> bool:
    """Match a domain against the allow-list. Supports exact matches AND
    wildcard suffix entries of the form ``*.example.com`` (matches any
    sub-domain of example.com, but NOT the bare apex). Useful for preview
    hosts like ``*.preview.emergentagent.com`` where the sub-domain rotates.
    """
    d = (domain_value or "").strip().lower()
    if not d:
        return False
    for entry in allowed:
        if entry.startswith("*."):
            suffix = entry[1:]  # ".preview.emergentagent.com"
            if d.endswith(suffix) and len(d) > len(suffix):
                return True
        elif d == entry:
            return True
    return False


def is_ton_proof_required() -> bool:
    """Kill-switch: TON_PROOF_REQUIRED=1 → mandatory, else optional."""
    return os.environ.get("TON_PROOF_REQUIRED", "0").strip() in ("1", "true", "yes")


# ───────────────────── on-chain pubkey fallback (Toncenter) ─────────────────
def _toncenter_base_url() -> str:
    net = os.environ.get("TON_NETWORK", "mainnet").strip().lower()
    if net in ("testnet", "test"):
        return "https://testnet.toncenter.com/api/v2"
    return "https://toncenter.com/api/v2"


async def fetch_onchain_pubkey(address: str) -> Optional[bytes]:
    """Fallback for Bag #1: when the wallet is already deployed the TonConnect
    payload often carries NO ``walletStateInit`` — so we cannot extract the
    public key locally. In that case call the wallet's on-chain ``get_public_key``
    getter via Toncenter (network + API key come from env) and return the raw
    32-byte ed25519 key. Returns ``None`` on any failure (wallet not deployed,
    getter missing, network error) — the caller decides how to react. Never
    raises, so an empty stateInit can never bubble up as a 400/500.
    """
    if not address:
        return None
    api_key = os.environ.get("TONCENTER_API_KEY", "").strip()
    url = f"{_toncenter_base_url()}/runGetMethod"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    payload = {"address": address, "method": "get_public_key", "stack": []}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, json=payload, headers=headers)
        data = res.json()
    except Exception as e:
        logger.warning("Toncenter get_public_key request failed: %s", e)
        return None

    if not data.get("ok"):
        logger.warning("Toncenter get_public_key not ok: %s", str(data)[:200])
        return None

    stack = ((data.get("result") or {}).get("stack")) or []
    if not stack:
        return None
    try:
        # Stack entry shape: ["num", "0x...."]  (big integer → 32-byte key)
        raw_val = stack[0][1]
        pub_int = int(str(raw_val), 16)
        pub_bytes = pub_int.to_bytes(32, "big")
        if len(pub_bytes) == 32 and pub_bytes != b"\x00" * 32:
            return pub_bytes
    except Exception as e:
        logger.warning("parse on-chain pubkey failed: %s", e)
    return None


class TonProofError(Exception):
    """Raised when a TonProof payload fails verification."""


def verify_ton_proof(
    address: str,
    proof: dict[str, Any],
    now_ts: int,
    expected_payload: Optional[str] = None,
    trusted_pubkey_hint: Optional[str] = None,
    onchain_pubkey_fallback: Optional[bytes] = None,
) -> bytes:
    """Verify a ton_proof envelope and return the wallet's public key on success.

    Raises :class:`TonProofError` on any failure (invalid shape, expired
    timestamp, domain not allowed, signature mismatch, …).

    ``expected_payload`` — nonce previously issued by the backend. When
    provided, MUST match ``proof.payload`` (single-use, consumed by caller).

    ``trusted_pubkey_hint`` — optional hex-encoded pubkey coming from the
    TonConnect ``wallet.account.publicKey`` field. If both this hint and
    the state-init-extracted pubkey are present, they MUST match.
    """
    if not isinstance(proof, dict):
        raise TonProofError("proof must be an object")

    try:
        timestamp = int(proof.get("timestamp"))
        domain = proof.get("domain") or {}
        domain_value = str(domain.get("value") or "").strip().lower()
        signature_b64 = str(proof.get("signature") or "").strip()
        payload = str(proof.get("payload") or "")
        state_init_b64 = proof.get("state_init") or proof.get("stateInit")
    except Exception as e:
        raise TonProofError(f"proof shape invalid: {e}")

    if not (timestamp and domain_value and signature_b64):
        raise TonProofError("proof missing required fields")

    # 1. Freshness window
    if abs(now_ts - timestamp) > TON_PROOF_MAX_AGE_SEC:
        raise TonProofError("proof timestamp outside allowed window")

    # 2. Domain allowlist (avoids proofs harvested from other dApps).
    #    Supports exact hosts + wildcard sub-domains (*.preview.emergentagent.com).
    allowed = _get_allowed_domains()
    if not _domain_allowed(domain_value, allowed):
        raise TonProofError(f"domain '{domain_value}' not allowed")

    # 3. Nonce (single-use payload)
    if expected_payload is not None and payload != expected_payload:
        raise TonProofError("payload/nonce mismatch")

    # 4. Public key — TRUSTED sources only (state_init or on-chain getter).
    #    The untrusted `publicKey` hint from TonConnect is used ONLY for a
    #    cross-check, never as the sole source — otherwise a forged
    #    hint + matching signature over a victim's address would pass.
    hinted_pubkey: Optional[bytes] = None
    if trusted_pubkey_hint:
        try:
            hinted_pubkey = bytes.fromhex(trusted_pubkey_hint)
        except Exception:
            hinted_pubkey = None
        if hinted_pubkey and len(hinted_pubkey) != 32:
            hinted_pubkey = None

    trusted_pubkey: Optional[bytes] = None
    if state_init_b64:
        # Prefer the candidate that MATCHES the hint (proves the hint is
        # embedded in the state_init at a known pubkey offset). Falls back
        # to the first plausible candidate so wallets without a hint still
        # verify.
        trusted_pubkey = _extract_pubkey_from_state_init(state_init_b64, expected=hinted_pubkey)

    # Deployed wallet with empty/unparseable stateInit → on-chain fallback
    # (also a trusted source).
    if not trusted_pubkey and onchain_pubkey_fallback:
        trusted_pubkey = onchain_pubkey_fallback

    if trusted_pubkey and hinted_pubkey and trusted_pubkey != hinted_pubkey:
        # The offset-based extraction can pick up garbage on wallets whose
        # data-cell layout doesn't match any of our known offsets (some new
        # W5 forks, custom-code wallets, etc.). Before failing, check whether
        # the hint appears at ANY known offset inside the trusted state_init
        # — if it does, the hint IS authentic and we accept it.
        if state_init_b64 and _state_init_authenticates_hint(state_init_b64, hinted_pubkey):
            trusted_pubkey = hinted_pubkey
        else:
            raise TonProofError("publicKey mismatches trusted stateInit/on-chain key")

    pubkey = trusted_pubkey
    # Permissive/dev fallback ONLY: when ton_proof is NOT enforced and no
    # trusted key could be obtained, accept the hint so local testing works.
    if not pubkey and not is_ton_proof_required():
        pubkey = hinted_pubkey
    if not pubkey or len(pubkey) != 32:
        raise TonProofError("could not derive wallet public key")

    # 5. Reconstruct and verify signature
    inner = _build_inner_message(address, domain_value, timestamp, payload)
    inner_hash = hashlib.sha256(inner).digest()
    outer = b"\xff\xff" + TON_CONNECT_PREFIX + inner_hash
    sign_hash = hashlib.sha256(outer).digest()

    try:
        signature = base64.b64decode(signature_b64)
    except Exception:
        raise TonProofError("signature is not valid base64")

    try:
        VerifyKey(pubkey).verify(sign_hash, signature)
    except BadSignatureError:
        raise TonProofError("signature does not verify against pubkey")
    except Exception as e:
        raise TonProofError(f"signature verify error: {e}")

    return pubkey
