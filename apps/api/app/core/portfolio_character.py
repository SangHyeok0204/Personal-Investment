"""포트폴리오 성격 — 목표 비중을 정하기 전에 지금이 어떤 모양인지 본다.

★리밸런싱 화면에서 "SOXL 을 몇 %로 둘까"를 정할 때, 그 20% 가 **레버리지 3배**
  라는 사실이 같이 보여야 한다. 비중만 보면 20% 인데 하루 움직임으로는 60% 를
  들고 있는 것과 같다.

⚠️**배수는 하루 수익률에만 적용된다.** 여러 날에 걸치면 변동성 끌림 때문에
  배수 × 기간수익률이 되지 않는다. '실효 노출'은 **오늘 하루** 얼마나
  움직이는지를 보는 숫자다 — 화면이 "3배 오른다"고 말하지 않게 같이 알린다.

⚠️배수의 근거는 **증권사가 준 종목명**이다. 시드와 이름이 어긋나면 조용히
  한쪽을 고르지 않고 **그 사실을 내보낸다** — TSL 을 2배로 잘못 적어 두었던
  적이 있다(이름은 1.25배).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

_RATIO = Decimal("0.000001")

#: 종목명에서 "N배"를 뽑는다. "1.25배", "3배" 둘 다 잡는다.
_NAME_MULTIPLIER = re.compile(r"(\d+(?:\.\d+)?)\s*배")


def multiplier_from_name(name: str | None) -> Decimal | None:
    """증권사 종목명에 적힌 배수. 없으면 None.

    ⚠️'3배'가 없다고 1배라고 단정하지 않는다 — 이름에 안 적었을 뿐일 수 있다.
    """
    if not name:
        return None
    match = _NAME_MULTIPLIER.search(name)
    return Decimal(match.group(1)) if match else None


@dataclass(frozen=True)
class Holding:
    ticker: str
    name: str | None
    weight: Decimal


@dataclass(frozen=True)
class LeveragePosition:
    ticker: str
    name: str | None
    weight: Decimal
    multiplier: Decimal
    effective_weight: Decimal
    source: str
    #: 시드와 종목명이 어긋나나. True 면 화면이 그 사실을 말해야 한다.
    disputed: bool
    name_multiplier: Decimal | None


@dataclass(frozen=True)
class Character:
    leverage: list[LeveragePosition] = field(default_factory=list)
    #: 레버리지 상품이 차지하는 비중 합(배수 적용 전).
    leveraged_weight: Decimal = Decimal("0")
    #: 배수를 적용한 전체 실효 노출. 레버리지가 없으면 주식 비중과 같다.
    effective_exposure: Decimal = Decimal("0")
    top1_ticker: str | None = None
    top1_weight: Decimal | None = None
    top3_weight: Decimal = Decimal("0")
    #: 허핀달 지수(비중 제곱합). 1 이면 한 종목, 1/n 이면 완전 균등.
    herfindahl: Decimal = Decimal("0")
    cash_weight: Decimal = Decimal("0")
    #: 유효 종목 수 = 1/HHI. "사실상 몇 종목에 걸려 있나".
    effective_count: Decimal | None = None


def build(
    holdings: list[Holding],
    leverage_map: dict[str, tuple[str, str]],
    *,
    cash_ticker: str | None = None,
) -> Character:
    """지금 포트폴리오의 성격.

    `holdings` 의 weight 는 **총자산 대비**다(예수금 포함). 현금 줄이 섞여
    있으면 `cash_ticker` 로 알려 준다 — 집중도 계산에서 빼야 하기 때문이다.
    """
    stocks = [h for h in holdings if h.ticker != cash_ticker]
    cash = next((h for h in holdings if h.ticker == cash_ticker), None)

    positions: list[LeveragePosition] = []
    effective = Decimal("0")
    leveraged_weight = Decimal("0")

    for h in stocks:
        seed = leverage_map.get(h.ticker)
        from_name = multiplier_from_name(h.name)
        if seed is None and from_name is None:
            # 레버리지 상품이 아니다 — 1배로 센다.
            effective += h.weight
            continue

        multiplier = Decimal(seed[0]) if seed else from_name
        source = seed[1] if seed else f"종목명에서 읽음: {h.name}"
        # ⚠️시드와 이름이 어긋나면 **이름을 믿는다**(증권사가 준 것이므로).
        #   다만 어긋났다는 사실을 숨기지 않는다.
        disputed = bool(
            seed is not None and from_name is not None and Decimal(seed[0]) != from_name
        )
        if disputed:
            multiplier = from_name
            source = f"종목명 우선: {h.name} (시드는 {seed[0]}배)"

        effective += h.weight * multiplier
        leveraged_weight += h.weight
        positions.append(
            LeveragePosition(
                ticker=h.ticker, name=h.name, weight=h.weight,
                multiplier=multiplier,
                effective_weight=(h.weight * multiplier).quantize(
                    _RATIO, rounding=ROUND_HALF_UP
                ),
                source=source, disputed=disputed, name_multiplier=from_name,
            )
        )

    positions.sort(key=lambda p: p.effective_weight, reverse=True)
    ranked = sorted(stocks, key=lambda h: h.weight, reverse=True)
    hhi = sum((h.weight * h.weight for h in stocks), Decimal("0"))

    return Character(
        leverage=positions,
        leveraged_weight=leveraged_weight.quantize(_RATIO, rounding=ROUND_HALF_UP),
        effective_exposure=effective.quantize(_RATIO, rounding=ROUND_HALF_UP),
        top1_ticker=ranked[0].ticker if ranked else None,
        top1_weight=ranked[0].weight if ranked else None,
        top3_weight=sum((h.weight for h in ranked[:3]), Decimal("0")).quantize(
            _RATIO, rounding=ROUND_HALF_UP
        ),
        herfindahl=hhi.quantize(_RATIO, rounding=ROUND_HALF_UP),
        cash_weight=(cash.weight if cash else Decimal("0")),
        # ⚠️HHI 가 0 이면 나눌 수 없다(보유가 없을 때). None 으로 둔다.
        effective_count=(
            (Decimal("1") / hhi).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            if hhi > 0
            else None
        ),
    )
