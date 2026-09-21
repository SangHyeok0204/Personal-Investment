"""편입 타임라인 복원 검증.

손으로 답을 낼 수 있는 작은 매매 이력만 쓴다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.position_timeline import (
    TradeRow,
    build_timeline,
    holding_periods,
    month_end_weights,
)


def buy(day: date, ticker: str, qty: str, amount: str) -> TradeRow:
    return TradeRow(day, ticker, "BUY", Decimal(qty), Decimal(amount))


def sell(day: date, ticker: str, qty: str, amount: str) -> TradeRow:
    return TradeRow(day, ticker, "SELL", Decimal(qty), Decimal(amount))


D = date


def test_first_buy_is_an_entry() -> None:
    events, _ = build_timeline([buy(D(2026, 1, 5), "AAA", "10", "1000")])
    assert [e.kind for e in events] == ["ENTRY"]
    assert events[0].weight_before is None
    assert events[0].weight_after == Decimal("1")
    assert events[0].holdings_after == 1


def test_second_buy_is_an_add_not_an_entry() -> None:
    events, _ = build_timeline(
        [buy(D(2026, 1, 5), "AAA", "10", "1000"), buy(D(2026, 2, 5), "AAA", "10", "1400")]
    )
    assert [e.kind for e in events] == ["ENTRY", "ADD"]


def test_partial_sell_is_a_trim_and_uses_average_cost() -> None:
    """10주를 1,000에 사고 5주를 팔면 원가는 절반(500)만 빠진다.

    매도대금(900)이 아니라 **평균단가**로 원가를 덜어낸다 — 대금으로 빼면
    원가가 음수가 되거나 남은 주식의 단가가 엉망이 된다.
    """
    events, history = build_timeline(
        [buy(D(2026, 1, 5), "AAA", "10", "1000"), sell(D(2026, 3, 5), "AAA", "5", "900")]
    )
    assert [e.kind for e in events] == ["ENTRY", "TRIM"]
    lot = history[D(2026, 3, 5)]["AAA"]
    assert lot.quantity == Decimal("5")
    assert lot.cost == Decimal("500")
    assert lot.avg_price == Decimal("100")


def test_selling_everything_is_an_exit() -> None:
    events, history = build_timeline(
        [buy(D(2026, 1, 5), "AAA", "10", "1000"), sell(D(2026, 3, 5), "AAA", "10", "1800")]
    )
    assert [e.kind for e in events] == ["ENTRY", "EXIT"]
    assert "AAA" not in history[D(2026, 3, 5)]
    assert events[-1].holdings_after == 0


def test_dust_quantity_still_counts_as_a_full_exit() -> None:
    """소수점 잔량이 남아 '청산'이 영영 안 찍히는 일이 없어야 한다."""
    events, _ = build_timeline(
        [
            buy(D(2026, 1, 5), "AAA", "10", "1000"),
            sell(D(2026, 3, 5), "AAA", "9.9999999", "1800"),
        ]
    )
    assert events[-1].kind == "EXIT"


def test_weights_are_cost_based_and_sum_to_one() -> None:
    events, history = build_timeline(
        [
            buy(D(2026, 1, 5), "AAA", "10", "1000"),
            buy(D(2026, 1, 6), "BBB", "10", "3000"),
        ]
    )
    # 이벤트의 weight_after 는 **그 순간**의 비중이다. AAA 를 샀을 때는
    # 아직 AAA 뿐이므로 100% 가 맞다.
    assert events[0].weight_after == Decimal("1")
    assert events[1].weight_after == Decimal("3000") / Decimal("4000")

    # 최종 상태에서 비중 합은 1 이다.
    lots = history[D(2026, 1, 6)]
    total = sum(l.cost for l in lots.values())
    assert total == Decimal("4000")
    assert lots["AAA"].cost / total == Decimal("1000") / Decimal("4000")


def test_same_day_trades_record_one_final_state() -> None:
    """같은 날 전량 매도 후 재매수 — 중간 상태가 비중으로 남으면 안 된다."""
    day = D(2026, 5, 4)
    _, history = build_timeline(
        [
            buy(D(2026, 1, 5), "AAA", "10", "1000"),
            sell(day, "AAA", "10", "1200"),
            buy(day, "AAA", "4", "500"),
        ]
    )
    lots = history[day]
    assert lots["AAA"].quantity == Decimal("4")
    assert lots["AAA"].cost == Decimal("500")


def test_sell_without_a_known_entry_does_not_invent_cost() -> None:
    """조회 기간 밖에서 산 종목의 매도. 원가를 지어내지 않는다."""
    events, history = build_timeline([sell(D(2026, 3, 5), "OLD", "10", "900")])
    assert [e.kind for e in events] == ["EXIT"]
    assert events[0].weight_before is None
    assert history[D(2026, 3, 5)] == {}


def test_month_end_weights_carry_quiet_months_forward() -> None:
    """1월에 사고 4월까지 거래가 없으면 2·3월에도 비중이 이어져야 한다."""
    _, history = build_timeline(
        [buy(D(2026, 1, 5), "AAA", "10", "1000"), buy(D(2026, 4, 5), "BBB", "10", "1000")]
    )
    points = month_end_weights(history)
    months = sorted({p.base_date for p in points})
    assert months == [D(2026, 1, 1), D(2026, 2, 1), D(2026, 3, 1), D(2026, 4, 1)]
    feb = [p for p in points if p.base_date == D(2026, 2, 1)]
    assert len(feb) == 1 and feb[0].ticker == "AAA" and feb[0].weight == Decimal("1")
    apr = {p.ticker: p.weight for p in points if p.base_date == D(2026, 4, 1)}
    assert apr == {"AAA": Decimal("0.5"), "BBB": Decimal("0.5")}


def test_holding_periods_mark_open_and_closed() -> None:
    events, _ = build_timeline(
        [
            buy(D(2026, 1, 5), "AAA", "10", "1000"),
            buy(D(2026, 1, 6), "BBB", "10", "1000"),
            sell(D(2026, 6, 6), "BBB", "10", "1200"),
        ]
    )
    periods = holding_periods(events)
    assert periods["AAA"] == (D(2026, 1, 5), None)
    assert periods["BBB"] == (D(2026, 1, 6), D(2026, 6, 6))


def test_reentry_keeps_the_first_entry_and_clears_the_exit() -> None:
    """팔았다가 다시 산 종목은 '지금 보유 중'이 더 중요한 사실이다."""
    events, _ = build_timeline(
        [
            buy(D(2026, 1, 5), "AAA", "10", "1000"),
            sell(D(2026, 3, 5), "AAA", "10", "1200"),
            buy(D(2026, 7, 5), "AAA", "4", "500"),
        ]
    )
    periods = holding_periods(events)
    assert periods["AAA"] == (D(2026, 1, 5), None)


def test_empty_input_is_safe() -> None:
    events, history = build_timeline([])
    assert events == [] and history == {}
    assert month_end_weights({}) == []
    assert holding_periods([]) == {}
