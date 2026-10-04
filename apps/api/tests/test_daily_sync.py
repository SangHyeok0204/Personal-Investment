"""영업일 16:30(KST) 이력 동기화의 '밀렸나' 판정.

시각 계산만 본다 — 실제 동기화는 키움을 부르므로 여기서 돌리지 않는다.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.daily_sync import (
    effective_sync_at,
    in_batch_window,
    is_due,
    last_scheduled_run,
)

KST = ZoneInfo("Asia/Seoul")


def kst(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=KST)


# 2026-09-21(월) ~ 09-27(일). PREV_FRI 는 그 **앞** 주 금요일이다.
MON, TUE, FRI, SAT, SUN = 21, 22, 25, 26, 27
PREV_FRI = 18


def test_after_1630_on_a_weekday_points_at_today():
    assert last_scheduled_run(kst(2026, 9, TUE, 17, 0)) == kst(2026, 9, TUE, 16, 30)


def test_before_1630_points_at_the_previous_business_day():
    """오전에는 아직 오늘 치가 오지 않았다 — 어제 것이 기준이다."""
    assert last_scheduled_run(kst(2026, 9, TUE, 9, 0)) == kst(2026, 9, MON, 16, 30)


def test_weekend_falls_back_to_friday():
    """주말에는 새 체결이 없다. 토·일 어느 시각이든 금요일 16:30 이 기준이다."""
    assert last_scheduled_run(kst(2026, 9, SAT, 12, 0)) == kst(2026, 9, FRI, 16, 30)
    assert last_scheduled_run(kst(2026, 9, SUN, 23, 0)) == kst(2026, 9, FRI, 16, 30)


def test_monday_morning_still_points_at_friday():
    """⚠️월요일 오전에 '어제'로 가면 일요일이 된다 — 주말을 건너뛰어야 한다."""
    assert last_scheduled_run(kst(2026, 9, MON, 8, 0)) == kst(2026, 9, PREV_FRI, 16, 30)


def test_utc_input_is_converted_not_assumed():
    """⚠️서버는 UTC 로 산다. KST 로 바꾸지 않으면 9시간이 통째로 어긋난다.

    2026-09-22 08:00 UTC = 09-22 17:00 KST → 그날 16:30 이 이미 지났다.
    """
    now = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
    assert last_scheduled_run(now) == kst(2026, 9, TUE, 16, 30)


def test_never_synced_is_due():
    assert is_due(None, kst(2026, 9, TUE, 17, 0)) is True


def test_synced_after_the_mark_is_not_due():
    """수동으로 돌렸으면 자동은 다시 돌지 않는다."""
    assert is_due(kst(2026, 9, TUE, 16, 45), kst(2026, 9, TUE, 17, 0)) is False


def test_synced_before_the_mark_is_due():
    """어제 받아 둔 것만으로는 오늘 체결이 안 들어온다."""
    assert is_due(kst(2026, 9, MON, 18, 0), kst(2026, 9, TUE, 17, 0)) is True


def test_batch_window_is_avoided():
    """⚠️KST 05~07시에는 키움이 이력을 **에러 없이 빈 배열**로 준다.

    맥이 자다 깬 뒤의 따라잡기가 하필 이 시간일 수 있다 — 그때 돌리면
    '받았다'고 기록만 남고 내용은 빈다.
    """
    assert in_batch_window(kst(2026, 9, TUE, 6, 0)) is True
    assert in_batch_window(kst(2026, 9, TUE, 5, 0)) is True
    assert in_batch_window(kst(2026, 9, TUE, 7, 0)) is False
    assert in_batch_window(kst(2026, 9, TUE, 16, 30)) is False


def test_empty_history_run_stops_counting_after_retry_gap():
    # 2026-10-03 토 09:12 — 일별성과 0건으로 '성공'. 2시간 뒤엔 안 돈 것으로 본다.
    at = datetime(2026, 10, 3, 0, 12, tzinfo=timezone.utc)
    empty = {"daily_performance": 0}
    assert effective_sync_at(at, "SUCCESS", empty, now=datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)) == at
    assert effective_sync_at(at, "SUCCESS", empty, now=datetime(2026, 10, 3, 3, 0, tzinfo=timezone.utc)) is None


def test_full_or_failed_runs_keep_their_time():
    at = datetime(2026, 10, 2, 7, 31, tzinfo=timezone.utc)
    later = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)
    assert effective_sync_at(at, "SUCCESS", {"daily_performance": 541}, now=later) == at
    assert effective_sync_at(at, "FAILED", None, now=later) == at
