"""FRED CSV 파싱 + 변환 규칙 고정. 네트워크를 타지 않는다."""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prices.fred import MacroSeries, _parse  # noqa: E402

CSV = """observation_date,CPIAUCSL
2025-08-01,320.000
2025-09-01,.
2025-10-01,322.000
2026-08-01,336.000
"""


def test_parses_dates_and_values() -> None:
    s = _parse(CSV, "CPIAUCSL")
    assert s.dates == [date(2025, 8, 1), date(2025, 10, 1), date(2026, 8, 1)]
    assert s.values[0] == Decimal("320.000")


def test_missing_marker_row_is_dropped_not_zeroed() -> None:
    """⚠️결측은 `.` 로 온다. 0 으로 채우면 폭락처럼 보인다."""
    s = _parse(CSV, "CPIAUCSL")
    assert Decimal("0") not in s.values
    assert len(s.values) == 3


def test_blank_value_is_dropped() -> None:
    s = _parse("observation_date,X\n2026-01-01,\n2026-02-01,5\n", "X")
    assert s.dates == [date(2026, 2, 1)]


def test_header_only_gives_empty_series() -> None:
    s = _parse("observation_date,X\n", "X")
    assert s.dates == [] and s.latest is None


def test_value_on_or_before_uses_previous_observation() -> None:
    s = _parse(CSV, "CPIAUCSL")
    # 2025-09-01 은 결측이라 8월 값이 나와야 한다.
    assert s.value_on_or_before(date(2025, 9, 15)) == Decimal("320.000")


def test_asking_before_the_series_starts_gives_none() -> None:
    """'없으면 첫 값'으로 떨어뜨리면 기간이 틀린 값이 조용히 나온다."""
    s = _parse(CSV, "CPIAUCSL")
    assert s.value_on_or_before(date(2000, 1, 1)) is None


def test_yoy_is_a_ratio_not_a_difference() -> None:
    """CPI 336 은 아무 의미가 없고 '전년 대비 +5%' 가 의미다."""
    s = _parse(CSV, "CPIAUCSL")
    yoy = s.yoy()
    assert yoy is not None
    # 2026-08 의 336 vs 2025-08 의 320 → +5%
    assert yoy == Decimal("16") / Decimal("320")


def test_yoy_none_when_a_year_of_history_is_missing() -> None:
    s = _parse("observation_date,X\n2026-08-01,100\n", "X")
    assert s.yoy() is None


def test_mom_diff_uses_25_days_not_30() -> None:
    """⚠️월간 시리즈는 매월 1일에 찍힌다. 30일 전은 같은 달로 떨어질 수 있다."""
    s = _parse(
        "observation_date,PAYEMS\n2026-07-01,158000\n2026-08-01,158150\n", "PAYEMS"
    )
    assert s.mom_diff() == Decimal("150")


def test_mom_diff_none_when_unchanged() -> None:
    s = _parse("observation_date,X\n2026-08-01,100\n", "X")
    assert s.mom_diff() is None
