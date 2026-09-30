"""계절성 C3 — Yahoo 월간 응답에서 '끝난 달'만 고른다."""
from datetime import datetime, timezone

from handlers.seasonality_append import completed_months


def _ts(y, m, d=1):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


def test_completed_months_drops_in_progress_null_and_keeps_last_duplicate():
    chart = {"chart": {"result": [{
        "timestamp": [_ts(2026, 7), _ts(2026, 8), _ts(2026, 8, 29), _ts(2026, 9), _ts(2026, 6)],
        "indicators": {"quote": [{"close": [100.0, 101.0, 102.0, 103.0, None]}]},
    }]}}
    now = datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)
    got = completed_months(chart, now)
    assert got == {"2026-07": 100.0, "2026-08": 102.0}   # 9월(진행 중) 제외 · 6월 빈 값 제외 · 8월은 마지막 값


def test_completed_months_empty_result():
    assert completed_months({"chart": {"result": None}}, datetime.now(timezone.utc)) == {}


def test_month_is_taken_in_exchange_timezone_for_asia():
    """코스피 9월 봉은 2026-08-31T15:00Z(= KST 9/1 00:00). UTC 로 보면 8월이 된다 — 한 달 밀림."""
    chart = {"chart": {"result": [{
        "meta": {"exchangeTimezoneName": "Asia/Seoul", "gmtoffset": 32400},
        "timestamp": [
            int(datetime(2026, 6, 30, 15, tzinfo=timezone.utc).timestamp()),   # 7월 봉
            int(datetime(2026, 7, 31, 15, tzinfo=timezone.utc).timestamp()),   # 8월 봉
            int(datetime(2026, 8, 31, 15, tzinfo=timezone.utc).timestamp()),   # 9월 봉(진행 중)
        ],
        "indicators": {"quote": [{"close": [6595.45, 6820.02, 7080.92]}]},
    }]}}
    got = completed_months(chart, datetime(2026, 9, 26, 3, tzinfo=timezone.utc))
    assert got == {"2026-07": 6595.45, "2026-08": 6820.02}


def test_gmtoffset_fallback_when_no_zone_name():
    chart = {"chart": {"result": [{
        "meta": {"gmtoffset": 28800},  # 홍콩 UTC+8
        "timestamp": [int(datetime(2026, 7, 31, 16, tzinfo=timezone.utc).timestamp())],
        "indicators": {"quote": [{"close": [25000.0]}]},
    }]}}
    assert completed_months(chart, datetime(2026, 9, 26, tzinfo=timezone.utc)) == {"2026-08": 25000.0}
