"""'그 외'가 무엇인지 쪼갠다.

자산 분해는 이렇게 닫힌다 — **시작 + 순납입 + 손익(증권사) + 그 외 = 끝.**
앞의 셋은 증권사가 준 값이라 '그 외'는 정의상 **잔차**다. 무엇이라고 단정하지
않으려고 그렇게 불러 왔는데, 그러면 사용자가 판단할 근거도 없다. 그래서 쪼갠다.

★실측 결과(2026-06-04 ~ 09-21):

      잔차        -3,121,093
      환율(추정)  -3,043,025
      배당(실측)    +121,611
      수수료(실측)  -128,189
      ────────────────────────
      남는 것         -71,490   ← 잔차의 2.3%

  즉 **'그 외'는 대부분 환율이고, 나머지는 배당과 수수료다.** 이제 그렇게 말할
  근거가 생겼다.

⚠️**환율만 추정이다.** 배당과 수수료는 증권사가 일별로 주는 실측값이지만,
  환율 영향은 우리가 모형으로 만든다 — 전일 주식평가액 × 그날 환율 변동률.
  증권사가 준 일별 환율 칸(`exchange_rate`)이 532행 전부 비어 있어서 달리
  방법이 없다. 화면에서 **추정과 실측을 구분해 적는다.**

⚠️**월 단위로는 어긋난다.** 남는 것이 월별로 +298,177 / +258,672 / -373,329 /
  -255,010 로 크게 흔들리는데 합치면 -71,490 이다. 부호가 번갈아 나며 상쇄되는
  모양이라, 우리가 쓰는 종가 환율과 증권사의 환산 시점이 달라 **월 경계에서
  하루씩 밀리는** 것으로 보인다. 그래서 월별 숫자를 "이만큼이 환율이다"라고
  읽으면 안 된다 — 화면에도 그렇게 적는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable

_MONEY = Decimal("0.01")
_ZERO = Decimal("0")


@dataclass(frozen=True)
class Day:
    """일별 성과 한 줄. 합산이 끝난 값을 받는다."""

    base_date: date
    assets_krw: Decimal | None
    stock_value_krw: Decimal | None
    pnl_krw: Decimal | None
    deposit_krw: Decimal | None
    withdrawal_krw: Decimal | None
    dividend_krw: Decimal | None
    commission_tax_krw: Decimal | None


@dataclass(frozen=True)
class Residual:
    """'그 외'의 분해. 넷을 더하면 `total_krw` 가 된다."""

    total_krw: Decimal | None
    """잔차 = 끝자산 − 시작자산 − 순납입 − 손익."""

    fx_estimate_krw: Decimal | None
    """**추정.** 전일 주식평가액 × 그날 환율 변동률의 합. 환율을 못 읽으면 None."""

    dividend_krw: Decimal
    """실측. 증권사 일별 배당."""

    cost_krw: Decimal
    """실측. 증권사 일별 수수료·세금. 자산을 **줄이는** 쪽이라 부호는 화면에서 뺀다."""

    leftover_krw: Decimal | None
    """넷으로 설명되지 않고 남는 것. **0 이라고 우기지 않는다.**"""

    fx_days: int
    """환율을 읽어 모형에 넣은 날 수."""

    fx_missing_days: int
    """환율을 못 읽어 건너뛴 날 수. 0 으로 치지 않고 센다."""


def decompose(
    days: list[Day], rate_on: Callable[[date], Decimal | None]
) -> Residual:
    """'그 외'를 환율·배당·수수료·남는 것으로 쪼갠다.

    ⚠️첫날은 **기준선**이다. 첫날의 손익·입출금·배당·수수료를 세지 않는다 —
      전부 첫날 마감 자산에 이미 들어 있다. 다른 화면과 같은 규칙이다.
    """
    empty = Residual(
        total_krw=None, fx_estimate_krw=None, dividend_krw=_ZERO, cost_krw=_ZERO,
        leftover_krw=None, fx_days=0, fx_missing_days=0,
    )
    if len(days) < 2:
        return empty

    rest = days[1:]
    start, end = days[0].assets_krw, days[-1].assets_krw
    if start is None or end is None:
        return empty

    net_flow = sum(
        ((d.deposit_krw or _ZERO) - (d.withdrawal_krw or _ZERO) for d in rest), _ZERO
    )
    pnl = sum((d.pnl_krw for d in rest if d.pnl_krw is not None), _ZERO)
    total = end - start - net_flow - pnl

    dividend = sum((d.dividend_krw or _ZERO for d in rest), _ZERO)
    cost = sum((d.commission_tax_krw or _ZERO for d in rest), _ZERO)

    # 환율 영향(추정) = 전일 주식평가액 × 그날 환율 변동률.
    # ⚠️예수금은 넣지 않는다. 외화 예수금이 얼마인지 따로 주지 않아, 전액 원화로
    #   보고 빼는 편이 없는 숫자를 지어내는 것보다 낫다 — 그만큼 과소추정된다.
    fx_effect = _ZERO
    fx_days = 0
    fx_missing = 0
    for prev, cur in zip(days, rest):
        base = prev.stock_value_krw
        r0, r1 = rate_on(prev.base_date), rate_on(cur.base_date)
        if base is None or r0 is None or r1 is None or r0 == 0:
            fx_missing += 1
            continue
        fx_effect += base * (r1 / r0 - Decimal("1"))
        fx_days += 1

    fx_estimate = fx_effect if fx_days > 0 else None
    leftover = (
        total - fx_effect - dividend + cost if fx_estimate is not None else None
    )

    def q(value: Decimal | None) -> Decimal | None:
        return None if value is None else value.quantize(_MONEY, rounding=ROUND_HALF_UP)

    return Residual(
        total_krw=q(total),
        fx_estimate_krw=q(fx_estimate),
        dividend_krw=q(dividend) or _ZERO,
        cost_krw=q(cost) or _ZERO,
        leftover_krw=q(leftover),
        fx_days=fx_days,
        fx_missing_days=fx_missing,
    )
