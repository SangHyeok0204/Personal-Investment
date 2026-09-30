"""계획 A3b — SEC 수집 주기 판정."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from app.core.sec_sync import due, in_13f_season, interval_for

UTC = timezone.utc


def test_13f_season_windows():
    assert not in_13f_season(date(2026, 10, 29))      # 9/30 +29일
    assert in_13f_season(date(2026, 10, 30))          # +30
    assert in_13f_season(date(2026, 11, 14))          # +45 마감
    assert in_13f_season(date(2026, 11, 19))          # +50
    assert not in_13f_season(date(2026, 11, 20))
    assert in_13f_season(date(2027, 2, 14))           # 12/31 +45 — 해를 넘긴다
    assert in_13f_season(date(2026, 5, 15))           # 3/31 +45
    assert not in_13f_season(date(2026, 9, 26))


def test_intervals():
    fri = datetime(2026, 9, 25, 15, tzinfo=UTC)       # 뉴욕 금 11시
    sat = datetime(2026, 9, 26, 15, tzinfo=UTC)
    assert interval_for("SEC_FORM4", fri) == timedelta(hours=1)
    assert interval_for("SEC_FORM4", sat) is None     # 주말엔 넣지 않는다
    assert interval_for("SEC_13DG", sat) == timedelta(hours=12)
    assert interval_for("SEC_13F", sat) == timedelta(days=7)
    assert interval_for("CUSIP_RESOLVE", sat) == timedelta(days=1)
    assert interval_for("SEC_13F", datetime(2026, 11, 14, 15, tzinfo=UTC)) == timedelta(days=1)


def test_due():
    now = datetime(2026, 9, 25, 15, tzinfo=UTC)
    job = lambda status, ago: SimpleNamespace(status=status, created_at=now - ago)  # noqa: E731
    assert due("SEC_FORM4", None, now)
    assert not due("SEC_FORM4", job("RUNNING", timedelta(hours=5)), now)       # 진행 중이면 안 넣는다
    assert not due("SEC_FORM4", job("SUCCEEDED", timedelta(minutes=30)), now)
    assert due("SEC_FORM4", job("SUCCEEDED", timedelta(minutes=56)), now)       # 5분 확인 주기 여유
    assert not due("SEC_13DG", job("FAILED", timedelta(hours=2)), now)          # 실패도 주기를 지킨다
    assert not due("SEC_FORM4", None, datetime(2026, 9, 26, 15, tzinfo=UTC))    # 주말


def test_earnings_calendar_daily_slot():
    from app.core.sec_sync import last_slot
    kst = lambda h, m=0, d=27: datetime(2026, 9, d, h - 9 if h >= 9 else h + 15, m, tzinfo=UTC) if h >= 9 else \
        datetime(2026, 9, d - 1, h + 15, m, tzinfo=UTC)  # noqa: E731
    at_8 = kst(8)                                    # 09-27 08:00 KST
    assert last_slot(at_8).astimezone(timezone(timedelta(hours=9))).strftime("%m-%d %H:%M") == "09-27 07:10"
    at_6 = kst(6)                                    # 07:10 전 → 어제 슬롯
    assert last_slot(at_6).astimezone(timezone(timedelta(hours=9))).strftime("%m-%d %H:%M") == "09-26 07:10"
    job = lambda status, t: SimpleNamespace(status=status, created_at=t)  # noqa: E731
    assert due("EARNINGS_CALENDAR", None, at_8)
    assert due("EARNINGS_CALENDAR", job("SUCCESS", kst(6)), at_8)          # 오늘 07:10 전에 돈 것 → 다시
    assert not due("EARNINGS_CALENDAR", job("SUCCESS", kst(7, 30)), at_8)  # 오늘 07:10 뒤에 돌았음
    assert not due("EARNINGS_CALENDAR", job("RUNNING", kst(6)), at_8)


def test_earnings_revenue_slot_after_calendar():
    from app.core.sec_sync import DAILY_SLOTS
    assert DAILY_SLOTS["EARNINGS_REVENUE"] > DAILY_SLOTS["EARNINGS_CALENDAR"]
    at = datetime(2026, 9, 27, 22, 15, tzinfo=UTC)          # 09-28 07:15 KST — 캘린더는 됐고 매출은 아직
    job = lambda t: SimpleNamespace(status="SUCCESS", created_at=t)  # noqa: E731
    yday = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    assert due("EARNINGS_CALENDAR", job(yday), at) and not due("EARNINGS_REVENUE", job(yday), at)


def test_result_ready_at():
    from app.core.sec_sync import result_ready_at
    ny = lambda dt: dt.astimezone(ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")  # noqa: E731
    assert ny(result_ready_at(date(2026, 8, 26), "AMC")) == "08-26 17:40"
    assert ny(result_ready_at(date(2026, 8, 26), "BMO")) == "08-26 08:40"
    assert ny(result_ready_at(date(2026, 8, 26), None)) == "08-27 09:00"
