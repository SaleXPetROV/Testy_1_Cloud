"""ONE definition of the game day: Moscow time (UTC+3), the same everywhere —
daily reward, daily goals, leagues, City Pass, analytics, smart notifications."""
from datetime import date, datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))


def msk_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(MSK)


def msk_today() -> date:
    return msk_now().date()


def msk_today_str() -> str:
    return msk_today().isoformat()
