import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional

APP_TIMEZONE = os.getenv('APP_TZ', 'America/Ciudad_Juarez')


def get_local_timezone():
    return ZoneInfo(APP_TIMEZONE)


def now_local() -> datetime:
    return datetime.now(get_local_timezone())


def utc_to_local(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_local_timezone())


def to_local_or_naive(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=get_local_timezone())
    return dt.astimezone(get_local_timezone())


def ensure_local_timezone(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=get_local_timezone())
    return dt.astimezone(get_local_timezone())


def format_local_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    if dt is None:
        return None
    local_dt = to_local_or_naive(dt)
    return local_dt.strftime(format_str)


def now() -> datetime:
    return now_local()


def localnow() -> datetime:
    return now_local()
