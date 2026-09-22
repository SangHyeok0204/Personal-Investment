"""리밸런싱 계산.

여기서 지키려는 것: **사용자가 시킨 적 없는 매매를 제안하지 않는다.**
"""
from decimal import Decimal as D

from app.core.rebalance import BUY, HOLD, SELL, Position, Target, build_plan


def _pos(ticker, qty, value, name=None):
    return Position(ticker=ticker, name=name, quantity=D(qty), market_value_krw=D(value))


def _tgt(ticker, weight, name=None):
    return Target(ticker=ticker, name=name, weight=D(weight))


BASE = [
    _pos("SOXL", "39", "7856237"),
    _pos("SCHD", "114", "5290668"),
    _pos("MSFT", "5", "3450648"),
]


def test_shares_round_toward_zero_so_we_never_overshoot():
    """⚠️반올림하면 목표를 **넘겨** 사거나 넘겨 판다.

    실측 SOXL: 필요 −26.64주 → −26 주(−27 이 아니다).
    """
    plan = build_plan(BASE, [_tgt("SOXL", "0.15")], band=D("0.01"))
    line = plan.lines[0]
    assert line.action == SELL
    assert line.delta_shares == -26
    # 주수로 못 맞춘 나머지는 버리지 않고 적어 둔다.
    assert line.residual_krw is not None and line.residual_krw < 0


def test_small_drift_inside_the_band_is_not_traded():
    """비용이 교정 효과보다 큰 거래를 제안하지 않는다(실측 거래비용률 0.250%)."""
    # MSFT 는 20.79% vs 목표 20% → 0.79%p, 밴드 1%p 안이다.
    plan = build_plan(BASE, [_tgt("MSFT", "0.20")], band=D("0.01"))
    line = plan.lines[0]
    assert line.within_band is True
    assert line.action == HOLD
    assert line.delta_shares == 0
    assert line.est_cost_krw == D("0.00")


def test_band_zero_trades_everything():
    """밴드를 0 으로 두면 작은 차이도 거래한다 — 사용자가 고를 수 있어야 한다."""
    plan = build_plan(BASE, [_tgt("MSFT", "0.20")], band=D("0"))
    assert plan.lines[0].within_band is False


def test_untargeted_holdings_are_not_treated_as_zero_percent():
    """⚠️목표가 없는 것과 0% 는 다르다.

    0% 로 치면 "아직 목표를 안 적은 종목을 전부 팔아라"가 되는데, 사용자가
    시킨 적 없는 말이다.
    """
    plan = build_plan(BASE, [_tgt("SOXL", "0.15")], band=D("0.01"))
    assert [l.ticker for l in plan.untargeted] == ["SCHD", "MSFT"]
    for line in plan.untargeted:
        assert line.delta_shares is None
        assert line.action == HOLD


def test_target_sum_is_reported_not_normalized():
    """합이 100% 가 아니어도 **정규화하지 않는다.** 조용히 고치면 사용자가
    적은 목표와 화면이 쓰는 목표가 달라진다."""
    plan = build_plan(BASE, [_tgt("SOXL", "0.15"), _tgt("SCHD", "0.30")], band=D("0.01"))
    assert plan.target_sum == D("0.45")
    assert plan.target_gap == D("0.55")
    # 목표를 그대로 쓴다 — 0.15/0.45 로 늘려 잡지 않는다.
    assert plan.lines[0].target_weight == D("0.15")


def test_price_comes_from_value_over_quantity_not_a_second_fx_multiply():
    """⚠️평가액이 이미 원화 환산이다. 환율을 다시 곱하면 두 번 곱하게 된다."""
    plan = build_plan([_pos("X", "10", "1000000")], [_tgt("X", "1.0")], band=D("0"))
    assert plan.lines[0].price_krw == D("100000")


def test_a_target_on_something_not_held_is_a_new_buy():
    """아직 사지 않은 종목에도 목표를 둘 수 있어야 한다(신규 편입 계획)."""
    plan = build_plan(BASE, [_tgt("NVDA", "0.10")], band=D("0.01"))
    line = plan.lines[0]
    assert line.current_value_krw == D("0")
    assert line.current_weight == D("0")
    # ⚠️가격을 모르므로 **주수를 지어내지 않는다.**
    assert line.price_krw is None
    assert line.delta_shares is None
    assert line.delta_value_krw is not None and line.delta_value_krw > 0


def test_empty_portfolio_does_not_divide_by_zero():
    plan = build_plan([], [_tgt("SOXL", "0.15")], band=D("0.01"))
    assert plan.base_value_krw == D("0")
    assert plan.lines[0].current_weight is None
    assert plan.lines[0].delta_shares is None


def test_totals_only_count_actual_trades():
    plan = build_plan(
        BASE,
        [_tgt("SOXL", "0.15"), _tgt("SCHD", "0.30"), _tgt("MSFT", "0.20")],
        band=D("0.01"),
    )
    # SOXL·SCHD 는 거래, MSFT 는 밴드 안 → 2건
    assert plan.trade_count == 2
    assert plan.sell_krw > 0
    assert plan.buy_krw == D("0.00")
    assert plan.est_cost_krw > 0
