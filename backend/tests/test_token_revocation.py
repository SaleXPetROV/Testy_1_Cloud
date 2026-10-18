import asyncio, time
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
from core import token_revocation as tr


def test_revoke_all_rejects_older_tokens_only():
    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["rev"]
        tr._cache.clear()
        await db.users.insert_one({"id": "u1", "email": "a@x.io"})
        old = {"sub": "u1", "iat": time.time() - 5}
        assert not await tr.is_revoked(db, old)                         # nothing revoked yet
        await tr.revoke_all(db, {"id": "u1"})
        assert await tr.is_revoked(db, old)                             # the cache is dropped at once
        assert await tr.is_revoked(db, {"sub": "a@x.io", "iat": time.time() - 5})   # old tokens with e-mail sub too
        assert not await tr.is_revoked(db, {"sub": "u1", "iat": time.time() + 0.01})  # issued after: valid
        assert await tr.is_revoked(db, {"sub": "u1"})                   # no iat at all = old token
        assert not await tr.is_revoked(db, {"sub": "nobody", "iat": 1})
    asyncio.run(go())
