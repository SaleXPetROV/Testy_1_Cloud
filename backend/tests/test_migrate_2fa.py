"""Tests for standalone 2FA secret migration script (backend/migrate_2fa.py)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from pymongo import MongoClient

BACKEND_DIR = Path("/app/backend")
load_dotenv(BACKEND_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
TOTP_ENC_KEY = os.environ["TOTP_ENC_KEY"]

PLAINTEXT_TFS = "JBSWY3DPEHPK3PXP"
PLAINTEXT_PENDING = "MFRGGZDFMZTWQ2LK"
TEST_EMAIL = "mig-test@example.com"


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    # final cleanup
    client[DB_NAME].users.delete_many({"email": TEST_EMAIL})
    client.close()


@pytest.fixture(scope="module")
def fernet():
    return Fernet(TOTP_ENC_KEY.encode())


@pytest.fixture(scope="module")
def temp_user(db):
    db.users.delete_many({"email": TEST_EMAIL})
    res = db.users.insert_one({
        "email": TEST_EMAIL,
        "two_factor_secret": PLAINTEXT_TFS,
        "pending_2fa_secret": PLAINTEXT_PENDING,
        "is_2fa_enabled": True,
    })
    yield res.inserted_id
    db.users.delete_many({"email": TEST_EMAIL})


def run_migration():
    result = subprocess.run(
        [sys.executable, "migrate_2fa.py"],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    assert result.returncode == 0, f"Migration failed: {result.stderr}"
    return result.stdout


def test_1_migration_encrypts_plaintext(db, fernet, temp_user):
    out = run_migration()
    assert "users_scanned=" in out
    # parse counters
    import re
    scanned = int(re.search(r"users_scanned=(\d+)", out).group(1))
    encrypted = int(re.search(r"users_encrypted=(\d+)", out).group(1))
    assert scanned >= 1
    assert encrypted >= 1

    user = db.users.find_one({"_id": temp_user})
    assert user["two_factor_secret"].startswith("gAAAAA"), user["two_factor_secret"]
    assert user["pending_2fa_secret"].startswith("gAAAAA"), user["pending_2fa_secret"]


def test_2_encrypted_value_decrypts_to_original(db, fernet, temp_user):
    user = db.users.find_one({"_id": temp_user})
    assert fernet.decrypt(user["two_factor_secret"].encode()).decode() == PLAINTEXT_TFS
    assert fernet.decrypt(user["pending_2fa_secret"].encode()).decode() == PLAINTEXT_PENDING


def test_3_migration_is_idempotent(db, fernet, temp_user):
    before = db.users.find_one({"_id": temp_user})
    out = run_migration()
    import re
    encrypted = int(re.search(r"users_encrypted=(\d+)", out).group(1))
    already = int(re.search(r"fields_already_encrypted=(\d+)", out).group(1))
    assert encrypted == 0
    assert already >= 2

    after = db.users.find_one({"_id": temp_user})
    # values untouched (no double-encryption)
    assert after["two_factor_secret"] == before["two_factor_secret"]
    assert after["pending_2fa_secret"] == before["pending_2fa_secret"]
