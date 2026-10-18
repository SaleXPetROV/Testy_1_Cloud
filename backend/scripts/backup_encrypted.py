"""Encrypted database backups (AES-256-GCM) — the backup file is useless without the key.

    cd backend
    python -m scripts.backup_encrypted --new-key                 # print a new key (keep it OFF the server!)
    BACKUP_KEY=... python -m scripts.backup_encrypted backup  /backups/gram_2026-10-10.enc
    BACKUP_KEY=... python -m scripts.backup_encrypted restore /backups/gram_2026-10-10.enc   # into an EMPTY database
    BACKUP_KEY=... python -m scripts.backup_encrypted verify  /backups/gram_2026-10-10.enc

File format: b"GRAMBK1" | 12-byte nonce | AES-256-GCM(gzip(BSON stream of {c: collection, d: document}))
The authentication tag makes any change to the file detectable (restore refuses it).
Env: MONGO_URL, DB_NAME (same as the server), BACKUP_KEY (base64, 32 bytes).
"""
import argparse, asyncio, base64, gzip, io, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bson  # noqa: E402  (ships with pymongo)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MAGIC = b"GRAMBK1"
SKIP = ("migration_backup_",)          # temporary migration copies are not part of a backup


def _key() -> bytes:
    k = os.environ.get("BACKUP_KEY", "")
    try:
        raw = base64.b64decode(k)
    except Exception:
        raw = b""
    if len(raw) != 32:
        sys.exit("BACKUP_KEY must be 32 bytes in base64 (python -m scripts.backup_encrypted --new-key)")
    return raw


def _db():
    return AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[os.environ.get("DB_NAME", "ton_city")]


async def backup(path: str, db=None) -> dict:
    db = db if db is not None else _db()
    buf = io.BytesIO(); counts = {}
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
        for name in sorted(await db.list_collection_names()):
            if name.startswith(SKIP) or name.startswith("system."):
                continue
            n = 0
            async for doc in db[name].find({}):
                gz.write(bson.encode({"c": name, "d": doc})); n += 1
            counts[name] = n
    nonce = os.urandom(12)
    blob = MAGIC + nonce + AESGCM(_key()).encrypt(nonce, buf.getvalue(), MAGIC)
    Path(path).write_bytes(blob); os.chmod(path, 0o600)
    return {"collections": len(counts), "documents": sum(counts.values()), "bytes": len(blob)}


def _read(path: str):
    blob = Path(path).read_bytes()
    if not blob.startswith(MAGIC):
        sys.exit("not a GRAM City backup")
    nonce, data = blob[len(MAGIC):len(MAGIC) + 12], blob[len(MAGIC) + 12:]
    try:
        plain = AESGCM(_key()).decrypt(nonce, data, MAGIC)
    except Exception:
        sys.exit("wrong BACKUP_KEY or the file was modified — refusing")
    raw = gzip.decompress(plain)
    return bson.decode_all(raw)


async def restore(path: str, db=None) -> dict:
    db = db if db is not None else _db()
    if [n for n in await db.list_collection_names() if not n.startswith("system.")]:
        sys.exit("the target database is not empty — restore only into an empty database")
    rows, counts = _read(path), {}
    by = {}
    for r in rows:
        by.setdefault(r["c"], []).append(r["d"])
    for name, docs in by.items():
        for i in range(0, len(docs), 1000):
            await db[name].insert_many(docs[i:i + 1000])
        counts[name] = len(docs)
    return {"collections": len(counts), "documents": sum(counts.values())}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", choices=["backup", "restore", "verify"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--new-key", action="store_true")
    a = ap.parse_args()
    if a.new_key:
        print(base64.b64encode(os.urandom(32)).decode()); return
    if not a.action or not a.path:
        ap.error("action and path are required")
    if a.action == "backup":
        print(asyncio.run(backup(a.path)))
    elif a.action == "restore":
        print(asyncio.run(restore(a.path)))
    else:
        rows = _read(a.path); print({"ok": True, "documents": len(rows)})


if __name__ == "__main__":
    main()
