"""Probe: does Resend accept plus-addressed sink recipients?"""
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv("/app/backend/.env", override=True)
sys.path.insert(0, "/app/backend")
import email_service  # noqa: E402


async def main():
    for to in ["delivered+gc1234@resend.dev", "delivered@resend.dev"]:
        ok = await email_service.send_email_via_resend(to, "TEST_ iter12 alias probe", "<p>x</p>")
        print(to, "->", ok)


asyncio.run(main())
