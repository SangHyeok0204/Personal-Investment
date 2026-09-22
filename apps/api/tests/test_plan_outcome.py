"""계획 대비 결과.

여기서 지키려는 것: **안 한 것과 못 한 것을 구분한다.**
"""
from datetime import date
from decimal import Decimal as D

from app.core.plan_outcome import Fill, OrderAttempt, evaluate

DAY = date(2026, 9, 18)


def _ev(**kw):
    base = dict(
        planned_side="SELL", planned_quantity=D("11"), planned_price_krw=D("201442"),
        entry_date=DAY, fills=[], orders=[], fx_rate=D("1375.5"),
    )
    base.update(kw)
    return evaluate(**base)


def test_no_order_is_not_the_same_as_unfilled():
    """⚠️계획 11주 중 0주 체결일 때, **주문을 안 낸 것**과 **주문은 냈는데 안
    걸린 것**은 완전히 다른 복기다. 같은 '0주'로 적으면 구분이 사라진다."""
    never = _ev()
    assert never.filled_quantity == D("0") and never.no_order is True
    assert never.unfilled_quantity == D("0")

    tried = _ev(orders=[OrderAttempt(DAY, "SELL", D("11"), D("0"), D("0"))])
    assert tried.filled_quantity == D("0") and tried.no_order is False
    assert tried.unfilled_quantity == D("11")


def test_slippage_sign_flips_with_direction():
    """⚠️매수는 비싸게 샀을 때, 매도는 싸게 팔았을 때가 손해다.

    같은 부호로 두면 매도 복기가 통째로 반대가 된다.
    """
    # 계획 201,442원 = 146.45달러(환율 1375.5). 140달러에 매도 → 싸게 팔았으니 손해.
    sell = _ev(fills=[Fill(DAY, "SELL", D("11"), D("140"))])
    assert sell.slippage_rate is not None and sell.slippage_rate > 0

    # 같은 값을 매수로 보면 싸게 샀으니 이득.
    buy = _ev(planned_side="BUY", fills=[Fill(DAY, "BUY", D("11"), D("140"))])
    assert buy.slippage_rate is not None and buy.slippage_rate < 0


def test_slippage_is_not_computed_without_an_fx_rate():
    """⚠️계획은 원화, 체결가는 현지통화다. 환율 없이 비교하면 4자리 차이 나는
    숫자를 나란히 놓고 '1,300% 불리'라고 말하게 된다."""
    out = _ev(fills=[Fill(DAY, "SELL", D("11"), D("140"))], fx_rate=None)
    assert out.slippage_rate is None
    # 체결 자체는 그대로 센다.
    assert out.filled_quantity == D("11")


def test_only_the_same_side_counts():
    """같은 날 반대 방향 체결이 있어도 계획과 섞지 않는다."""
    out = _ev(fills=[Fill(DAY, "BUY", D("5"), D("150"))])
    assert out.filled_quantity == D("0")


def test_window_excludes_far_away_fills():
    out = _ev(fills=[Fill(date(2026, 9, 30), "SELL", D("11"), D("140"))])
    assert out.filled_quantity == D("0")


def test_partial_fill_reports_a_rate():
    out = _ev(
        fills=[Fill(DAY, "SELL", D("8"), D("146"))],
        orders=[OrderAttempt(DAY, "SELL", D("11"), D("8"), D("0"))],
    )
    assert out.fill_rate == (D("8") / D("11")).quantize(D("0.000001"))
    assert out.unfilled_quantity == D("3")


def test_cancelled_is_not_counted_as_unfilled():
    """스스로 취소한 것은 '못 한 것'이 아니다."""
    out = _ev(orders=[OrderAttempt(DAY, "SELL", D("11"), D("0"), D("11"))])
    assert out.cancelled_quantity == D("11")
    assert out.unfilled_quantity == D("0")


def test_average_price_ignores_fills_without_a_price():
    """가격 없는 체결로 평균을 흐리지 않는다 — 수량은 세되 평균에서는 뺀다."""
    out = _ev(
        fills=[Fill(DAY, "SELL", D("5"), D("146")), Fill(DAY, "SELL", D("6"), None)]
    )
    assert out.filled_quantity == D("11")
    assert out.avg_fill_price == D("146.0000")


def test_the_two_ledgers_can_disagree_and_we_say_so():
    """⚠️실측(SKHY 2026-09-18): 주문 원장은 2주 체결이라는데 체결 원장에는
    매도 행이 **아예 없다**(증권사 피드 누락). 체결만 보고 "0주"라고 적으면
    화면이 거짓말을 한다."""
    out = _ev(
        planned_quantity=D("8"),
        fills=[],  # 체결 원장이 비어 있다
        orders=[
            OrderAttempt(DAY, "SELL", D("2"), D("2"), D("0")),
            OrderAttempt(DAY, "SELL", D("2"), D("0"), D("0")),
            OrderAttempt(DAY, "SELL", D("2"), D("0"), D("0")),
            OrderAttempt(DAY, "SELL", D("2"), D("0"), D("0")),
        ],
    )
    assert out.filled_quantity == D("0")
    assert out.order_filled_quantity == D("2")
    assert out.sources_disagree is True
    assert out.unfilled_quantity == D("6")


def test_agreeing_ledgers_do_not_raise_a_flag():
    out = _ev(
        planned_quantity=D("2"),
        fills=[Fill(DAY, "SELL", D("2"), D("146"))],
        orders=[OrderAttempt(DAY, "SELL", D("2"), D("2"), D("0"))],
    )
    assert out.sources_disagree is False
