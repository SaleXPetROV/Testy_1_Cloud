import asyncio, base64, os
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
from scripts import backup_encrypted as bk


def test_backup_is_encrypted_restorable_and_tamper_proof(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_KEY", base64.b64encode(os.urandom(32)).decode())
    src = mongomock_motor.AsyncMongoMockClient()["src"]; dst = mongomock_motor.AsyncMongoMockClient()["dst"]
    async def go():
        await src.users.insert_many([{"id": "u1", "email": "alice@example.com", "balance_ton": 12.5}, {"id": "u2"}])
        await src.businesses.insert_one({"id": "b1", "owner": "u1"})
        await src.migration_backup_x.insert_one({"tmp": 1})
        f = tmp_path / "b.enc"
        r = await bk.backup(str(f), src)
        assert r["documents"] == 3                                      # migration copies skipped
        raw = f.read_bytes()
        assert b"alice@example.com" not in raw and b"balance_ton" not in raw   # nothing readable
        assert (await bk.restore(str(f), dst))["documents"] == 3
        assert (await dst.users.find_one({"id": "u1"}))["email"] == "alice@example.com"
        bad = bytearray(raw); bad[-5] ^= 1; f.write_bytes(bytes(bad))
        with pytest.raises(SystemExit):                                  # any change is detected
            bk._read(str(f))
        monkeypatch.setenv("BACKUP_KEY", base64.b64encode(os.urandom(32)).decode())
        f.write_bytes(raw)
        with pytest.raises(SystemExit):                                  # wrong key
            bk._read(str(f))
    asyncio.run(go())
