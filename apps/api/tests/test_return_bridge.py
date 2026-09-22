"""원화 증감 ↔ 주가 손익 다리.

여기서 지키는 것은 하나다 — **두 숫자가 어긋날 때 조용히 한쪽을 고르지 않는다.**
차이를 잔차로 꺼내 놓고, 못 잰 날은 0 이 아니라 세어서 알린다.
"""

from datetime import date
from decimal import Decimal

from app.core import return_bridge as rbr


def day(d: str, assets, pnl, dep="0", wd="0") -> rbr.Day:
    return rbr.Day(
        base_date=date.fromisoformat(d),
        assets_krw=None if assets is None else Decimal(assets),
        pnl_krw=None if pnl is None else Decimal(pnl),
        deposit_krw=Decimal(dep),
        withdrawal_krw=Decimal(wd),
    )


def test_bridge_closes():
    """주가 손익 + 잔차 = 원화 증감. 이 등식이 깨지면 화면이 거짓말을 한다."""
    days = [
        day("2026-06-04", "1000000", "-5000"),
        day("2026-06-05", "1100000", "100000"),
        day("2026-06-06", "1050000", "-50000"),
    ]
    b = rbr.build(days)
    assert b.price_pnl_krw == Decimal("50000.00")
    assert b.asset_change_krw == Decimal("50000.00")
    assert b.fx_effect_krw == Decimal("0.00")
    assert b.price_pnl_krw + b.fx_effect_krw == b.asset_change_krw


def test_first_day_is_a_baseline_not_a_flow():
    """첫날 손익과 첫날 입금은 세지 않는다 — 첫날 마감 자산에 이미 들어 있다."""
    days = [
        day("2026-06-04", "1000000", "-999999", dep="900000"),
        day("2026-06-05", "1010000", "10000"),
    ]
    b = rbr.build(days)
    assert b.price_pnl_krw == Decimal("10000.00")  # 첫날 -999,999 는 빠졌다
    assert b.asset_change_krw == Decimal("10000.00")  # 첫날 입금 900,000 도 빠졌다


def test_deposit_does_not_become_profit():
    """구간 중 입금은 수익이 아니다. 자산은 늘지만 증감에는 들어가지 않는다."""
    days = [
        day("2026-06-04", "1000000", "0"),
        day("2026-06-05", "2000000", "0", dep="1000000"),
    ]
    b = rbr.build(days)
    assert b.asset_change_krw == Decimal("0.00")
    assert b.price_pnl_krw == Decimal("0.00")


def test_fx_shows_up_as_the_residual():
    """환율이 빠진 구간의 모습 — 주가로는 벌었는데 원화 자산은 줄었다.

    실측한 상황을 줄여 놓은 것이다(2026-06-04~09-21: 주가 +2,480,825,
    원화 -722,749, 잔차 -3,203,574).
    """
    days = [
        day("2026-06-04", "10000000", "0"),
        day("2026-09-21", "9000000", "2000000"),
    ]
    b = rbr.build(days)
    assert b.price_pnl_krw == Decimal("2000000.00")
    assert b.asset_change_krw == Decimal("-1000000.00")
    assert b.fx_effect_krw == Decimal("-3000000.00")


def test_twr_chains_daily_returns():
    """연쇄 수익률은 전일 자산을 분모로 쓴다. 입금이 있는 날도 왜곡되지 않는다."""
    days = [
        day("2026-06-04", "1000000", "0"),
        day("2026-06-05", "1100000", "100000"),          # +10%
        day("2026-06-06", "2310000", "110000", dep="1100000"),  # +10% (입금 제외)
    ]
    b = rbr.build(days)
    assert b.twr_days == 2
    # 1.10 × 1.10 − 1 = 0.21. 입금 1,100,000 이 분모로 들어갔다면 값이 달라진다.
    assert b.twr == Decimal("0.210000")


def test_missing_pnl_is_counted_not_zeroed():
    """손익 칸이 비면 0 으로 치지 않는다. 0 은 '변동 없음'이라는 **주장**이다."""
    days = [
        day("2026-06-04", "1000000", "0"),
        day("2026-06-05", "1100000", None),
        day("2026-06-06", "1200000", "100000"),
    ]
    b = rbr.build(days)
    assert b.missing_pnl_days == 1
    assert b.unmeasured_days == 1          # 그날은 수익률도 못 낸다
    assert b.twr_days == 1
    assert b.price_pnl_krw == Decimal("100000.00")


def test_zero_base_is_unmeasured_not_infinite():
    """전일 자산이 0 이면 나눌 수 없다. 건너뛰고 센다 — 터뜨리지 않는다."""
    days = [
        day("2026-06-04", "0", "0"),
        day("2026-06-05", "50000", "50000"),
    ]
    b = rbr.build(days)
    assert b.unmeasured_days == 1
    assert b.twr is None


def test_too_short_a_window_measures_nothing():
    """하루짜리 구간에는 잴 변화가 없다. 0 이 아니라 None 이다."""
    assert rbr.build([]).price_pnl_krw is None
    assert rbr.build([day("2026-06-04", "1000000", "1234")]).twr is None
