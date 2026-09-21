"""일별 시계열 → 기간 변화 계산 규칙 고정. 네트워크를 타지 않는다."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prices.history import Series, base_values, changes  # noqa: E402


def series(days: int = 400, start: str = "100") -> Series:
    """매일 +1 씩 오르는 시계열. 손으로 답을 낼 수 있다."""
    end = date(2026, 9, 21)
    dates = [end - timedelta(days=days - 1 - i) for i in range(days)]
    closes = [Decimal(start) + Decimal(i) for i in range(days)]
    return Series("AAA", dates, closes, "USD", closes[-1])


def test_close_on_or_before_uses_the_previous_trading_day() -> None:
    """그 날이 휴장이어도 직전 값을 쓴다."""
    s = Series(
        "AAA",
        [date(2026, 9, 18), date(2026, 9, 21)],
        [Decimal("10"), Decimal("12")],
        "USD",
        Decimal("12"),
    )
    assert s.close_on_or_before(date(2026, 9, 20)) == Decimal("10")
    assert s.close_on_or_before(date(2026, 9, 21)) == Decimal("12")


def test_asking_before_the_data_starts_gives_none() -> None:
    """1년치밖에 없는데 3년 전을 물으면 None 이다.

    ⚠️'없으면 첫 값'으로 떨어뜨리면 기간이 통째로 틀린 값이 조용히 나온다.
    """
    s = series(days=30)
    assert s.close_on_or_before(date(2020, 1, 1)) is None


def test_changes_are_absolute_not_ratios() -> None:
    """여기서는 나누지 않는다 — 금리는 퍼센트 수익률이 의미가 없어서,
    비율로 바꿀지 bp 로 바꿀지는 호출부가 정한다."""
    s = series()
    c = changes(s, today=date(2026, 9, 21))
    assert c["1D"] == Decimal("1")  # 하루 +1
    assert c["1W"] == Decimal("7")


def test_ytd_baseline_is_last_years_close() -> None:
    """YTD 기준은 **작년 마지막 종가**다. 올해 첫 거래일 종가가 아니다."""
    s = series(days=400)
    base = base_values(s, today=date(2026, 9, 21))
    # 2025-12-31 이하의 마지막 값이 기준이어야 한다.
    expected = s.close_on_or_before(date(2025, 12, 31))
    assert base["YTD"] == expected
    assert changes(s, today=date(2026, 9, 21))["YTD"] == s.latest - expected


def test_missing_period_is_none_not_zero() -> None:
    """데이터가 모자란 기간은 None. 0 으로 두면 '변동 없음'으로 보인다."""
    s = series(days=10)
    c = changes(s, today=date(2026, 9, 21))
    assert c["1Y"] is None
    assert c["1D"] == Decimal("1")


def test_single_point_series_has_no_changes() -> None:
    s = Series("AAA", [date(2026, 9, 21)], [Decimal("5")], "USD", Decimal("5"))
    c = changes(s, today=date(2026, 9, 21))
    assert c["1D"] is None
    assert c["1W"] is None
