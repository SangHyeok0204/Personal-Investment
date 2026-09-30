"""매크로 월간 이력 — 월말 다운샘플 · yoy/mom_diff · 침체 구간 (순수 함수, 네트워크 없음)."""
from datetime import date, timedelta
from decimal import Decimal

from app.api.market import _macro_monthly, _recession_ranges
from prices.fred import MacroSeries


def _monthly(start_year: int, values: list[float]) -> MacroSeries:
    dates = [date(start_year + i // 12, i % 12 + 1, 1) for i in range(len(values))]
    return MacroSeries("X", dates, [Decimal(str(v)) for v in values])


def test_daily_input_is_downsampled_to_month_end():
    start = date(2024, 1, 1)
    dates = [start + timedelta(days=i) for i in range(60)]  # 1월 1일 ~ 2월 29일
    values = [Decimal(i) for i in range(60)]
    points = _macro_monthly(MacroSeries("DGS10", dates, values), "level")
    # 한 달에 한 점, 그 달의 **마지막** 관측치.
    assert points == [("2024-01", 30.0), ("2024-02", 59.0)]


def test_yoy_uses_exact_twelve_months_back():
    # 100 → 매달 +1. 첫 12개월은 전년 값이 없어 버린다.
    series = _monthly(2020, [100 + i for i in range(25)])
    points = _macro_monthly(series, "yoy")
    assert points[0][0] == "2021-01"
    assert len(points) == 13
    assert points[0][1] == round((112 - 100) / 100, 6)
    assert points[-1] == ("2022-01", round((124 - 112) / 112, 6))


def test_mom_diff_and_gap_is_dropped_not_filled():
    series = MacroSeries(
        "PAYEMS",
        [date(2024, 11, 1), date(2024, 12, 1), date(2025, 1, 1), date(2025, 3, 1)],
        [Decimal(100), Decimal(110), Decimal(105), Decimal(120)],
    )
    points = _macro_monthly(series, "mom_diff")
    # 연 경계(12→1)를 넘는 전월을 찾고, 2월이 비면 3월은 내지 않는다.
    assert points == [("2024-12", 10.0), ("2025-01", -5.0)]


def test_recession_ranges():
    pts = [("2020-01", 0), ("2020-02", 0), ("2020-03", 1), ("2020-04", 1), ("2020-05", 0), ("2020-06", 1)]
    assert _recession_ranges(pts) == [("2020-03", "2020-04"), ("2020-06", "2020-06")]
