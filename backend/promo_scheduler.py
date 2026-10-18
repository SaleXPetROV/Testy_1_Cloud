"""
APScheduler jobs for the Referral Rally promo.

- referral_rally_freeze_job: every minute, freezes campaigns whose ends_at
  has passed and broadcasts the finale.
- referral_rally_reminder_job: every 5 minutes; if the active campaign is
  approaching a reminder window (24h before end / 1h before end) AND the
  corresponding reminder has not been sent yet, broadcasts the reminder
  push (short leaderboard-style message with the live top-3, banner image
  attached) via `broadcast_rally_reminder`. Idempotent through the
  `reminders_sent.<stage>` flag persisted on the campaign document.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / '.env')

logger = logging.getLogger(__name__)

_mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
_db_name = os.environ.get('DB_NAME', 'test_database')


def _new_db():
    client = AsyncIOMotorClient(_mongo_url)
    return client, client[_db_name]


async def referral_rally_freeze_job():
    """Check every minute: if any active campaign's ends_at has passed (MSK),
    freeze it and broadcast the finale."""
    client, db = _new_db()
    try:
        from promo_service import get_active_campaign, to_msk, now_msk, freeze_campaign
        from promo_broadcast import broadcast_finished_rally

        campaign = await get_active_campaign(db)
        if not campaign:
            return

        ends_at = campaign.get("ends_at")
        if not ends_at:
            return

        try:
            ea = to_msk(ends_at)
        except Exception as e:
            logger.warning(f"promo freeze: bad ends_at {ends_at}: {e}")
            return

        if now_msk() >= ea:
            logger.info(f"⏰ Freezing referral rally {campaign['id']}")
            frozen = await freeze_campaign(db, campaign)
            try:
                await broadcast_finished_rally(db, frozen)
            except Exception as e:
                logger.warning(f"finale broadcast failed: {e}")
    except Exception as e:
        logger.error(f"referral_rally_freeze_job failed: {e}", exc_info=True)
    finally:
        client.close()


async def referral_rally_reminder_job():
    """Runs frequently (every 5 min). Fires two reminder broadcasts per
    campaign:

    • "day_before"  — when ends_at - now  ≤ 24h  (and > 60min)
    • "final_hour"  — when ends_at - now  ≤ 60min (and > 0)

    Each reminder is broadcast at most once per campaign (tracked via
    `reminders_sent.<stage>` on the campaign document). This delivers the
    biggest final-day/final-hour engagement bump for the leaderboard TOP-3
    without spamming users.
    """
    client, db = _new_db()
    try:
        from promo_service import get_active_campaign, to_msk, now_msk
        from promo_broadcast import broadcast_rally_reminder

        campaign = await get_active_campaign(db)
        if not campaign:
            return

        ends_at = campaign.get("ends_at")
        if not ends_at:
            return
        try:
            ea = to_msk(ends_at)
        except Exception as e:
            logger.warning(f"reminder job: bad ends_at {ends_at}: {e}")
            return

        remaining = ea - now_msk()
        remaining_seconds = remaining.total_seconds()
        if remaining_seconds <= 0:
            return

        sent = campaign.get("reminders_sent", {}) or {}

        # Final-hour reminder (0 < remaining ≤ 60min)
        if remaining_seconds <= 3600 and not sent.get("final_hour"):
            logger.info(f"⚡ Firing final-hour reminder for campaign {campaign['id']}")
            await broadcast_rally_reminder(db, campaign, is_final_hour=True)
            return

        # Day-before reminder (60min < remaining ≤ 24h)
        if remaining_seconds <= 86400 and not sent.get("day_before"):
            logger.info(f"⏰ Firing day-before reminder for campaign {campaign['id']}")
            await broadcast_rally_reminder(db, campaign, is_final_hour=False)
    except Exception as e:
        logger.error(f"referral_rally_reminder_job failed: {e}", exc_info=True)
    finally:
        client.close()


# Legacy job name kept for import compatibility; deprecated — do not use
# in new code. It now just delegates to the smart reminder job.
async def referral_rally_daily_notify_job():
    await referral_rally_reminder_job()
