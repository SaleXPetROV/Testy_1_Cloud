"""Encrypted-path sanity check for totp_crypto (runs with TOTP_ENC_KEY set).

Executed as a subprocess by test_2fa_internal_error_iter3 helpers / manually:
    TOTP_ENC_KEY=<fernet key> python tests/_iter3_totp_enc_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

import pyotp  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from security import totp_crypto  # noqa: E402

assert totp_crypto.encryption_enabled(), "TOTP_ENC_KEY not picked up"

secret = pyotp.random_base32()
token = totp_crypto.encrypt_secret(secret)
assert token != secret, "secret was not encrypted"
assert totp_crypto.decrypt_secret(token) == secret, "round-trip failed"
assert totp_crypto.is_encrypted(token) is True

# legacy plaintext still returned unchanged even with a key configured
assert totp_crypto.decrypt_secret(secret) == secret, "legacy plaintext broken"

# token from a DIFFERENT key → '' (never the raw ciphertext)
other = Fernet(Fernet.generate_key()).encrypt(secret.encode()).decode()
out = totp_crypto.decrypt_secret(other)
assert out == "", f"foreign-key token leaked: {out[:30]!r}"
assert pyotp.TOTP(out).verify("123456") is False

print("OK encrypted-path checks passed")
