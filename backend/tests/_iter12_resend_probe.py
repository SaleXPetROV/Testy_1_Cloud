"""Iteration 12 probe: direct call to email_service.send_email_with_code_async with real Resend key."""
import asyncio
import importlib
import sys

from dotenv import load_dotenv

load_dotenv("/app/backend/.env", override=True)
sys.path.insert(0, "/app/backend")

import email_service  # noqa: E402

importlib.reload(email_service)

print("RESEND_AVAILABLE:", email_service.RESEND_AVAILABLE)
print("KEY prefix:", email_service.RESEND_API_KEY[:8], "len:", len(email_service.RESEND_API_KEY))
print("SENDER:", repr(email_service.SENDER_EMAIL))


async def main():
    ok = await email_service.send_email_with_code_async(
        "delivered@resend.dev", "123456", "en", "verification"
    )
    print("send_email_with_code_async ->", ok)
    ok2 = await email_service.send_email_via_resend(
        "delivered@resend.dev", "TEST_ probe subject", "<p>probe</p>"
    )
    print("send_email_via_resend ->", ok2)


asyncio.run(main())
