"""Sending NFTs of the reward warehouse from the project wallet (TON).

    tradable  — an NFT minted beforehand (e.g. on GetGems) onto the project wallet: a TEP-62 `transfer`
                message to the NFT item, new owner = the player's wallet.
    sbt       — a soulbound copy (TEP-85) minted straight onto the player's wallet: a `deploy item`
                message (op 1) to the SBT collection, the way GetGems SBT collections expect it:
                index, amount, content ref = owner address + individual content + authority address.

Settings (admin «NFT» tab → admin_settings type=minigame_nft): network testnet | mainnet.
The project wallet is the withdrawal wallet set in the admin («Контракт», encrypted in the database);
TON_WALLET_MNEMONIC in backend/.env is only the fallback. Keys in backend/.env:
    TONCENTER_API_KEY            mainnet key;  TONCENTER_TESTNET_API_KEY  testnet key
    NFT_META_BASE_URL            public base of /api/nft-meta/ (SBT metadata served by this server)

Every send is checked on chain afterwards (owner of the item == the player) before it counts as delivered.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

TRANSFER_TON = 0.05          # attached to a transfer (the excess comes back to the project wallet)
MINT_TON = 0.06              # attached to an SBT mint (pays the new item's storage)
ITEM_KEEP_TON = 0.03         # what the new SBT item keeps


def endpoints(network: str) -> Tuple[str, str, str]:
    """(v2 url, v3 url, api key) for the chosen network."""
    if network == "mainnet":
        v2 = os.environ.get("TONCENTER_API_ENDPOINT", "https://toncenter.com/api/v2").rstrip("/")
        for suf in ("/jsonRPC", "/jsonrpc"):
            if v2.endswith(suf):
                v2 = v2[: -len(suf)]
        return v2, "https://toncenter.com/api/v3", os.environ.get("TONCENTER_API_KEY", "")
    return "https://testnet.toncenter.com/api/v2", "https://testnet.toncenter.com/api/v3", os.environ.get("TONCENTER_TESTNET_API_KEY", "")


_WORDS: List[str] = []


async def load_mnemonic(db) -> bool:
    """The project wallet = the SAME wallet the admin set for withdrawals (admin → «Контракт»: withdrawal_wallet,
    then sender_wallet, stored encrypted), then TON_WALLET_MNEMONIC from backend/.env. Called before every use."""
    global _WORDS
    seed = None
    try:
        from mnemonic_crypto import decrypt_mnemonic
        for kind in ("withdrawal_wallet", "sender_wallet"):
            doc = await db.admin_settings.find_one({"type": kind}, {"_id": 0, "mnemonic": 1})
            seed = decrypt_mnemonic(doc.get("mnemonic")) if doc and doc.get("mnemonic") else None
            if seed:
                break
    except Exception:
        seed = None
    seed = seed or os.environ.get("TON_WALLET_MNEMONIC") or ""
    _WORDS = str(seed).split()
    return len(_WORDS) == 24


def _mnemonic() -> List[str]:
    if len(_WORDS) != 24:
        raise RuntimeError("Кошелёк проекта не задан: укажите фразу из 24 слов в админке → «Контракт» (кошелёк для выплат)")
    return _WORDS


def project_wallet(network: str = "testnet"):
    from tonsdk.contract.wallet import WalletV4ContractR2
    from tonsdk.crypto import mnemonic_to_wallet_key
    pub, priv = mnemonic_to_wallet_key(_mnemonic())
    w = WalletV4ContractR2(public_key=pub, private_key=priv, workchain=0)
    return w, w.address.to_string(True, True, False, network != "mainnet")


def raw(addr: str) -> str:
    """Canonical raw form 0:<hex> for comparing addresses."""
    try:
        from pytoniq_core import Address
        return Address(addr).to_str(is_user_friendly=False).lower()
    except Exception:
        return str(addr or "").lower()


async def _get(client: httpx.AsyncClient, url: str, params: Dict, key: str) -> Dict:
    for i in range(4):
        r = await client.get(url, params=params, headers={"X-API-Key": key} if key else {})
        if r.status_code == 429:
            await asyncio.sleep(1 + i)
            continue
        return r.json()
    return {}


async def wallet_state(network: str) -> Dict[str, Any]:
    _w, addr = project_wallet(network)
    v2, _v3, key = endpoints(network)
    async with httpx.AsyncClient(timeout=15) as c:
        info = await _get(c, f"{v2}/getWalletInformation", {"address": addr}, key)
    res = info.get("result") or {}
    return {"address": addr, "balance_ton": int(res.get("balance") or 0) / 1e9, "seqno": int(res.get("seqno") or 0),
            "state": res.get("account_state") or res.get("wallet_type")}


def _transfer_body(new_owner: str, response_to: str):
    from tonsdk.boc import Cell
    from tonsdk.utils import Address
    b = Cell()
    b.bits.write_uint(0x5FCC3D14, 32)          # op::transfer (TEP-62)
    b.bits.write_uint(0, 64)                   # query_id
    b.bits.write_address(Address(new_owner))   # new_owner
    b.bits.write_address(Address(response_to)) # response_destination (excess back to the project wallet)
    b.bits.write_bit(0)                        # no custom_payload
    b.bits.write_coins(1)                      # forward_amount: 1 nanoton -> the new owner gets ownership_assigned
    b.bits.write_bit(0)                        # forward_payload in place (empty)
    return b


def _snake(text: str):
    from tonsdk.boc import Cell
    data = text.encode()
    root = Cell()
    cur, first = root, True
    while data:
        cap = 127 if first else 127
        chunk, data = data[:cap], data[cap:]
        cur.bits.write_bytes(chunk)
        if data:
            nxt = Cell(); cur.refs.append(nxt); cur = nxt
        first = False
    return root


def _sbt_mint_body(index: int, owner: str, content: str, authority: str):
    from tonsdk.boc import Cell
    from tonsdk.utils import Address, to_nano
    item = Cell()
    item.bits.write_address(Address(owner))
    item.refs.append(_snake(content))          # individual content (suffix of the collection's common content)
    item.bits.write_address(Address(authority))
    b = Cell()
    b.bits.write_uint(1, 32)                   # op::deploy_new_nft
    b.bits.write_uint(0, 64)                   # query_id
    b.bits.write_uint(int(index), 64)          # item index
    b.bits.write_coins(to_nano(ITEM_KEEP_TON, "ton"))
    b.refs.append(item)
    return b


async def _send(network: str, to_addr: str, amount_ton: float, body) -> str:
    """Sign and send one internal message from the project wallet. Waits until the seqno moves (so the next
    send never reuses it). Returns the hash of the external message (tonviewer accepts it)."""
    from tonsdk.utils import bytes_to_b64str, to_nano
    w, addr = project_wallet(network)
    v2, _v3, key = endpoints(network)
    async with httpx.AsyncClient(timeout=20) as c:
        info = await _get(c, f"{v2}/getWalletInformation", {"address": addr}, key)
        seqno = int((info.get("result") or {}).get("seqno") or 0)
        q = w.create_transfer_message(to_addr=to_addr, amount=to_nano(amount_ton, "ton"), seqno=seqno, payload=body)
        msg = q["message"]
        h = msg.bytes_hash().hex()
        r = await c.post(f"{v2}/sendBoc", json={"boc": bytes_to_b64str(msg.to_boc(False))},
                         headers={"X-API-Key": key} if key else {})
        j = r.json() if r.content else {}
        if r.status_code != 200 or not j.get("ok"):
            raise RuntimeError(f"sendBoc: {j.get('error') or r.status_code}")
        for _ in range(30):                     # wait for the seqno to move (≈ one block)
            await asyncio.sleep(2)
            info2 = await _get(c, f"{v2}/getWalletInformation", {"address": addr}, key)
            if int((info2.get("result") or {}).get("seqno") or 0) > seqno:
                break
    return h


async def transfer_nft(network: str, item_address: str, new_owner: str) -> str:
    _w, addr = project_wallet(network)
    return await _send(network, item_address, TRANSFER_TON, _transfer_body(new_owner, addr))


async def mint_sbt(network: str, collection: str, index: int, owner: str, content: str) -> str:
    _w, addr = project_wallet(network)
    return await _send(network, collection, MINT_TON, _sbt_mint_body(index, owner, content, addr))


async def item_owner(network: str, item_address: str) -> Optional[str]:
    _v2, v3, key = endpoints(network)
    async with httpx.AsyncClient(timeout=15) as c:
        j = await _get(c, f"{v3}/nft/items", {"address": item_address, "limit": 1}, key)
    items = j.get("nft_items") or []
    return items[0].get("owner_address") if items else None


async def sbt_item(network: str, collection: str, index: int) -> Optional[Dict]:
    _v2, v3, key = endpoints(network)
    async with httpx.AsyncClient(timeout=15) as c:
        j = await _get(c, f"{v3}/nft/items", {"collection_address": collection, "index": int(index), "limit": 1}, key)
    items = j.get("nft_items") or []
    return items[0] if items else None


async def collection_items_on_wallet(network: str, collection: str) -> List[Dict]:
    """NFTs of a collection that sit on the project wallet: address, index, name, image (from the indexer's metadata)."""
    _w, addr = project_wallet(network)
    _v2, v3, key = endpoints(network)
    out, offset = [], 0
    async with httpx.AsyncClient(timeout=20) as c:
        while True:
            j = await _get(c, f"{v3}/nft/items", {"collection_address": collection, "owner_address": addr,
                                                  "limit": 100, "offset": offset}, key)
            items = j.get("nft_items") or []
            meta = j.get("metadata") or {}
            for it in items:
                m = (meta.get(it.get("address")) or {}).get("token_info") or [{}]
                m = m[0] if m else {}
                out.append({"nft_address": it.get("address"), "index": it.get("index"),
                            "name": m.get("name"), "image_url": m.get("image"), "description": m.get("description")})
            if len(items) < 100:
                break
            offset += 100
    return out


async def single_item(network: str, item_address: str) -> Optional[Dict]:
    _v2, v3, key = endpoints(network)
    async with httpx.AsyncClient(timeout=15) as c:
        j = await _get(c, f"{v3}/nft/items", {"address": item_address, "limit": 1}, key)
    items = j.get("nft_items") or []
    if not items:
        return None
    it = items[0]
    m = ((j.get("metadata") or {}).get(it.get("address")) or {}).get("token_info") or [{}]
    m = m[0] if m else {}
    return {"nft_address": it.get("address"), "index": it.get("index"), "owner": it.get("owner_address"),
            "collection": (it.get("collection") or {}).get("address") or it.get("collection_address"),
            "name": m.get("name"), "image_url": m.get("image"), "description": m.get("description")}
