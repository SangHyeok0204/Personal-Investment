"""미국 주간거래(데이장) 세션 윈도우 판정.

레거시 batch.py(us_daytime_window 계열)의 검증된 로직을 라이브 컬렉터가
쓸 수 있게 분리. KST 낮 시간대(서머타임 09:00~17:00, 표준시 10:00~18:00)에
NAS/NYS/AMS 대신 BAQ/BAY/BAA(데이장) 시세를 조회하기 위한 윈도우.

미국 휴장일엔 데이장 세션이 없어 KIS가 낡은 값을 반복하므로, 공유 Holidays
엑셀(holiday_calendar)을 정본으로 휴장 여부를 가드하고, 엑셀에 해당 일자가
없으면 NYSE pandas 달력으로 폴백한다 (batch.py 와 동일).
"""

from __future__ import annotations

from datetime import date as dt_date, datetime, time as dt_time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from etf_inav.data_sources import holiday_calendar

KST = timezone(timedelta(hours=9))
US_EASTERN = ZoneInfo("America/New_York")

US_DAYTIME_EXCHANGE_MAP = {"NAS": "BAQ", "NYS": "BAY", "AMS": "BAA"}
US_DAYTIME_STANDARD_START_KST = dt_time(10, 0)
US_DAYTIME_DST_START_KST = dt_time(9, 0)
US_DAYTIME_STANDARD_END_KST = dt_time(18, 0)
US_DAYTIME_DST_END_KST = dt_time(17, 0)


def ensure_kst(value: datetime | None = None) -> datetime:
    current = value or datetime.now(KST)
    if current.tzinfo is None:
        return current.replace(tzinfo=KST)
    return current.astimezone(KST)


def is_us_dst(value: datetime | None = None) -> bool:
    return bool(ensure_kst(value).astimezone(US_EASTERN).dst())


_NYSE_CALENDAR = None


@lru_cache(maxsize=1024)
def _nyse_session_open(day: dt_date) -> bool:
    """True if NYSE has a regular session on ``day``. NYSE pandas calendar."""
    global _NYSE_CALENDAR
    if _NYSE_CALENDAR is None:
        import pandas_market_calendars as mcal

        _NYSE_CALENDAR = mcal.get_calendar("NYSE")
    return len(_NYSE_CALENDAR.valid_days(str(day), str(day))) > 0


def is_us_market_open(day: dt_date) -> bool:
    status = holiday_calendar.us_status(day)  # True=휴장, False=개장, None=데이터 없음
    if status is not None:
        return not status
    return _nyse_session_open(day)


def us_daytime_window(value: datetime | None = None) -> dict:
    current = ensure_kst(value)
    dst = is_us_dst(current)
    start = US_DAYTIME_DST_START_KST if dst else US_DAYTIME_STANDARD_START_KST
    end = US_DAYTIME_DST_END_KST if dst else US_DAYTIME_STANDARD_END_KST
    market_open = is_us_market_open(current.date())
    active = market_open and (start <= current.time() < end)
    return {
        "active": active,
        "market_open": market_open,
        "is_dst": dst,
        "kst_now": current,
        "start": start,
        "end": end,
    }
