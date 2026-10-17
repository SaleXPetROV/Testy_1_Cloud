"""Personal data is encrypted at rest; the game keeps working through the proxy."""
import asyncio, base64, os
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
from pymongo import UpdateOne
from core import pii_crypto


@pytest.fixture()
def dbs(monkeypatch):
    monkeypatch.setenv("PII_ENC_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("PII_INDEX_KEY", base64.b64encode(os.urandom(32)).decode())
    raw = mongomock_motor.AsyncMongoMockClient()["pii"]
    return raw, pii_crypto.wrap_database(raw)


def test_encrypted_at_rest_and_lookups_work(dbs):
    raw, db = dbs
    async def go():
        await db.users.insert_one({"id": "u1", "email": "Alice@Example.com", "wallet_address": "EQabc", "telegram_chat_id": 777, "username": "alice", "last_ip": "1.2.3.4"})
        r = await raw.users.find_one({"id": "u1"})
        blob = str(r)
        assert "Alice@Example.com" not in blob and "EQabc" not in blob and "1.2.3.4" not in blob and "777" not in str(r["telegram_chat_id"])
        assert r["username"] == "alice" and r["email_bidx"] and r["wallet_address_bidx"]          # non-personal stays plain
        u = await db.users.find_one({"email": "alice@example.com"})                                 # case-insensitive e-mail
        assert u["email"] == "Alice@Example.com" and u["telegram_chat_id"] == 777 and u["last_ip"] == "1.2.3.4"
        assert (await db.users.find_one({"$or": [{"id": "zz"}, {"wallet_address": "EQabc"}]}))["id"] == "u1"
        assert await db.users.count_documents({"wallet_address": {"$in": ["EQx", "EQabc"]}}) == 1
        assert (await db.users.find_one({"email": {"$regex": "^alice@example\\.com$", "$options": "i"}}))["id"] == "u1"   # regex -> exact
        assert await db.users.count_documents({"telegram_chat_id": {"$nin": [None, ""]}}) == 1
        assert await db.users.find_one({"email": "bob@example.com"}) is None
    asyncio.run(go())


def test_updates_aggregate_distinct_bulk(dbs):
    raw, db = dbs
    async def go():
        await db.users.insert_many([{"id": "a", "email": "a@x.io", "balance_ton": 1}, {"id": "b", "email": "b@x.io", "balance_ton": 2}])
        await db.users.update_one({"id": "a"}, {"$set": {"email": "new@x.io"}})
        assert (await db.users.find_one({"email": "new@x.io"}))["id"] == "a" and await db.users.find_one({"email": "a@x.io"}) is None
        assert "new@x.io" not in str(await raw.users.find_one({"id": "a"}))
        rows = await db.users.aggregate([{"$match": {"email": "b@x.io"}}, {"$project": {"_id": 0, "id": 1, "email": 1}}]).to_list(10)
        assert rows == [{"id": "b", "email": "b@x.io"}]
        assert sorted(await db.users.distinct("email")) == ["b@x.io", "new@x.io"]
        await db.users.bulk_write([UpdateOne({"email": "b@x.io"}, {"$set": {"wallet_address": "EQb"}})])
        assert (await db.users.find_one({"wallet_address": "EQb"}))["id"] == "b"
        doc = await db.users.find_one_and_update({"id": "b"}, {"$set": {"last_device": "iPhone"}}, return_document=True)
        assert doc["last_device"] == "iPhone"
        await db.users.update_one({"id": "b"}, {"$unset": {"wallet_address": ""}})
        r = await raw.users.find_one({"id": "b"}); assert "wallet_address" not in r and "wallet_address_bidx" not in r
        cur = db.users.find({}, {"_id": 0}).sort("id", 1).limit(5)
        got = [d async for d in cur]; assert [d["email"] for d in got] == ["new@x.io", "b@x.io"]
    asyncio.run(go())


def test_migration_encrypts_existing_and_rolls_back(dbs, monkeypatch):
    raw, db = dbs
    from scripts import encrypt_pii
    async def go():
        await raw.users.insert_one({"id": "old", "email": "Old@Mail.com", "wallet_address": "EQold"})
        await raw.fingerprints.insert_one({"user_id": "old", "ip": "9.9.9.9", "visitor_id": "v1"})
        assert (await encrypt_pii.run(False, False, raw))["users"] == 1                     # dry run
        assert (await raw.users.find_one({"id": "old"}))["email"] == "Old@Mail.com"
        await encrypt_pii.run(True, False, raw)
        assert "Old@Mail.com" not in str(await raw.users.find_one({"id": "old"}))
        assert (await db.users.find_one({"email": "old@mail.com"}))["wallet_address"] == "EQold"
        assert (await db.fingerprints.find_one({"visitor_id": "v1"}))["ip"] == "9.9.9.9"
        assert (await encrypt_pii.run(True, False, raw))["users"] == 0                      # idempotent
        await encrypt_pii.run(True, True, raw)                                               # roll back
        r = await raw.users.find_one({"id": "old"}); assert r["email"] == "Old@Mail.com" and "email_bidx" not in r
    asyncio.run(go())
