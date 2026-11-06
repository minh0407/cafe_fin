from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

BUSINESS_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def business_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, BUSINESS_ZONE)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)
