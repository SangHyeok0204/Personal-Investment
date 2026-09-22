"""계획 대비 결과 — 적어 둔 계획이 실제로 어떻게 됐나.

★리밸런싱이 "SOXL 11주 매도"를 내면 매매일지에 **구조로** 남는다. 며칠 뒤
  이 모듈이 그 계획을 실제 체결·주문과 대조한다.

⚠️**체결과 주문은 다른 것을 말한다.**
    체결(trades) — 성사된 것만. "몇 주가 실제로 오갔나."
    주문(orders) — 하려고 한 것 전부. "몇 주를 걸었고 몇 주가 안 걸렸나."
  둘 중 하나만 보면 틀린다. 계획 11주 중 0주가 체결됐을 때, 주문을 안 낸 것과
  주문은 냈는데 안 걸린 것은 **완전히 다른 복기**다.

⚠️두 원장이 **서로 다른 말을 할 때가 있다.** 실측(SKHY 2026-09-18): 주문 원장은
  2주 체결이라는데 체결 원장에는 매도 행이 아예 없다(증권사 피드 누락). 한쪽만
  보고 숫자를 내면 화면이 거짓말을 한다 — 둘 다 싣고 갈리면 그 사실을 알린다.

⚠️슬리피지의 부호는 **방향에 따라 뒤집힌다.** 매수는 싸게 사야 이득이고 매도는
  비싸게 팔아야 이득이다. 같은 부호로 두면 매도 복기가 통째로 반대가 된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

_RATIO = Decimal("0.000001")
_MONEY = Decimal("0.01")


@dataclass(frozen=True)
class Fill:
    trade_date: date
    side: str
    quantity: Decimal | None
    #: 체결 단가(현지통화).
    price: Decimal | None


@dataclass(frozen=True)
class OrderAttempt:
    order_date: date
    side: str
    order_quantity: Decimal | None
    filled_quantity: Decimal | None
    cancelled_quantity: Decimal | None


@dataclass(frozen=True)
class Outcome:
    planned_quantity: Decimal
    planned_side: str
    filled_quantity: Decimal
    #: 체결 / 계획. 1 이면 계획대로 다 됐다.
    fill_rate: Decimal | None
    avg_fill_price: Decimal | None
    #: 계획 시점 대비 얼마나 불리하게 체결됐나. **양수면 손해**다(방향 반영).
    #: 계획 가격을 모르면 None — 0 으로 두면 "정확히 계획대로"가 된다.
    slippage_rate: Decimal | None
    ordered_quantity: Decimal
    #: 주문 원장이 말하는 체결 수량. **체결 원장과 다를 수 있다**(아래 note).
    order_filled_quantity: Decimal
    #: 주문은 냈는데 안 걸린 수량.
    unfilled_quantity: Decimal
    cancelled_quantity: Decimal
    #: 주문 자체가 없었나. 미체결과 다르다.
    no_order: bool
    #: 두 원장이 서로 다른 말을 하나. True 면 화면이 **그 사실을 말해야 한다**.
    sources_disagree: bool


def _sum(values) -> Decimal:
    return sum((v for v in values if v is not None), Decimal("0"))


def evaluate(
    *,
    planned_side: str,
    planned_quantity: Decimal,
    planned_price_krw: Decimal | None,
    entry_date: date,
    fills: list[Fill],
    orders: list[OrderAttempt],
    window_days: int = 3,
    fx_rate: Decimal | None = None,
) -> Outcome:
    """계획 하나를 그 주변 체결·주문과 대조한다.

    ⚠️`fx_rate` 가 없으면 슬리피지를 **계산하지 않는다.** 계획 가격은 원화고
      체결 단가는 현지통화라, 환율 없이 비교하면 4자리 차이 나는 숫자를
      나란히 놓고 "1,300% 불리"라고 말하게 된다.
    """
    side = (planned_side or "").upper()
    lo, hi = entry_date - timedelta(days=window_days), entry_date + timedelta(days=window_days)

    near_fills = [
        f for f in fills if f.side.upper() == side and lo <= f.trade_date <= hi
    ]
    near_orders = [
        o for o in orders if o.side.upper() == side and lo <= o.order_date <= hi
    ]

    filled = _sum(f.quantity for f in near_fills)
    ordered = _sum(o.order_quantity for o in near_orders)
    order_filled = _sum(o.filled_quantity for o in near_orders)
    cancelled = _sum(o.cancelled_quantity for o in near_orders)

    amount = _sum(
        (f.quantity * f.price) for f in near_fills if f.quantity and f.price
    )
    qty_with_price = _sum(f.quantity for f in near_fills if f.quantity and f.price)
    avg_price = (amount / qty_with_price) if qty_with_price > 0 else None

    slippage = None
    if avg_price is not None and planned_price_krw and fx_rate and fx_rate > 0:
        planned_local = planned_price_krw / fx_rate
        if planned_local > 0:
            raw = (avg_price - planned_local) / planned_local
            # ⚠️매수는 비싸게 샀을 때, 매도는 싸게 팔았을 때가 손해다.
            slippage = (raw if side == "BUY" else -raw).quantize(
                _RATIO, rounding=ROUND_HALF_UP
            )

    return Outcome(
        planned_quantity=planned_quantity,
        planned_side=side,
        filled_quantity=filled,
        fill_rate=(
            (filled / planned_quantity).quantize(_RATIO, rounding=ROUND_HALF_UP)
            if planned_quantity and planned_quantity != 0
            else None
        ),
        avg_fill_price=(
            avg_price.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if avg_price is not None
            else None
        ),
        slippage_rate=slippage,
        ordered_quantity=ordered,
        order_filled_quantity=order_filled,
        unfilled_quantity=max(ordered - order_filled - cancelled, Decimal("0")),
        cancelled_quantity=cancelled,
        # ⚠️주문이 없는 것과 주문이 안 걸린 것은 다른 복기다.
        no_order=not near_orders,
        # ⚠️두 원장이 갈리는 일이 실제로 있다. 실측(SKHY 2026-09-18): 주문
        #   원장은 2주 체결이라는데 체결 원장에는 매도 행이 **아예 없다**.
        #   체결만 보고 "0주"라고 적으면 화면이 거짓말을 한다.
        sources_disagree=filled != order_filled,
    )
