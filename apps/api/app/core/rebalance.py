"""리밸런싱 계산 — 목표 비중과 지금 보유의 차이를 **주수**로 바꾼다.

★알림이 "SOXL 비중 21.32% > 20%" 를 잡아 준다. 여기는 그 다음 질문에 답한다 —
  **그래서 몇 주를 팔아야 하나.**

⚠️분모는 **주식 평가액**이다(예수금 제외). 섹터/자산 배분 화면과 같은 분모를
  써야 두 화면의 비중이 같은 말을 한다. 예수금을 넣으면 같은 종목이 화면마다
  다른 비중으로 보인다.

⚠️목표가 없는 보유 종목을 **0% 로 간주하지 않는다.** 그렇게 하면 "목표를 아직
  안 적은 종목을 전부 팔아라"가 되는데, 그건 사용자가 시킨 적 없는 말이다.
  따로 모아 보여 주기만 한다.

⚠️주수는 **0 방향으로 내린다.** 반올림하면 목표를 넘겨 사거나 넘겨 판다.
  남는 금액은 잔여로 적어 둔다.

⚠️밴드 안의 차이는 **거래하지 않는다.** 실측 거래비용이 거래대금의 0.250% 라,
  작은 어긋남을 맞추려다 비용이 교정 효과보다 커진다.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

_MONEY = Decimal("0.01")
_RATIO = Decimal("0.000001")

#: 실측 거래비용률(수수료+세금 ÷ 거래대금, 2026-09-22 기준 82건).
MEASURED_COST_RATE = Decimal("0.0025")

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


@dataclass(frozen=True)
class Position:
    ticker: str
    name: str | None
    quantity: Decimal
    market_value_krw: Decimal | None


@dataclass(frozen=True)
class Target:
    ticker: str
    name: str | None
    weight: Decimal
    memo: str | None = None


@dataclass(frozen=True)
class Line:
    ticker: str
    name: str | None
    quantity: Decimal
    current_value_krw: Decimal | None
    current_weight: Decimal | None
    target_weight: Decimal
    target_value_krw: Decimal | None
    #: 목표 − 현재 (퍼센트포인트가 아니라 소수). None 이면 잴 수 없었다.
    drift: Decimal | None
    delta_value_krw: Decimal | None
    #: 1주의 원화 가격. 평가액 ÷ 수량으로 구한다 — 환율을 따로 곱하지 않는다.
    price_krw: Decimal | None
    #: 사고팔 주수(정수, 0 방향 내림). 가격을 모르면 None.
    delta_shares: int | None
    #: 주수로 못 맞춘 나머지 금액.
    residual_krw: Decimal | None
    action: str
    within_band: bool
    est_cost_krw: Decimal | None
    memo: str | None


@dataclass(frozen=True)
class Plan:
    lines: list[Line]
    #: 목표가 없는 보유 종목. **0% 로 치지 않는다.**
    untargeted: list[Line]
    base_value_krw: Decimal
    target_sum: Decimal
    #: 목표 합과 100% 의 차이. 0 이 아니면 화면이 말해야 한다.
    target_gap: Decimal
    band: Decimal
    buy_krw: Decimal
    sell_krw: Decimal
    est_cost_krw: Decimal
    trade_count: int


def _price(position: Position | None) -> Decimal | None:
    """1주의 원화 가격. 평가액 ÷ 수량.

    ⚠️환율을 따로 곱하지 않는다 — 평가액이 이미 원화 환산이라 여기서 다시
      환산하면 두 번 곱하게 된다.
    """
    if position is None or position.market_value_krw is None:
        return None
    if position.quantity is None or position.quantity == 0:
        return None
    return position.market_value_krw / position.quantity


def build_plan(
    positions: list[Position],
    targets: list[Target],
    *,
    band: Decimal = Decimal("0.01"),
    cost_rate: Decimal = MEASURED_COST_RATE,
) -> Plan:
    """목표 비중 → 사고팔 주수.

    `band` 는 **건드리지 않고 두는 폭**이다(0.01 = 1%p).
    """
    by_ticker = {p.ticker: p for p in positions}
    base = sum(
        (p.market_value_krw for p in positions if p.market_value_krw is not None),
        Decimal("0"),
    )
    target_sum = sum((t.weight for t in targets), Decimal("0"))

    def weight(value: Decimal | None) -> Decimal | None:
        if value is None or base <= 0:
            return None
        return (value / base).quantize(_RATIO, rounding=ROUND_HALF_UP)

    lines: list[Line] = []
    for target in targets:
        position = by_ticker.get(target.ticker)
        current_value = position.market_value_krw if position else Decimal("0")
        price = _price(position)
        target_value = (
            (base * target.weight).quantize(_MONEY, rounding=ROUND_HALF_UP)
            if base > 0
            else None
        )
        current_weight = weight(current_value)
        drift = (
            (target.weight - current_weight)
            if current_weight is not None
            else None
        )
        delta_value = (
            (target_value - current_value)
            if target_value is not None and current_value is not None
            else None
        )

        within = drift is not None and abs(drift) < band
        if delta_value is None or price is None or price <= 0:
            shares = None
            residual = delta_value
            action = HOLD
        elif within:
            # ⚠️밴드 안이면 **계산하지 않는다.** 숫자를 내놓으면 사용자가 그걸
            #   따라 하게 된다 — 비용이 교정 효과보다 큰 거래다.
            shares = 0
            residual = delta_value
            action = HOLD
        else:
            raw = delta_value / price
            # 0 방향 내림 — 반올림하면 목표를 넘긴다.
            shares = int(raw.quantize(Decimal("1"), rounding=ROUND_DOWN))
            residual = (delta_value - price * shares).quantize(
                _MONEY, rounding=ROUND_HALF_UP
            )
            action = BUY if shares > 0 else SELL if shares < 0 else HOLD

        traded = abs(price * shares) if (price and shares) else Decimal("0")
        lines.append(
            Line(
                ticker=target.ticker,
                name=target.name or (position.name if position else None),
                quantity=position.quantity if position else Decimal("0"),
                current_value_krw=current_value,
                current_weight=current_weight,
                target_weight=target.weight,
                target_value_krw=target_value,
                drift=drift,
                delta_value_krw=delta_value,
                price_krw=price,
                delta_shares=shares,
                residual_krw=residual,
                action=action,
                within_band=within,
                est_cost_krw=(traded * cost_rate).quantize(
                    _MONEY, rounding=ROUND_HALF_UP
                ),
                memo=target.memo,
            )
        )

    targeted = {t.ticker for t in targets}
    untargeted = [
        Line(
            ticker=p.ticker, name=p.name, quantity=p.quantity,
            current_value_krw=p.market_value_krw,
            current_weight=weight(p.market_value_krw),
            # ⚠️목표를 **0 이라고 적지 않는다.** 목표가 없는 것과 0% 는 다르다.
            target_weight=Decimal("0"), target_value_krw=None, drift=None,
            delta_value_krw=None, price_krw=_price(p), delta_shares=None,
            residual_krw=None, action=HOLD, within_band=False,
            est_cost_krw=None, memo=None,
        )
        for p in positions
        if p.ticker not in targeted
    ]

    buys = sum(
        (
            (line.price_krw * line.delta_shares)
            for line in lines
            if line.delta_shares and line.delta_shares > 0 and line.price_krw
        ),
        Decimal("0"),
    )
    sells = sum(
        (
            (line.price_krw * -line.delta_shares)
            for line in lines
            if line.delta_shares and line.delta_shares < 0 and line.price_krw
        ),
        Decimal("0"),
    )
    return Plan(
        lines=lines,
        untargeted=untargeted,
        base_value_krw=base,
        target_sum=target_sum,
        target_gap=(Decimal("1") - target_sum),
        band=band,
        buy_krw=buys.quantize(_MONEY, rounding=ROUND_HALF_UP),
        sell_krw=sells.quantize(_MONEY, rounding=ROUND_HALF_UP),
        est_cost_krw=sum(
            (line.est_cost_krw for line in lines if line.est_cost_krw),
            Decimal("0"),
        ).quantize(_MONEY, rounding=ROUND_HALF_UP),
        trade_count=sum(1 for line in lines if line.delta_shares),
    )
