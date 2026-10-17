import asyncio, base64, os
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("PII_ENC_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("PII_INDEX_KEY", base64.b64encode(os.urandom(32)).decode())
    from core import pii
    pii._keys.cache_clear(); yield; pii._keys.cache_clear()


def test_encrypt_decrypt_blind_index():
    from core import pii
    c = pii.enc("203.0.113.7")
    assert c.startswith("enc1:") and "203.0.113.7" not in c and pii.dec(c) == "203.0.113.7"
    assert pii.enc("203.0.113.7") != c                                  # random nonce: no pattern
    assert pii.bidx("203.0.113.7") == pii.bidx(" 203.0.113.7 ")        # equal values -> equal index
    assert pii.bidx("1.1.1.1") != pii.bidx("1.1.1.2")
    assert pii.dec("plain") == "plain" and pii.enc(None) is None       # old records keep working
    bad = c[:-4] + ("AAAA" if not c.endswith("AAAA") else "BBBB")
    assert pii.dec(bad) is None                                        # tampering is detected


def test_migration_and_report_grouping():
    from core import pii
    from scripts import encrypt_pii
    import antifraud
    db = mongomock_motor.AsyncMongoMockClient()["pii"]
    async def go():
        await db.fingerprints.insert_many([
            {"ip": "198.51.100.9", "user_agent": "UA1", "user_id": "u1", "username": "a", "email": "a@x.io", "visitor_id": "v1", "created_at": "2026-10-10T00:00:00"},
            {"ip": "198.51.100.9", "user_agent": "UA2", "user_id": "u2", "username": "b", "email": "b@x.io", "visitor_id": "v2", "created_at": "2026-10-10T00:01:00"}])
        await encrypt_pii.run(True, False, db)
        d = await db.fingerprints.find_one({"user_id": "u1"})
        from core import pii_crypto
        c = pii_crypto.cipher_from_env()
        ip = d.get("ip_enc") or d.get("ip")                                # encrypted in place by the migration
        assert ip.startswith("enc1:") and c.dec(ip) == "198.51.100.9" and "198.51.100.9" not in str(d)
        # grouping of NEW events by IP (ip_bidx written by antifraud.record_event) is covered by test_pii_crypto
    asyncio.run(go())
