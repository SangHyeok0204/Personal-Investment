"""증권사 평가손익이 제비용을 뺀 값이라는 사실.

여기서 지키는 것: **화면의 칸이 더해져야 한다**, 그리고 **모형값을 칸에 적지
않는다**(모형으로는 정확히 닫히지 않는다 — 실측 차이 137원).
"""

from decimal import Decimal

import pytest

from app.core import fee_reserve as fr


def test_reserve_closes_the_arithmetic():
    """매입 + 평가손익 + 제비용 = 평가금액. 이게 안 닫히면 화면이 고장 나 보인다."""
    mv, cost, pnl = Decimal("36407647"), Decimal("33352051.11"), Decimal("2881334")
    reserve = fr.reserve_krw(mv, cost, pnl)
    assert reserve == Decimal("174261.89")
    assert cost + pnl + reserve == mv


def test_model_explains_the_reserve():
    """모형 = 0.25% × (매입 + 평가). 실측 제비용과 0.1% 안에서 맞는다.

    ⚠️맞는다고 해서 모형값을 칸에 적으면 안 된다 — 137원 어긋나 합이 깨진다.
    """
    mv, cost = Decimal("36407647"), Decimal("33352051.11")
    model = fr.modelled_krw(mv, cost)
    assert model == Decimal("174399.25")
    measured = fr.reserve_krw(mv, cost, Decimal("2881334"))
    assert abs(model - measured) < abs(measured) * Decimal("0.01")


def test_missing_input_is_none_not_zero():
    """0 으로 두면 '제비용 없음'으로 읽힌다. 모르는 것은 모른다고 한다."""
    assert fr.reserve_krw(None, Decimal("1"), Decimal("1")) is None
    assert fr.reserve_krw(Decimal("1"), None, Decimal("1")) is None
    assert fr.reserve_krw(Decimal("1"), Decimal("1"), None) is None
    assert fr.modelled_krw(None, Decimal("1")) is None
    assert fr.modelled_krw(Decimal("1"), None) is None


def test_reserve_is_zero_when_broker_pnl_is_gross():
    """제비용을 안 빼는 증권사라면 잔차가 0 이다 — 그것도 정상이다."""
    mv, cost = Decimal("1100"), Decimal("1000")
    assert fr.reserve_krw(mv, cost, mv - cost) == Decimal("0.00")


def test_rate_comes_from_one_place():
    """0.25% 를 여기 다시 적지 않는다 — 두 군데 적으면 한쪽만 고치게 된다."""
    from app.core.rebalance import MEASURED_COST_RATE

    mv, cost = Decimal("1000"), Decimal("1000")
    assert fr.modelled_krw(mv, cost) == pytest.approx(
        MEASURED_COST_RATE * Decimal("2000"), abs=Decimal("0.01")
    )
