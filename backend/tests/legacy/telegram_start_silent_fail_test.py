"""
Test suite for Telegram bot /start silent-fail fix.

Verifies that cmd_start correctly handles empty backend_url scenarios
by falling back to safe button types (url instead of web_app) and
retrying without keyboard on failure.
"""

import asyncio
import os
import sys
from motor.motor_asyncio import AsyncIOMotorClient

# Add backend to path
sys.path.insert(0, '/app/backend')

from telegram_bot import TelegramBot

# Environment setup
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

# DO NOT set these - we're testing the empty-backend_url path
# os.environ.pop("BACKEND_URL", None)
# os.environ.pop("REACT_APP_BACKEND_URL", None)
# os.environ.pop("PUBLIC_URL", None)

async def run_tests():
    """Run all 5 tests for the silent-fail fix."""
    
    # Connect to MongoDB
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    
    # Create bot instance
    bot = TelegramBot(db)
    
    print("=" * 80)
    print("TELEGRAM BOT /START SILENT-FAIL FIX - TEST SUITE")
    print("=" * 80)
    print()
    
    # ========================================================================
    # TEST 1: First-time /start (no language, no backend_url)
    # ========================================================================
    print("TEST 1: First-time /start (no language, no backend_url)")
    print("-" * 80)
    
    # Clean up
    await db.telegram_mappings.delete_one({"chat_id": "77001"})
    await db.support_settings.delete_one({"_id": "main"})
    
    # Monkey-patch send_message
    captured = []
    async def fake_send(chat_id, text, reply_markup=None, **kwargs):
        captured.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return True
    
    original_send = bot.send_message
    bot.send_message = fake_send
    
    # Call cmd_start
    await bot.cmd_start("77001", "u1", "User1", [])
    
    # Restore original
    bot.send_message = original_send
    
    # Assertions
    test1_pass = True
    try:
        assert len(captured) >= 1, f"Expected at least 1 message, got {len(captured)}"
        
        # Check for language selection text (should contain "Select language" or "Выберите язык")
        text = captured[-1]["text"]
        assert "Select language" in text or "Выберите язык" in text, \
            f"Expected language selection prompt in text, got: {text[:100]}"
        
        # Check that ALL buttons have callback_data starting with "lang_"
        keyboard = captured[-1]["reply_markup"]["inline_keyboard"]
        
        # Collect all button texts to verify language names are in buttons
        button_texts = []
        for row in keyboard:
            for button in row:
                assert "callback_data" in button, f"Expected callback_data in button: {button}"
                assert button["callback_data"].startswith("lang_"), f"Expected lang_ prefix, got: {button['callback_data']}"
                assert "web_app" not in button, f"No web_app buttons should be present at this stage: {button}"
                assert "url" not in button, f"No url buttons should be present at this stage: {button}"
                button_texts.append(button["text"])
        
        # Verify that button texts contain language names
        assert "Русский" in " ".join(button_texts), "Expected 'Русский' in button texts"
        assert "English" in " ".join(button_texts), "Expected 'English' in button texts"
        
        print("✅ PASS: Language selection screen shown with correct buttons")
        print(f"   - Message count: {len(captured)}")
        print(f"   - Text contains language selection prompt: ✓")
        print(f"   - All buttons have callback_data with lang_ prefix: ✓")
        print(f"   - Button texts contain language names (Русский, English): ✓")
        print(f"   - No web_app or url buttons: ✓")
    except AssertionError as e:
        print(f"❌ FAIL: {e}")
        test1_pass = False
    
    print()
    
    # ========================================================================
    # TEST 2: After picking Russian, backend_url still unresolvable
    # ========================================================================
    print("TEST 2: After picking Russian, backend_url unresolvable (welcome fallback)")
    print("-" * 80)
    
    # Set language
    await db.telegram_mappings.update_one(
        {"chat_id": "77002"},
        {"$set": {"language": "ru"}},
        upsert=True
    )
    
    # Ensure no support_settings.public_url
    await db.support_settings.delete_one({"_id": "main"})
    
    # Monkey-patch send_message
    captured = []
    bot.send_message = fake_send
    
    # Call cmd_start
    await bot.cmd_start("77002", "u2", "User2", [])
    
    # Restore original
    bot.send_message = original_send
    
    # Assertions
    test2_pass = True
    try:
        assert len(captured) >= 1, f"Expected at least 1 message, got {len(captured)}"
        
        # Find the welcome message
        welcome_msg = None
        for msg in captured:
            if "Добро пожаловать в Gram City" in msg["text"]:
                welcome_msg = msg
                break
        
        assert welcome_msg is not None, "Expected Russian welcome message with 'Добро пожаловать в Gram City'"
        
        # Check keyboard buttons
        keyboard = welcome_msg["reply_markup"]["inline_keyboard"]
        
        # Flatten all buttons
        all_buttons = []
        for row in keyboard:
            all_buttons.extend(row)
        
        # Check that NO button has web_app with relative URL
        for button in all_buttons:
            if "web_app" in button:
                web_app_url = button["web_app"]["url"]
                assert web_app_url.startswith("https://"), \
                    f"FAIL: web_app button with relative URL found: {web_app_url}"
        
        # Check that primary CTA button exists and has valid URL
        primary_button = keyboard[0][0]  # First button in first row
        assert "url" in primary_button or "web_app" in primary_button, \
            f"Primary button should have url or web_app: {primary_button}"
        
        if "url" in primary_button:
            assert primary_button["url"].startswith("https://"), \
                f"Primary button URL should start with https://: {primary_button['url']}"
        
        if "web_app" in primary_button:
            assert primary_button["web_app"]["url"].startswith("https://"), \
                f"Primary button web_app URL should start with https://: {primary_button['web_app']['url']}"
        
        # Check button text contains Russian label
        button_text = primary_button["text"]
        assert "Перейти" in button_text or "🌐" in button_text, \
            f"Primary button should have Russian label: {button_text}"
        
        print("✅ PASS: Russian welcome message with safe buttons")
        print(f"   - Message count: {len(captured)}")
        print(f"   - Text contains 'Добро пожаловать в Gram City': ✓")
        print(f"   - No web_app buttons with relative URLs: ✓")
        print(f"   - Primary CTA button has valid https:// URL: ✓")
        print(f"   - Button text contains Russian label: ✓")
    except AssertionError as e:
        print(f"❌ FAIL: {e}")
        test2_pass = False
    
    print()
    
    # ========================================================================
    # TEST 3: English fallback (same conditions as Test 2 but language="en")
    # ========================================================================
    print("TEST 3: English fallback (same conditions as Test 2 but language='en')")
    print("-" * 80)
    
    # Set language
    await db.telegram_mappings.update_one(
        {"chat_id": "77003"},
        {"$set": {"language": "en"}},
        upsert=True
    )
    
    # Monkey-patch send_message
    captured = []
    bot.send_message = fake_send
    
    # Call cmd_start
    await bot.cmd_start("77003", "u3", "User3", [])
    
    # Restore original
    bot.send_message = original_send
    
    # Assertions
    test3_pass = True
    try:
        assert len(captured) >= 1, f"Expected at least 1 message, got {len(captured)}"
        
        # Find the welcome message
        welcome_msg = None
        for msg in captured:
            if "Welcome to Gram City" in msg["text"]:
                welcome_msg = msg
                break
        
        assert welcome_msg is not None, "Expected English welcome message with 'Welcome to Gram City'"
        
        # Check keyboard buttons
        keyboard = welcome_msg["reply_markup"]["inline_keyboard"]
        
        # Flatten all buttons
        all_buttons = []
        for row in keyboard:
            all_buttons.extend(row)
        
        # Check that NO button has relative URL
        for button in all_buttons:
            if "web_app" in button:
                web_app_url = button["web_app"]["url"]
                assert web_app_url.startswith("https://"), \
                    f"FAIL: web_app button with relative URL found: {web_app_url}"
            if "url" in button and "callback_data" not in button:
                url = button["url"]
                assert url.startswith("https://"), \
                    f"FAIL: url button with relative URL found: {url}"
        
        # Check that primary CTA button exists and has valid URL
        primary_button = keyboard[0][0]  # First button in first row
        button_text = primary_button["text"]
        assert "Go to the website" in button_text or "🌐" in button_text, \
            f"Primary button should have English label: {button_text}"
        
        print("✅ PASS: English welcome message with safe buttons")
        print(f"   - Message count: {len(captured)}")
        print(f"   - Text contains 'Welcome to Gram City': ✓")
        print(f"   - No relative URLs in any button: ✓")
        print(f"   - Button text contains 'Go to the website': ✓")
    except AssertionError as e:
        print(f"❌ FAIL: {e}")
        test3_pass = False
    
    print()
    
    # ========================================================================
    # TEST 4: Once backend_url IS available, web_app buttons should reappear
    # ========================================================================
    print("TEST 4: Once backend_url IS available, web_app buttons should reappear")
    print("-" * 80)
    
    # Set backend_url in support_settings
    await db.support_settings.update_one(
        {"_id": "main"},
        {"$set": {"public_url": "https://example.com"}},
        upsert=True
    )
    
    # Set language
    await db.telegram_mappings.update_one(
        {"chat_id": "77004"},
        {"$set": {"language": "ru"}},
        upsert=True
    )
    
    # Monkey-patch send_message
    captured = []
    bot.send_message = fake_send
    
    # Call cmd_start
    await bot.cmd_start("77004", "u4", "User4", [])
    
    # Restore original
    bot.send_message = original_send
    
    # Assertions
    test4_pass = True
    try:
        assert len(captured) >= 1, f"Expected at least 1 message, got {len(captured)}"
        
        # Find the welcome message
        welcome_msg = captured[-1]
        
        # Check keyboard buttons
        keyboard = welcome_msg["reply_markup"]["inline_keyboard"]
        
        # Flatten all buttons
        all_buttons = []
        for row in keyboard:
            all_buttons.extend(row)
        
        # Look for support button (second row, second button OR second row, first button)
        # The support button should now have web_app or url with https://example.com
        found_support_button = False
        for button in all_buttons:
            if "Поддержка" in button.get("text", "") or "Support" in button.get("text", ""):
                found_support_button = True
                # Check if it has web_app or url with example.com
                if "web_app" in button:
                    assert "https://example.com" in button["web_app"]["url"], \
                        f"Support button web_app should contain https://example.com: {button['web_app']['url']}"
                elif "url" in button:
                    assert "https://example.com" in button["url"], \
                        f"Support button url should contain https://example.com: {button['url']}"
                break
        
        assert found_support_button, "Expected to find support button in keyboard"
        
        print("✅ PASS: web_app/url buttons with https://example.com present")
        print(f"   - Message count: {len(captured)}")
        print(f"   - Support button contains https://example.com: ✓")
    except AssertionError as e:
        print(f"❌ FAIL: {e}")
        test4_pass = False
    
    print()
    
    # ========================================================================
    # TEST 5: Regression - send_message failure fallback
    # ========================================================================
    print("TEST 5: Regression - send_message failure fallback")
    print("-" * 80)
    
    # Set language
    await db.telegram_mappings.update_one(
        {"chat_id": "77005"},
        {"$set": {"language": "ru"}},
        upsert=True
    )
    
    # Ensure no support_settings.public_url
    await db.support_settings.delete_one({"_id": "main"})
    
    # Monkey-patch send_message to fail on first call, succeed on second
    captured = []
    call_count = [0]
    
    async def fake_send_with_failure(chat_id, text, reply_markup=None, **kwargs):
        call_count[0] += 1
        captured.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        if call_count[0] == 1:
            return False  # First call fails
        return True  # Second call succeeds
    
    bot.send_message = fake_send_with_failure
    
    # Call cmd_start
    await bot.cmd_start("77005", "u5", "User5", [])
    
    # Restore original
    bot.send_message = original_send
    
    # Assertions
    test5_pass = True
    try:
        assert len(captured) == 2, f"Expected 2 messages (first fails, retry without keyboard), got {len(captured)}"
        
        # First message should have keyboard
        assert captured[0]["reply_markup"] is not None, "First message should have keyboard"
        
        # Second message should NOT have keyboard (retry)
        assert captured[1]["reply_markup"] is None, "Second message should NOT have keyboard (retry)"
        
        # Second message should contain welcome text
        assert "Добро пожаловать в Gram City" in captured[1]["text"], \
            "Second message should contain Russian welcome text"
        
        print("✅ PASS: send_message failure fallback works correctly")
        print(f"   - Message count: {len(captured)}")
        print(f"   - First message has keyboard: ✓")
        print(f"   - Second message has NO keyboard (retry): ✓")
        print(f"   - Second message contains welcome text: ✓")
    except AssertionError as e:
        print(f"❌ FAIL: {e}")
        test5_pass = False
    
    print()
    
    # ========================================================================
    # CLEANUP
    # ========================================================================
    print("CLEANUP")
    print("-" * 80)
    
    await db.telegram_mappings.delete_many({"chat_id": {"$in": ["77001", "77002", "77003", "77004", "77005"]}})
    await db.support_settings.delete_one({"_id": "main"})
    
    print("✅ Cleanup complete")
    print()
    
    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    all_tests = [
        ("TEST 1: First-time /start (no language, no backend_url)", test1_pass),
        ("TEST 2: Russian welcome with backend_url unresolvable", test2_pass),
        ("TEST 3: English welcome with backend_url unresolvable", test3_pass),
        ("TEST 4: web_app buttons reappear when backend_url available", test4_pass),
        ("TEST 5: send_message failure fallback", test5_pass),
    ]
    
    passed = sum(1 for _, p in all_tests if p)
    total = len(all_tests)
    
    for test_name, test_pass in all_tests:
        status = "✅ PASS" if test_pass else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print()
    print(f"TOTAL: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        return True
    else:
        print("⚠️  SOME TESTS FAILED")
        return False

if __name__ == "__main__":
    result = asyncio.run(run_tests())
    sys.exit(0 if result else 1)
