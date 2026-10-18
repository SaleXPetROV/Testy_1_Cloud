#!/usr/bin/env python3
"""
Backend Test Suite for Telegram Bot Fixes & Security Patches
=============================================================
Tests 6 independent fixes:
  1. Diagnostic GET endpoint reachable
  2. Webhook diagnostic log emitted on /start
  3. Language-selection cascade (fallback on send failure)
  4. Link-token persistence survives in-memory wipe
  5. F1 security regression (SECRET_KEY)
  6. F6 security regression (secrets.choice for OTP)
"""

import asyncio
import sys
import os
import time
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

# Add backend to path
sys.path.insert(0, '/app/backend')

# Load environment
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
load_dotenv('/app/frontend/.env')

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
REACT_APP_BACKEND_URL = os.environ.get('REACT_APP_BACKEND_URL', '')

print(f"[CONFIG] MONGO_URL: {MONGO_URL}")
print(f"[CONFIG] DB_NAME: {DB_NAME}")
print(f"[CONFIG] REACT_APP_BACKEND_URL: {REACT_APP_BACKEND_URL}")

# MongoDB client
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


# ============================================================
# TEST 1: Diagnostic GET endpoint reachable
# ============================================================
async def test_1_diagnostic_endpoint():
    """GET /api/telegram/webhook returns 200 with diagnostic fields."""
    import aiohttp
    
    print("\n" + "="*60)
    print("TEST 1: Diagnostic GET endpoint reachable")
    print("="*60)
    
    url = f"{REACT_APP_BACKEND_URL}/api/telegram/webhook"
    print(f"[TEST 1] GET {url}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                status = resp.status
                data = await resp.json()
                
                print(f"[TEST 1] Status: {status}")
                print(f"[TEST 1] Response: {data}")
                
                # Assertions
                assert status == 200, f"Expected 200, got {status}"
                assert "endpoint_reachable" in data, "Missing 'endpoint_reachable' field"
                assert data["endpoint_reachable"] is True, "endpoint_reachable must be True"
                assert "bot_token_loaded" in data, "Missing 'bot_token_loaded' field"
                assert "bot_initialized" in data, "Missing 'bot_initialized' field"
                assert "webhook_from_telegram" in data, "Missing 'webhook_from_telegram' field"
                
                print("[TEST 1] ✅ PASS - Diagnostic endpoint reachable with correct schema")
                return True
    except Exception as e:
        print(f"[TEST 1] ❌ FAIL - {e}")
        return False


# ============================================================
# TEST 2: Webhook diagnostic log emitted on /start
# ============================================================
async def test_2_webhook_diagnostic_log():
    """POST /api/telegram/webhook with /start → log line 'TG_WH id=...' appears."""
    import aiohttp
    import subprocess
    
    print("\n" + "="*60)
    print("TEST 2: Webhook diagnostic log emitted on /start")
    print("="*60)
    
    url = f"{REACT_APP_BACKEND_URL}/api/telegram/webhook"
    
    # Synthetic /start update
    update = {
        "update_id": 999999,
        "message": {
            "message_id": 1,
            "from": {
                "id": 12345,
                "is_bot": False,
                "first_name": "TestUser",
                "username": "testuser"
            },
            "chat": {
                "id": 12345,
                "first_name": "TestUser",
                "username": "testuser",
                "type": "private"
            },
            "date": int(time.time()),
            "text": "/start"
        }
    }
    
    print(f"[TEST 2] POST {url}")
    print(f"[TEST 2] Payload: {update}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=update, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                status = resp.status
                data = await resp.json()
                
                print(f"[TEST 2] Status: {status}")
                print(f"[TEST 2] Response: {data}")
                
                # Wait a moment for log to be written
                await asyncio.sleep(2)
                
                # Check backend logs for diagnostic line
                result = subprocess.run(
                    ["tail", "-n", "100", "/var/log/supervisor/backend.err.log"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                log_output = result.stdout
                
                # Look for the diagnostic log line
                found = False
                for line in log_output.split('\n'):
                    if 'TG_WH id=' in line and 'msg=' in line:
                        print(f"[TEST 2] Found diagnostic log: {line}")
                        found = True
                        break
                
                assert found, "Diagnostic log line 'TG_WH id=...' not found in backend logs"
                
                print("[TEST 2] ✅ PASS - Webhook diagnostic log emitted")
                return True
    except Exception as e:
        print(f"[TEST 2] ❌ FAIL - {e}")
        return False


# ============================================================
# TEST 3: Language-selection cascade
# ============================================================
async def test_3_language_selection_cascade():
    """Direct-invoke cmd_start with monkey-patched send_message that fails first, succeeds second."""
    print("\n" + "="*60)
    print("TEST 3: Language-selection cascade (direct-invoke)")
    print("="*60)
    
    try:
        from telegram_bot import TelegramBot
        
        bot = TelegramBot(db)
        
        # Monkey-patch send_message to fail on first call, succeed on subsequent
        captured = []
        call_count = [0]
        
        original_send = bot.send_message
        
        async def mock_send(chat_id, text, parse_mode="HTML", reply_markup=None):
            call_count[0] += 1
            captured.append({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
                "call_number": call_count[0]
            })
            
            # First call fails, subsequent succeed
            if call_count[0] == 1:
                print(f"[TEST 3] Mock send_message call #{call_count[0]} - FAIL (simulated)")
                return False
            else:
                print(f"[TEST 3] Mock send_message call #{call_count[0]} - SUCCESS")
                return True
        
        bot.send_message = mock_send
        
        # Delete telegram_mappings for test chat_id
        chat_id = "80001"
        await db.telegram_mappings.delete_one({"chat_id": chat_id})
        print(f"[TEST 3] Deleted telegram_mappings for chat_id={chat_id}")
        
        # Invoke cmd_start
        print(f"[TEST 3] Invoking cmd_start for chat_id={chat_id}")
        await bot.cmd_start(chat_id, "testuser", "TestUser", [])
        
        # Restore original
        bot.send_message = original_send
        
        print(f"[TEST 3] Captured {len(captured)} send_message calls")
        
        # Assertions
        assert len(captured) >= 2, f"Expected at least 2 send_message calls, got {len(captured)}"
        
        # First call should be HTML attempt
        first = captured[0]
        print(f"[TEST 3] First call parse_mode: {first['parse_mode']}")
        
        # Second call should be plaintext fallback
        second = captured[1]
        print(f"[TEST 3] Second call parse_mode: {second['parse_mode']}")
        print(f"[TEST 3] Second call text preview: {second['text'][:100]}")
        
        assert second['parse_mode'] == "", f"Expected plaintext (parse_mode=''), got '{second['parse_mode']}'"
        
        # Check text contains language selection
        text_lower = second['text'].lower()
        assert "choose your language" in text_lower or "выберите язык" in text_lower, \
            "Second call text should contain language selection prompt"
        
        # Cleanup
        await db.telegram_mappings.delete_one({"chat_id": chat_id})
        
        print("[TEST 3] ✅ PASS - Language-selection cascade works correctly")
        return True
    except Exception as e:
        print(f"[TEST 3] ❌ FAIL - {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# TEST 4: Link-token persistence survives in-memory wipe
# ============================================================
async def test_4_link_token_persistence():
    """Generate link token, verify in MongoDB, wipe in-memory cache, verify linking still works."""
    print("\n" + "="*60)
    print("TEST 4: Link-token persistence survives in-memory wipe")
    print("="*60)
    
    try:
        import aiohttp
        import uuid
        
        # a) Login as testuser@example.com
        print("[TEST 4] Step a) Login as testuser@example.com")
        
        login_url = f"{REACT_APP_BACKEND_URL}/api/auth/login"
        login_data = {
            "email": "testuser@example.com",
            "password": "Test1234!"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(login_url, json=login_data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    print(f"[TEST 4] Login failed with status {resp.status}")
                    data = await resp.text()
                    print(f"[TEST 4] Response: {data}")
                    raise Exception(f"Login failed: {resp.status}")
                
                login_resp = await resp.json()
                token = login_resp.get("token")
                user_id = login_resp.get("user", {}).get("id")
                
                print(f"[TEST 4] Login successful, user_id: {user_id}")
                
                # b) POST /api/telegram/generate-link-token
                print("[TEST 4] Step b) Generate link token")
                
                gen_url = f"{REACT_APP_BACKEND_URL}/api/telegram/generate-link-token"
                headers = {"Authorization": f"Bearer {token}"}
                
                async with session.post(gen_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        print(f"[TEST 4] Generate token failed with status {resp.status}")
                        data = await resp.text()
                        print(f"[TEST 4] Response: {data}")
                        raise Exception(f"Generate token failed: {resp.status}")
                    
                    gen_resp = await resp.json()
                    link_token = gen_resp.get("token")
                    bot_link = gen_resp.get("bot_link")
                    
                    print(f"[TEST 4] Token generated: {link_token}")
                    print(f"[TEST 4] Bot link: {bot_link}")
        
        # c) Verify token in MongoDB
        print("[TEST 4] Step c) Verify token in MongoDB")
        
        token_doc = await db.telegram_link_tokens.find_one({"_id": link_token})
        assert token_doc is not None, "Token not found in MongoDB"
        assert token_doc.get("user_id") == user_id, "Token user_id mismatch"
        assert "expires_at" in token_doc, "Token missing expires_at"
        
        print(f"[TEST 4] Token found in MongoDB: {token_doc}")
        
        # d) Simulate backend restart - wipe in-memory cache
        print("[TEST 4] Step d) Wipe in-memory cache")
        
        from server import telegram_link_tokens
        telegram_link_tokens.clear()
        
        print(f"[TEST 4] In-memory cache cleared, size: {len(telegram_link_tokens)}")
        
        # e) Direct invoke process_link_token
        print("[TEST 4] Step e) Invoke process_link_token")
        
        from telegram_bot import TelegramBot
        
        bot = TelegramBot(db)
        
        # Monkey-patch send_message to capture
        captured = []
        
        async def mock_send(chat_id, text, parse_mode="HTML", reply_markup=None):
            captured.append({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup
            })
            return True
        
        bot.send_message = mock_send
        
        test_chat_id = "80002"
        test_username = "testlinker"
        
        await bot.process_link_token(test_chat_id, test_username, link_token)
        
        print(f"[TEST 4] Captured {len(captured)} messages")
        
        # Assertions
        assert len(captured) > 0, "No messages captured"
        
        success_msg = captured[0]["text"]
        print(f"[TEST 4] Message text: {success_msg[:200]}")
        
        assert "Аккаунт привязан" in success_msg or "привязан" in success_msg.lower(), \
            "Success message should contain 'Аккаунт привязан'"
        
        # Verify user updated in MongoDB
        user_doc = await db.users.find_one({"id": user_id})
        assert user_doc is not None, "User not found"
        assert user_doc.get("telegram_chat_id") == test_chat_id, "telegram_chat_id not updated"
        assert user_doc.get("telegram_notifications") is True, "telegram_notifications not enabled"
        
        print(f"[TEST 4] User updated: telegram_chat_id={user_doc.get('telegram_chat_id')}")
        
        # Verify token removed from both stores
        token_doc_after = await db.telegram_link_tokens.find_one({"_id": link_token})
        assert token_doc_after is None, "Token should be removed from MongoDB after use"
        
        assert link_token not in telegram_link_tokens, "Token should be removed from in-memory cache"
        
        print("[TEST 4] Token removed from both stores")
        
        # Cleanup - reset user's telegram_chat_id
        await db.users.update_one(
            {"id": user_id},
            {"$unset": {"telegram_chat_id": "", "telegram_notifications": ""}}
        )
        
        print("[TEST 4] ✅ PASS - Link-token persistence works correctly")
        return True
    except Exception as e:
        print(f"[TEST 4] ❌ FAIL - {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# TEST 5: F1 security regression (SECRET_KEY)
# ============================================================
async def test_5_f1_security_regression():
    """Verify SECRET_KEY in 5 fixed modules is non-empty and not the old hardcoded value."""
    print("\n" + "="*60)
    print("TEST 5: F1 security regression (SECRET_KEY)")
    print("="*60)
    
    try:
        modules = [
            "business_system",
            "chat_handler",
            "core.constants",
            "transaction_history",
            "security.security_router"
        ]
        
        secrets = {}
        
        for mod_name in modules:
            print(f"[TEST 5] Importing {mod_name}")
            
            mod = __import__(mod_name, fromlist=['SECRET_KEY'])
            secret = getattr(mod, 'SECRET_KEY', None)
            
            print(f"[TEST 5] {mod_name}.SECRET_KEY = {secret[:20] if secret else 'None'}...")
            
            # Assertions
            assert secret is not None, f"{mod_name}.SECRET_KEY is None"
            assert isinstance(secret, str), f"{mod_name}.SECRET_KEY is not a string"
            assert len(secret) > 0, f"{mod_name}.SECRET_KEY is empty"
            assert secret != "ton-city-builder-secret-key-2025", \
                f"{mod_name}.SECRET_KEY is still the old hardcoded value"
            
            secrets[mod_name] = secret
        
        # Verify all modules use the SAME secret
        unique_secrets = set(secrets.values())
        print(f"[TEST 5] Unique secrets count: {len(unique_secrets)}")
        
        assert len(unique_secrets) == 1, \
            f"All modules should use the same SECRET_KEY, found {len(unique_secrets)} different values"
        
        print("[TEST 5] ✅ PASS - All modules use the same non-hardcoded SECRET_KEY")
        return True
    except Exception as e:
        print(f"[TEST 5] ❌ FAIL - {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# TEST 6: F6 security regression (secrets.choice for OTP)
# ============================================================
async def test_6_f6_security_regression():
    """Verify auth_handler.py uses secrets.choice for OTP generation (not random.choices)."""
    print("\n" + "="*60)
    print("TEST 6: F6 security regression (secrets.choice for OTP)")
    print("="*60)
    
    try:
        import subprocess
        
        # Check that random.choices is NOT used
        print("[TEST 6] Checking for random.choices('0123456789')")
        
        result = subprocess.run(
            ["grep", "-n", "random.choices('0123456789'", "/app/backend/auth_handler.py"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"[TEST 6] ❌ Found random.choices in auth_handler.py:")
            print(result.stdout)
            raise Exception("auth_handler.py still uses random.choices for OTP")
        
        print("[TEST 6] ✓ No random.choices found")
        
        # Check that secrets.choice is used at least 3 times
        print("[TEST 6] Checking for secrets.choice('0123456789')")
        
        result = subprocess.run(
            ["grep", "-c", "secrets.choice('0123456789')", "/app/backend/auth_handler.py"],
            capture_output=True,
            text=True
        )
        
        count = int(result.stdout.strip())
        print(f"[TEST 6] Found {count} occurrences of secrets.choice('0123456789')")
        
        assert count >= 3, f"Expected at least 3 occurrences of secrets.choice, found {count}"
        
        # Check that secrets is imported
        print("[TEST 6] Checking for 'import secrets'")
        
        result = subprocess.run(
            ["grep", "-n", "import secrets", "/app/backend/auth_handler.py"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise Exception("'import secrets' not found in auth_handler.py")
        
        print(f"[TEST 6] Found import secrets:")
        print(result.stdout)
        
        print("[TEST 6] ✅ PASS - auth_handler.py uses secrets.choice for OTP generation")
        return True
    except Exception as e:
        print(f"[TEST 6] ❌ FAIL - {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# MAIN TEST RUNNER
# ============================================================
async def main():
    print("\n" + "="*60)
    print("BACKEND TEST SUITE - Telegram Bot Fixes & Security Patches")
    print("="*60)
    
    results = {}
    
    # Run all tests
    results["TEST 1"] = await test_1_diagnostic_endpoint()
    results["TEST 2"] = await test_2_webhook_diagnostic_log()
    results["TEST 3"] = await test_3_language_selection_cascade()
    results["TEST 4"] = await test_4_link_token_persistence()
    results["TEST 5"] = await test_5_f1_security_regression()
    results["TEST 6"] = await test_6_f6_security_regression()
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
