"""Encrypt the personal data that is already stored in plain text (one-off, idempotent).

    cd backend
    export PII_ENC_KEY=...  PII_INDEX_KEY=...          # the same keys as the server
    python -m scripts.encrypt_pii                      # DRY RUN: how many documents would change
    python -m scripts.encrypt_pii --apply              # encrypt + build the blind indexes + indexes
    python -m scripts.encrypt_pii --decrypt --apply    # roll back to plain text (removes the indexes fields)

Make an encrypted backup first (scripts/backup_encrypted.py). Fields: core/pii_crypto.SPEC.
"""
import argparse, asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from core.pii_crypto import SPEC, PREFIX, cipher_from_env  # noqa: E402


async def run(apply: bool, decrypt: bool, db=None) -> dict:
    c = cipher_from_env()
    if not c:
        sys.exit("Set PII_ENC_KEY and PII_INDEX_KEY")
    db = db if db is not None else AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[os.environ.get("DB_NAME", "ton_city")]
    stats = {}
    for coll, spec in SPEC.items():
        changed = 0
        async for d in db[coll].find({}, {**{f: 1 for f in spec}, **{f"{f}_bidx": 1 for f in spec}}):
            upd, uns = {}, {}
            for f, (lookup, norm) in spec.items():
                v = d.get(f)
                if decrypt:
                    if isinstance(v, str) and v.startswith(PREFIX):
                        upd[f] = c.dec(v)
                    if lookup and f"{f}_bidx" in d:
                        uns[f"{f}_bidx"] = ""
                else:
                    if v not in (None, "") and not (isinstance(v, str) and v.startswith(PREFIX)):
                        upd[f] = c.enc(v)
                    if lookup and f in d and (d.get(f"{f}_bidx") is None) and v is not None:
                        upd[f"{f}_bidx"] = c.bidx(v, norm)
            if upd or uns:
                changed += 1
                if apply:
                    op = {}
                    if upd: op["$set"] = upd
                    if uns: op["$unset"] = uns
                    await db[coll].update_one({"_id": d["_id"]}, op)
        stats[coll] = changed
        if apply and not decrypt:
            for f, (lookup, _n) in spec.items():
                if lookup:
                    try:
                        await db[coll].create_index(f"{f}_bidx")
                    except Exception:
                        pass
    print(("APPLIED " if apply else "DRY RUN ") + ("decrypt" if decrypt else "encrypt") + ":", stats)
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true"); ap.add_argument("--decrypt", action="store_true")
    a = ap.parse_args(); asyncio.run(run(a.apply, a.decrypt))
