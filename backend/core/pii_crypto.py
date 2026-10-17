"""Field-level encryption of personal data, transparent for the rest of the code.

Every personal field (e-mail, wallets, Telegram chat id, IP, user agent, device id…) is
stored ENCRYPTED with AES-256-GCM ("enc1:<type><base64(nonce+ciphertext)>"). Fields the
game must search by also get a blind index "<field>_bidx" = HMAC-SHA256(index key, value):
equality lookups work, the value can't be recovered from it.

`wrap_database(db)` returns a proxy of the Motor database: on every collection
  • writes  (insert / update $set / $setOnInsert / replace / bulk_write) encrypt the fields,
  • queries ({"email": x}, $in, $nin, $ne, $or/$and, $regex→exact) are rewritten to the index,
  • reads   (find / find_one / aggregate / distinct …) decrypt "enc1:" values (nested too).
Without both keys the proxy is NOT installed (plain mode, e.g. local development).

Keys (base64 of 32 random bytes each) come only from the environment:
    PII_ENC_KEY    — AES-256-GCM key
    PII_INDEX_KEY  — HMAC key of the blind indexes
Generate: python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
Losing PII_ENC_KEY means the encrypted fields can't be read any more — keep a copy offline.
"""
import base64
import hashlib
import hmac
import logging
import os
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PREFIX = "enc1:"
# collection -> {field: (is_lookup, normalizer)}
_lower = lambda v: str(v).strip().lower()   # noqa: E731
_exact = lambda v: str(v).strip()           # noqa: E731
SPEC: Dict[str, Dict[str, tuple]] = {
    "users": {
        "email": (True, _lower), "wallet_address": (True, _exact), "raw_address": (True, _exact),
        "telegram_chat_id": (True, _exact), "last_ip": (False, _exact),
        "last_user_agent": (False, _exact), "last_device": (False, _exact),
    },
    "fingerprints": {
        "email": (True, _lower), "ip": (True, _exact), "visitor_id": (True, _exact), "user_agent": (False, _exact),
    },
    "transactions": {"user_wallet": (True, _exact)},
}


class PIICipher:
    def __init__(self, enc_key: bytes, idx_key: bytes):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if len(enc_key) != 32 or len(idx_key) != 32:
            raise ValueError("PII keys must be 32 bytes")
        self._aes = AESGCM(enc_key)
        self._idx = idx_key

    def enc(self, v: Any) -> Any:
        if v is None or (isinstance(v, str) and (v == "" or v.startswith(PREFIX))):
            return v
        kind, raw = ("i", str(v)) if isinstance(v, int) and not isinstance(v, bool) else ("s", str(v))
        nonce = os.urandom(12)
        return PREFIX + kind + base64.b64encode(nonce + self._aes.encrypt(nonce, raw.encode(), None)).decode()

    def dec(self, v: Any) -> Any:
        if not (isinstance(v, str) and v.startswith(PREFIX)):
            return v
        try:
            blob = base64.b64decode(v[len(PREFIX) + 1:])
            raw = self._aes.decrypt(blob[:12], blob[12:], None).decode()
            return int(raw) if v[len(PREFIX)] == "i" else raw
        except Exception:
            logger.error("PII: cannot decrypt a value (wrong PII_ENC_KEY?)")
            return None

    def bidx(self, v: Any, norm=_exact) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str) and v.startswith(PREFIX):
            v = self.dec(v)
        return hmac.new(self._idx, norm(v).encode(), hashlib.sha256).hexdigest()[:40]


def cipher_from_env() -> Optional[PIICipher]:
    a, b = os.environ.get("PII_ENC_KEY", ""), os.environ.get("PII_INDEX_KEY", "")
    if not a or not b:
        return None
    return PIICipher(base64.b64decode(a), base64.b64decode(b))


# ───────────────────────── rewriting ─────────────────────────
def _unregex(pat: str) -> str:
    """'^alice@x\\.com$' -> 'alice@x.com' (a search on an encrypted field becomes an exact match)."""
    p = pat[1:] if pat.startswith("^") else pat
    p = p[:-1] if p.endswith("$") else p
    return re.sub(r"\\(.)", r"\1", p)


def rewrite_filter(c: PIICipher, spec: Dict[str, tuple], flt: Any) -> Any:
    if not isinstance(flt, dict):
        return flt
    out: Dict[str, Any] = {}
    for k, v in flt.items():
        if k in ("$or", "$and", "$nor") and isinstance(v, list):
            out[k] = [rewrite_filter(c, spec, x) for x in v]
            continue
        if k not in spec or not spec[k][0]:
            out[k] = v
            continue
        norm, ik = spec[k][1], f"{k}_bidx"
        if isinstance(v, dict) and any(str(x).startswith("$") for x in v):
            cond: Dict[str, Any] = {}
            for op, arg in v.items():
                if op in ("$in", "$nin"):
                    cond[op] = [c.bidx(x, norm) for x in (arg or [])]
                elif op in ("$eq", "$ne"):
                    cond[op] = c.bidx(arg, norm)
                elif op == "$exists":
                    cond[op] = arg
                elif op == "$regex":
                    cond["$eq"] = c.bidx(_unregex(str(arg)), norm)
                elif op == "$options":
                    continue
                else:
                    logger.warning(f"PII: operator {op} on encrypted field {k} is not supported")
            out[ik] = cond
        else:
            out[ik] = c.bidx(v, norm)
    return out


def encrypt_doc(c: PIICipher, spec: Dict[str, tuple], doc: Any) -> Any:
    if not isinstance(doc, dict):
        return doc
    d = dict(doc)
    for f, (lookup, norm) in spec.items():
        if f in d:
            v = d[f]
            if lookup:
                d[f"{f}_bidx"] = c.bidx(v, norm) if v not in (None, "") else (None if v is None else c.bidx("", norm))
            d[f] = c.enc(v)
    return d


def rewrite_update(c: PIICipher, spec: Dict[str, tuple], upd: Any) -> Any:
    if not isinstance(upd, dict):
        return upd                                     # aggregation-pipeline updates: passed through
    if not any(str(k).startswith("$") for k in upd):
        return encrypt_doc(c, spec, upd)               # replacement document
    out = dict(upd)
    for op in ("$set", "$setOnInsert"):
        if isinstance(out.get(op), dict):
            out[op] = encrypt_doc(c, spec, out[op])
    if isinstance(out.get("$unset"), dict):
        u = dict(out["$unset"])
        for f, (lookup, _n) in spec.items():
            if f in u and lookup:
                u[f"{f}_bidx"] = ""
        out["$unset"] = u
    return out


def decrypt_any(c: PIICipher, v: Any) -> Any:
    if isinstance(v, str):
        return c.dec(v) if v.startswith(PREFIX) else v
    if isinstance(v, dict):
        return {k: decrypt_any(c, x) for k, x in v.items()}
    if isinstance(v, list):
        return [decrypt_any(c, x) for x in v]
    return v


# ───────────────────────── proxies ─────────────────────────
class _Cursor:
    def __init__(self, cur, c): self._cur, self._c = cur, c
    def __getattr__(self, n):
        a = getattr(self._cur, n)
        if callable(a) and n in ("sort", "skip", "limit", "batch_size", "max_time_ms", "hint", "collation", "allow_disk_use"):
            def chain(*x, **k):
                a(*x, **k); return self
            return chain
        return a
    async def to_list(self, length=None):
        return [decrypt_any(self._c, d) for d in await self._cur.to_list(length)]
    def __aiter__(self):
        return self
    async def __anext__(self):
        return decrypt_any(self._c, await self._cur.__anext__())


class EncryptedCollection:
    def __init__(self, coll, c: PIICipher, spec: Dict[str, tuple]):
        self._coll, self._c, self._spec = coll, c, spec
    def __getattr__(self, n):
        return getattr(self._coll, n)
    def _f(self, flt): return rewrite_filter(self._c, self._spec, flt) if flt else flt
    def find(self, filter=None, *a, **k):
        return _Cursor(self._coll.find(self._f(filter or {}), *a, **k), self._c)
    async def find_one(self, filter=None, *a, **k):
        return decrypt_any(self._c, await self._coll.find_one(self._f(filter or {}), *a, **k))
    async def find_one_and_update(self, filter, update, *a, **k):
        return decrypt_any(self._c, await self._coll.find_one_and_update(self._f(filter), rewrite_update(self._c, self._spec, update), *a, **k))
    async def find_one_and_replace(self, filter, doc, *a, **k):
        return decrypt_any(self._c, await self._coll.find_one_and_replace(self._f(filter), encrypt_doc(self._c, self._spec, doc), *a, **k))
    async def find_one_and_delete(self, filter, *a, **k):
        return decrypt_any(self._c, await self._coll.find_one_and_delete(self._f(filter), *a, **k))
    async def insert_one(self, doc, *a, **k):
        enc = encrypt_doc(self._c, self._spec, doc)
        r = await self._coll.insert_one(enc, *a, **k)
        if isinstance(doc, dict) and "_id" in enc:
            doc["_id"] = enc["_id"]                     # pymongo sets _id on the passed dict
        return r
    async def insert_many(self, docs, *a, **k):
        return await self._coll.insert_many([encrypt_doc(self._c, self._spec, d) for d in docs], *a, **k)
    async def update_one(self, filter, update, *a, **k):
        return await self._coll.update_one(self._f(filter), rewrite_update(self._c, self._spec, update), *a, **k)
    async def update_many(self, filter, update, *a, **k):
        return await self._coll.update_many(self._f(filter), rewrite_update(self._c, self._spec, update), *a, **k)
    async def replace_one(self, filter, doc, *a, **k):
        return await self._coll.replace_one(self._f(filter), encrypt_doc(self._c, self._spec, doc), *a, **k)
    async def delete_one(self, filter, *a, **k):
        return await self._coll.delete_one(self._f(filter), *a, **k)
    async def delete_many(self, filter, *a, **k):
        return await self._coll.delete_many(self._f(filter), *a, **k)
    async def count_documents(self, filter, *a, **k):
        return await self._coll.count_documents(self._f(filter), *a, **k)
    async def distinct(self, key, filter=None, *a, **k):
        vals = await self._coll.distinct(key, self._f(filter) if filter else filter, *a, **k)
        return [decrypt_any(self._c, v) for v in vals]
    def aggregate(self, pipeline, *a, **k):
        p = [({"$match": self._f(st["$match"])} if isinstance(st, dict) and "$match" in st else st) for st in (pipeline or [])]
        return _Cursor(self._coll.aggregate(p, *a, **k), self._c)
    async def bulk_write(self, requests, *a, **k):
        from pymongo import UpdateOne, UpdateMany, InsertOne, ReplaceOne, DeleteOne, DeleteMany
        out = []
        for r in requests:
            f = getattr(r, "_filter", None); d = getattr(r, "_doc", None); ups = getattr(r, "_upsert", False)
            if isinstance(r, UpdateOne): out.append(UpdateOne(self._f(f), rewrite_update(self._c, self._spec, d), upsert=ups))
            elif isinstance(r, UpdateMany): out.append(UpdateMany(self._f(f), rewrite_update(self._c, self._spec, d), upsert=ups))
            elif isinstance(r, ReplaceOne): out.append(ReplaceOne(self._f(f), encrypt_doc(self._c, self._spec, d), upsert=ups))
            elif isinstance(r, InsertOne): out.append(InsertOne(encrypt_doc(self._c, self._spec, d)))
            elif isinstance(r, DeleteOne): out.append(DeleteOne(self._f(f)))
            elif isinstance(r, DeleteMany): out.append(DeleteMany(self._f(f)))
            else: out.append(r)
        return await self._coll.bulk_write(out, *a, **k)


class _ReadDecryptCollection(EncryptedCollection):
    """Collections without personal fields: only decrypt values coming back (e.g. $lookup of users)."""
    def __init__(self, coll, c):
        super().__init__(coll, c, {})


class EncryptedDatabase:
    def __init__(self, db, c: PIICipher):
        self._db, self._c = db, c
    def _wrap(self, coll):
        name = getattr(coll, "name", "")
        return EncryptedCollection(coll, self._c, SPEC[name]) if name in SPEC else _ReadDecryptCollection(coll, self._c)
    def __getattr__(self, n):
        a = getattr(self._db, n)
        return self._wrap(a) if type(a).__name__.endswith("Collection") else a
    def __getitem__(self, n):
        return self._wrap(self._db[n])
    def get_collection(self, n, *a, **k):
        return self._wrap(self._db.get_collection(n, *a, **k))
    @property
    def raw(self):
        return self._db


def wrap_database(db):
    """Install the proxy when both keys are set; otherwise return the database unchanged."""
    c = cipher_from_env()
    if not c:
        logger.warning("PII encryption is OFF (PII_ENC_KEY / PII_INDEX_KEY not set)")
        return db
    logger.info("🔐 PII field encryption is ON")
    return EncryptedDatabase(db, c)
