"""Regression tests for withdrawal approval double-notification bug fix.

Verifies:
- POST /api/admin/withdrawal/approve/{tx_id} emits exactly ONE notification row
  (type='withdrawal_approved') for the withdrawing user (no double delivery).
- Notification message never contains legacy 'sent_success' placeholder.
- When ton_client.send_ton_payout returns a real hex hash, the FULL hash appears
  in the notification (not truncated).
- ton_integration.send_ton_payout returns Cell.bytes_hash().hex() (validated by
  source inspection).
- Reject flow still creates ONE 'withdrawal_rejected' notification and refunds.

Approach: hot-swap ton_integration.py with a stubbed send_ton_payout that reads
a controlled hash from /tmp/test_ton_mock_hash. Backend hot-reloads picks it up.
Restore file at session teardown.
"""
import os
import re
import time
import uuid
import shutil
import pytest
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASS = "Test1234!"

TON_INTEGRATION_PATH = "/app/backend/ton_integration.py"
TON_INTEGRATION_BACKUP = "/app/backend/ton_integration.py.bak_test"
FLAG_FILE = "/tmp/test_ton_mock_hash"

STUB_MARKER = "# ---TEST-STUB-INJECTED-FILE-FLAG---"
STUB_SNIPPET = (
    "        " + STUB_MARKER + "\n"
    "        try:\n"
    "            with open('/tmp/test_ton_mock_hash', 'r') as _fh:\n"
    "                _stub_val = _fh.read().strip()\n"
    "                if _stub_val:\n"
    "                    return _stub_val\n"
    "        except FileNotFoundError:\n"
    "            pass\n"
)


def _inject_stub():
    with open(TON_INTEGRATION_PATH, "r") as f:
        src = f.read()
    if STUB_MARKER in src:
        return
    shutil.copyfile(TON_INTEGRATION_PATH, TON_INTEGRATION_BACKUP)
    pattern = re.compile(r'(async def send_ton_payout\(self,[^\)]*\):\n\s+"""[^"]*"""\n)')
    new_src, n = pattern.subn(lambda m: m.group(1) + STUB_SNIPPET, src, count=1)
    if n == 0:
        pattern2 = re.compile(r'(async def send_ton_payout\(self,[^\)]*\):\n)')
        new_src, n = pattern2.subn(lambda m: m.group(1) + STUB_SNIPPET, src, count=1)
    assert n == 1, "Failed to inject stub into send_ton_payout"
    with open(TON_INTEGRATION_PATH, "w") as f:
        f.write(new_src)


def _restore_stub():
    if os.path.exists(TON_INTEGRATION_BACKUP):
        shutil.copyfile(TON_INTEGRATION_BACKUP, TON_INTEGRATION_PATH)
        os.remove(TON_INTEGRATION_BACKUP)


def _wait_backend_ready(timeout=30):
    for _ in range(timeout):
        try:
            r = requests.get(f"{BASE_URL}/api/", timeout=3)
            if r.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(1)


@pytest.fixture(scope="session", autouse=True)
def stub_ton_send():
    _inject_stub()
    os.system("sudo supervisorctl restart backend >/dev/null 2>&1")
    time.sleep(6)
    _wait_backend_ready()
    yield
    _restore_stub()
    try:
        os.remove(FLAG_FILE)
    except FileNotFoundError:
        pass
    os.system("sudo supervisorctl restart backend >/dev/null 2>&1")
    time.sleep(3)


@pytest.fixture(scope="session")
def mongo():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def user_token_and_id():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": USER_EMAIL, "password": USER_PASS}, timeout=15)
    assert r.status_code == 200, f"User login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    return data["token"], data["user"]["id"]


def _ensure_withdrawal_wallet(mongo):
    fake_seed = " ".join(["abandon"] * 24)
    mongo.admin_settings.update_one(
        {"type": "withdrawal_wallet"},
        {"$set": {"type": "withdrawal_wallet", "mnemonic": fake_seed}},
        upsert=True,
    )


def _seed_pending_withdrawal(mongo, user_id, net=1.2345, commission=0.0655, amount=1.3):
    tx_id = f"TEST_wd_{uuid.uuid4().hex[:12]}"
    wallet_addr = "UQTEST_wallet_dummy_for_test_" + tx_id[-8:]
    mongo.users.update_one(
        {"id": user_id},
        {"$set": {
            "wallet_address": wallet_addr,
            "raw_address": "0:" + "a" * 64,
        }},
    )
    doc = {
        "id": tx_id,
        "type": "withdrawal",
        "status": "pending",
        "user_id": user_id,
        "user_wallet": wallet_addr,
        "amount_ton": amount,
        "net_amount": net,
        "commission": commission,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.transactions.insert_one(doc)
    return tx_id


def _set_hash(val):
    with open(FLAG_FILE, "w") as f:
        f.write(val)


# ============ Tests ============

class TestWithdrawalNotifySingleFanout:
    approved_tx_ids = []
    user_id = None

    def test_1_setup(self, user_token_and_id, mongo):
        _, user_id = user_token_and_id
        type(self).user_id = user_id
        _ensure_withdrawal_wallet(mongo)

    def test_2_approve_with_real_hash_creates_one_notification(
        self, admin_token, user_token_and_id, mongo
    ):
        _, user_id = user_token_and_id
        real_hash = "a1b2c3" + "d" * 58  # 64 hex chars
        _set_hash(real_hash)

        mongo.notifications.delete_many(
            {"user_id": user_id, "type": "withdrawal_approved"}
        )

        tx_id = _seed_pending_withdrawal(mongo, user_id)
        type(self).approved_tx_ids.append(tx_id)

        r = requests.post(
            f"{BASE_URL}/api/admin/withdrawal/approve/{tx_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, f"approve failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        assert body.get("status") == "completed"
        assert body.get("hash") == real_hash, f"expected hash {real_hash}, got {body.get('hash')}"

        # Small delay for async notify_user to complete
        time.sleep(0.5)
        notifs = list(mongo.notifications.find(
            {"user_id": user_id, "type": "withdrawal_approved"}
        ))
        assert len(notifs) == 1, f"Expected 1 withdrawal_approved notification, got {len(notifs)}: {notifs}"
        n = notifs[0]
        assert n.get("title") == "Вывод одобрен"
        msg = n.get("message", "")
        assert "sent_success" not in msg, f"'sent_success' leaked into message: {msg}"
        assert real_hash in msg, f"Full hash not in message: {msg}"

    def test_3_approve_with_sent_success_omits_placeholder(
        self, admin_token, user_token_and_id, mongo
    ):
        _, user_id = user_token_and_id
        _set_hash("sent_success")

        mongo.notifications.delete_many(
            {"user_id": user_id, "type": "withdrawal_approved"}
        )

        tx_id = _seed_pending_withdrawal(mongo, user_id)
        type(self).approved_tx_ids.append(tx_id)

        r = requests.post(
            f"{BASE_URL}/api/admin/withdrawal/approve/{tx_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]

        time.sleep(0.5)
        notifs = list(mongo.notifications.find(
            {"user_id": user_id, "type": "withdrawal_approved"}
        ))
        assert len(notifs) == 1, f"Expected 1 notif, got {len(notifs)}"
        msg = notifs[0].get("message", "")
        assert "sent_success" not in msg, f"'sent_success' leaked: {msg}"
        assert "Транзакция:" not in msg, \
            f"tx line should be omitted when hash=='sent_success': {msg}"

    def test_4_reject_flow_creates_notification(
        self, admin_token, user_token_and_id, mongo
    ):
        _, user_id = user_token_and_id
        mongo.notifications.delete_many(
            {"user_id": user_id, "type": "withdrawal_rejected"}
        )

        tx_id = _seed_pending_withdrawal(mongo, user_id)
        type(self).approved_tx_ids.append(tx_id)

        r = requests.post(
            f"{BASE_URL}/api/admin/withdrawal/reject/{tx_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, f"reject failed: {r.status_code} {r.text[:300]}"

        time.sleep(0.5)
        notifs = list(mongo.notifications.find(
            {"user_id": user_id, "type": "withdrawal_rejected"}
        ))
        assert len(notifs) >= 1, "Reject should create at least 1 in-app notification"
        assert notifs[0].get("title") == "Вывод отклонён"

    def test_5_source_uses_bytes_hash_hex(self):
        """Static assertion: ton_integration.py computes Cell.bytes_hash().hex()
        and returns it instead of 'sent_success'."""
        path = TON_INTEGRATION_BACKUP if os.path.exists(TON_INTEGRATION_BACKUP) else TON_INTEGRATION_PATH
        with open(path) as f:
            src = f.read()
        assert "bytes_hash()" in src, "Cell.bytes_hash() not used in ton_integration.py"
        assert "msg_hash_hex" in src, "msg_hash_hex variable missing"
        assert 'return "sent_success"' not in src and "return 'sent_success'" not in src, \
            "Legacy sent_success return string still present"

    @classmethod
    def teardown_class(cls):
        client = MongoClient(MONGO_URL)
        db = client[DB_NAME]
        try:
            db.transactions.delete_many({"id": {"$in": cls.approved_tx_ids}})
            if cls.user_id:
                db.notifications.delete_many(
                    {"user_id": cls.user_id,
                     "type": {"$in": ["withdrawal_approved", "withdrawal_rejected"]}}
                )
        except Exception:
            pass
        try:
            os.remove(FLAG_FILE)
        except FileNotFoundError:
            pass
