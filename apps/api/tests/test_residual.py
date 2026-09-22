"""'그 외' 분해.

지키는 것: **추정과 실측을 섞지 않는다**, **못 잰 것을 0 으로 치지 않는다**,
그리고 **남는 것을 숨기지 않는다**.
"""

from datetime import date
from decimal import Decimal

from app.core import residual as rs


def day(d, assets, stock, pnl, dep="0", wd="0", div="0", fee="0") -> rs.Day:
    return rs.Day(
        base_date=date.fromisoformat(d),
        assets_krw=None if assets is None else Decimal(assets),
        stock_value_krw=None if stock is None else Decimal(stock),
        pnl_krw=None if pnl is None else Decimal(pnl),
        deposit_krw=Decimal(dep),
        withdrawal_krw=Decimal(wd),
        dividend_krw=Decimal(div),
        commission_tax_krw=Decimal(fee),
    )


def flat(_: date) -> Decimal:
    return Decimal("1000")


def test_no_fx_move_leaves_dividend_and_cost():
    """환율이 그대로면 '그 외'는 배당 − 수수료다."""
    days = [
        day("2026-06-04", "1000000", "900000", "0"),
        day("2026-06-05", "1004000", "900000", "0", div="5000", fee="1000"),
    ]
    r = rs.decompose(days, flat)
    assert r.total_krw == Decimal("4000.00")
    assert r.fx_estimate_krw == Decimal("0.00")
    assert r.dividend_krw == Decimal("5000.00")
    assert r.cost_krw == Decimal("1000.00")
    assert r.leftover_krw == Decimal("0.00")


def test_fx_move_explains_the_gap():
    """환율이 10% 오르면 주식평가액의 10% 만큼 '그 외'가 생긴다."""
    rates = {date(2026, 6, 4): Decimal("1000"), date(2026, 6, 5): Decimal("1100")}
    days = [
        day("2026-06-04", "1000000", "900000", "0"),
        day("2026-06-05", "1090000", "990000", "0"),
    ]
    r = rs.decompose(days, rates.get)
    assert r.total_krw == Decimal("90000.00")
    assert r.fx_estimate_krw == Decimal("90000.00")  # 900,000 × 10%
    assert r.leftover_krw == Decimal("0.00")


def test_leftover_is_reported_not_swallowed():
    """설명되지 않는 부분은 그대로 내놓는다. 맞춰 놓으면 틀린 걸 모르게 된다."""
    days = [
        day("2026-06-04", "1000000", "900000", "0"),
        day("2026-06-05", "1050000", "900000", "0"),
    ]
    r = rs.decompose(days, flat)
    assert r.fx_estimate_krw == Decimal("0.00")
    assert r.leftover_krw == Decimal("50000.00")


def test_first_day_is_a_baseline():
    """첫날의 배당·수수료·입금은 세지 않는다 — 첫날 마감 자산에 이미 있다."""
    days = [
        day("2026-06-04", "1000000", "900000", "9999", dep="500000", div="7777", fee="3"),
        day("2026-06-05", "1000000", "900000", "0"),
    ]
    r = rs.decompose(days, flat)
    assert r.total_krw == Decimal("0.00")
    assert r.dividend_krw == Decimal("0.00")
    assert r.cost_krw == Decimal("0.00")


def test_missing_rate_is_counted_not_zeroed():
    """환율을 못 읽은 날은 '변동 없음'이 아니다. 세어서 알린다."""
    rates = {date(2026, 6, 4): Decimal("1000")}
    days = [
        day("2026-06-04", "1000000", "900000", "0"),
        day("2026-06-05", "1000000", "900000", "0"),
    ]
    r = rs.decompose(days, rates.get)
    assert r.fx_missing_days == 1
    assert r.fx_days == 0
    assert r.fx_estimate_krw is None
    assert r.leftover_krw is None  # 환율을 모르면 남는 것도 못 센다


def test_deposit_is_not_part_of_the_residual():
    """입금은 '그 외'가 아니다. 순납입으로 따로 빠진다."""
    days = [
        day("2026-06-04", "1000000", "900000", "0"),
        day("2026-06-05", "1500000", "900000", "0", dep="500000"),
    ]
    r = rs.decompose(days, flat)
    assert r.total_krw == Decimal("0.00")


def test_too_short_a_window_measures_nothing():
    assert rs.decompose([], flat).total_krw is None
    assert rs.decompose([day("2026-06-04", "1", "1", "0")], flat).leftover_krw is None
