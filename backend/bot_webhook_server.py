"""
GRAM City — Independent Telegram Bot Webhook Server
===================================================

A SEPARATE OS process (separate from the game API in server.py) that runs ALL
Telegram bot logic.

Flow:
    Telegram ──webhook──▶ server.py  (mailbox: verify + forward, instant 200 OK)
                              │  POST /internal/telegram/update
                              ▼
                     bot_webhook_server.py  (this process)
                              │  bot.process_webhook(update)
                              ▼
                     command / button handling, edit/delete messages, DB, …

Because this process has its own event loop, its own sockets and its own
MongoDB connection pool, heavy game-API traffic can NEVER block or interrupt
bot button handling (the "message not deleted / new one appears late" issue),
and vice-versa.

The bot token is read from the DB (game_settings.telegram_settings /
admin_settings.telegram_bot), so setting/rotating it in the admin panel works
without touching this process.

Run (see supervisor config `telegram_bot.supervisor.conf`):
    /root/.venv/bin/uvicorn bot_webhook_server:app --host 127.0.0.1 --port 8002 --workers 1
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from telegram_bot import init_telegram_bot, get_telegram_bot

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("bot_webhook_server")

# Dedicated MongoDB pool for the bot process.
mongo_url = os.environ["MONGO_URL"]
db_name = os.environ["DB_NAME"]
client = AsyncIOMotorClient(
    mongo_url,
    maxPoolSize=100,
    minPoolSize=10,
    maxIdleTimeMS=60000,
    waitQueueTimeoutMS=10000,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=10000,
    retryWrites=True,
)
db = client[db_name]


async def _load_token_from_db() -> None:
    """Mirror the stored bot token into os.environ so send_message is fast."""
    try:
        settings = await db.game_settings.find_one({"type": "telegram_settings"}, {"_id": 0})
        token = (settings or {}).get("bot_token")
        if not token:
            alt = await db.admin_settings.find_one({"type": "telegram_bot"}, {"_id": 0})
            token = (alt or {}).get("bot_token")
        if token:
            os.environ["TELEGRAM_BOT_TOKEN"] = token
            logger.info("✅ Bot token loaded from DB")
        else:
            logger.warning("⏳ Bot token not set yet — set it in the admin panel.")
    except Exception as e:
        logger.warning(f"Token load failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_telegram_bot(db)
    await _load_token_from_db()
    # Ensure the Telegram lookup indexes exist (idempotent). Without an index on
    # chat_id / telegram_chat_id, every click/message does a full collection
    # scan → 10-14s stalls + "Answer callback error" at ~20k users.
    try:
        await db.telegram_mappings.create_index("chat_id")
        await db.users.create_index("telegram_chat_id")
        logger.info("✅ Telegram lookup indexes ensured")
    except Exception as e:
        logger.warning(f"telegram index setup: {e}")
    # The bot handlers call into support_handler (agent login token, support
    # chat ingest/close). That module keeps its own module-level `db` which is
    # set via init_support() — normally called by server.py. In THIS standalone
    # process we must initialise it too, or every support call raises
    # "'NoneType' object has no attribute 'support_agents'". The user-auth
    # callables are only used by HTTP routes (not served here), so pass None.
    try:
        from support_handler import init_support
        init_support(db, None, None, get_telegram_bot)
        logger.info("✅ support_handler initialised for bot process")
    except Exception as e:
        logger.warning(f"support_handler init failed: {e}")
    logger.info("🤖 Independent bot webhook server started.")
    yield
    client.close()
    logger.info("👋 Bot webhook server stopped.")


app = FastAPI(title="GRAM City Bot Webhook Server", lifespan=lifespan)


async def _process(update: dict) -> None:
    """Run the heavy bot logic. Reloads the token from DB if it went missing
    (e.g. admin just configured it) so no restart is needed."""
    try:
        bot = get_telegram_bot()
        if bot is None:
            bot = await init_telegram_bot(db)
        if not os.environ.get("TELEGRAM_BOT_TOKEN"):
            await _load_token_from_db()
        await bot.process_webhook(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}")


@app.post("/internal/telegram/update")
async def internal_update(update: dict, background_tasks: BackgroundTasks):
    """Receive a forwarded Telegram update from server.py and process it.

    Acks the forwarder instantly; heavy handling runs in a background task on
    THIS process's event loop.
    """
    background_tasks.add_task(_process, update)
    return {"ok": True}


@app.get("/internal/health")
async def health():
    return {"status": "ok", "service": "bot_webhook_server"}


@app.post("/internal/reload-token")
async def reload_token():
    """Force the bot process to pick up a token changed in the admin panel.

    server.py calls this after the admin saves a new bot token so the running
    bot immediately replies from the NEW bot instead of a stale cached one.
    """
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    await _load_token_from_db()
    bot = get_telegram_bot()
    if bot is not None:
        bot.invalidate_token_cache()
    logger.info("🔄 Bot token reloaded from DB on admin request.")
    return {"ok": True, "token_set": bool(os.environ.get("TELEGRAM_BOT_TOKEN"))}
