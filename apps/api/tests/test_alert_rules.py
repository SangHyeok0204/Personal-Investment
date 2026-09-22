"""알림 규칙 판정.

여기서 지키려는 것은 하나다 — **잴 수 없는데 "괜찮다"고 말하지 않는다.**
상태가 셋이다: 충족 / 미충족 / **판정 불가**.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.core.alert_rules import (
    OK,
    TRIGGERED,
    UNKNOWN,
    Facts,
    evaluate,
    unfilled_orders,
)

D = Decimal


# ── 판정 불가가 '미충족'으로 새지 않는다 ────────────────────────────────────

@pytest.mark.parametrize(
    "kind,threshold,facts,why",
    [
        ("PRICE_ABOVE", D("200"), Facts(price=None), "시세 결측"),
        ("PRICE_BELOW", D("200"), Facts(price=None), "시세 결측"),
        # ⚠️전일 종가가 없으면 등락률이 없다. 0% 로 두면 "조용하다"는 거짓이 된다.
        ("DAY_MOVE_ABS", D("0.05"), Facts(change_rate=None), "전일 종가 없음"),
        ("NEAR_52W_HIGH", D("0.05"), Facts(price=D("10"), week52_high=None), "52주 고가 없음"),
        ("NEAR_52W_LOW", D("0.05"), Facts(price=D("10"), week52_low=None), "52주 저가 없음"),
        # ⚠️보유하지 않은 종목의 평가손익은 **없는 것**이지 0 이 아니다.
        ("PNL_RATE_BELOW", D("-0.1"), Facts(held=False), "미보유"),
        ("WEIGHT_ABOVE", D("0.2"), Facts(held=False), "미보유"),
        ("ORDER_UNFILLED", D("7"), Facts(order_total=None), "주문 내역 없음"),
    ],
)
def test_unmeasurable_is_unknown_not_ok(kind, threshold, facts, why):
    assert evaluate(kind, threshold, facts).state == UNKNOWN, why


def test_missing_threshold_does_not_default_to_zero():
    """⚠️기준값을 0 으로 채우면 모든 가격이 조건을 만족해 알림이 늘 켜진다."""
    assert evaluate("PRICE_ABOVE", None, Facts(price=D("1"))).state == UNKNOWN


def test_unknown_kind_is_unknown_not_ok():
    assert evaluate("NOPE", D("1"), Facts(price=D("1"))).state == UNKNOWN


# ── 실제 판정 ───────────────────────────────────────────────────────────────

def test_price_thresholds_are_inclusive_at_the_boundary():
    """기준가에 **정확히** 닿아도 도달이다 — 목표가 알림의 요점이 그것이다."""
    assert evaluate("PRICE_ABOVE", D("200"), Facts(price=D("200"))).state == TRIGGERED
    assert evaluate("PRICE_BELOW", D("200"), Facts(price=D("200"))).state == TRIGGERED
    assert evaluate("PRICE_ABOVE", D("200"), Facts(price=D("199.99"))).state == OK


def test_day_move_uses_absolute_value():
    """급등락은 **양쪽 다** 봐야 한다. 하락만 놓치면 알림의 뜻이 없다."""
    assert evaluate("DAY_MOVE_ABS", D("0.05"), Facts(change_rate=D("-0.08"))).state == TRIGGERED
    assert evaluate("DAY_MOVE_ABS", D("0.05"), Facts(change_rate=D("0.08"))).state == TRIGGERED
    assert evaluate("DAY_MOVE_ABS", D("0.05"), Facts(change_rate=D("-0.01"))).state == OK


def test_52w_proximity_is_a_gap_not_a_level():
    """실측 SOXL: 현재가 141.93, 52주 최고 302 → 53% 아래라 근접이 아니다."""
    near = evaluate("NEAR_52W_HIGH", D("0.05"), Facts(price=D("295"), week52_high=D("302")))
    far = evaluate("NEAR_52W_HIGH", D("0.05"), Facts(price=D("141.93"), week52_high=D("302")))
    assert near.state == TRIGGERED
    assert far.state == OK


def test_weight_uses_strict_greater_than():
    """'초과'는 초과다 — 정확히 20%면 아직 넘지 않았다."""
    assert evaluate("WEIGHT_ABOVE", D("0.2"), Facts(held=True, weight=D("0.2"))).state == OK
    assert evaluate("WEIGHT_ABOVE", D("0.2"), Facts(held=True, weight=D("0.2132"))).state == TRIGGERED


def test_held_but_unconvertible_is_unknown():
    """보유는 하는데 원가를 환산 못 하면 **손익률이 없는 것**이다."""
    assert evaluate("PNL_RATE_BELOW", D("-0.1"), Facts(held=True, pnl_rate=None)).state == UNKNOWN


# ── 미체결 ──────────────────────────────────────────────────────────────────

@dataclass
class FakeOrder:
    order_date: date
    order_quantity: Decimal
    filled_quantity: Decimal
    cancelled_quantity: Decimal = Decimal("0")


TODAY = date(2026, 9, 22)


def test_unfilled_counts_only_inside_the_window():
    """⚠️처음엔 '며칠째 방치'로 짰는데 **그런 상태가 없었다** — 주문 145건이 전부
    잔량 0 이다. 체결 안 된 지정가는 장 마감에 소멸한다. 그대로 뒀다면
    "55건이 477일째 미체결"이라는 영원히 켜진 알림이 됐다."""
    orders = [
        FakeOrder(date(2026, 9, 20), D("10"), D("0")),   # 창 안 · 미체결
        FakeOrder(date(2026, 9, 18), D("10"), D("10")),  # 창 안 · 체결
        FakeOrder(date(2025, 6, 2), D("22"), D("0")),    # 1년 전 — 세지 않는다
    ]
    total, unfilled = unfilled_orders(orders, 7, TODAY)
    assert (total, unfilled) == (2, 1)


def test_cancelled_orders_are_not_unfilled():
    """스스로 취소한 것은 알릴 일이 아니다 — 세면 알림이 늘 켜져 있게 된다."""
    orders = [FakeOrder(date(2026, 9, 20), D("10"), D("0"), D("10"))]
    assert unfilled_orders(orders, 7, TODAY) == (0, 0)


def test_empty_window_is_unknown_not_ok():
    """주문이 없는 것과 전부 체결된 것은 다르다."""
    assert evaluate("ORDER_UNFILLED", D("7"), Facts(order_total=0)).state == UNKNOWN
    assert evaluate("ORDER_UNFILLED", D("7"), Facts(order_total=5, order_unfilled=0)).state == OK
    assert evaluate("ORDER_UNFILLED", D("7"), Facts(order_total=5, order_unfilled=2)).state == TRIGGERED
