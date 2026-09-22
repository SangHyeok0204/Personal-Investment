"""원화 자산 증감과 증권사 일별 손익을 잇는다 — 그리고 시간가중수익률.

★왜 필요한가: 수익률 추이 화면이 **한 화면에서 서로 반대되는 말을 하고 있었다.**
  2026-06-04 ~ 09-21 구간에서

      상단 타일  '입출금 제외 증감'  −₩722,749  (−1.86%)
      월별 표    '월 손익'의 합      +₩2,469,456

  둘 다 맞다. **다른 것을 재고 있었을 뿐이다.**

  · 예탁자산(`deposit_assets_krw`)은 **원화 환산액**이다. 환율이 빠지면 종목이
    그대로여도 줄어든다.
  · 증권사 일별 손익(`pl_amt` → `pnl_krw`)은 **주가 손익**이다. 환율 변동을
    담지 않는다.

  실측으로 확인했다 — 이 구간에 USD/KRW 가 1,530.11 → 1,384.86 으로 **−9.49%**
  빠졌다. 두 숫자의 차이 ₩3,192,205 를 −9.49% 로 나누면 ₩33,637,566, 이 구간
  평균 주식평가액과 거의 같다. 즉 **차이의 대부분이 환율**이다.

  그래서 두 숫자를 나란히 두지 않고 **다리를 놓는다**:

      주가 손익  +₩2,469,456
      환율 등    −₩3,192,205      ← 잔차
      ────────────────────────
      원화 증감  −₩722,749

⚠️`fx_effect_krw` 는 **잔차**다. '환율'이라고 단정하지 않는다. 환율이 대부분인
  것은 위 계산으로 확인했지만, 배당·수수료·원장 잡음도 여기로 들어온다. 화면에도
  '환율 등'이라고 적는다 — 재지 않은 것을 잰 것처럼 부르지 않는다.

⚠️**`cumulative_pnl_krw`(acum_pl_amt) 를 연속된 시계열로 쓰지 말 것.** 조회 창
  경계에서 그날 손익으로 **초기화된다.** 실측: 531일 중 528일은
  `cum_t − cum_{t−1} == pnl_t` 가 정확히 성립하는데, 2025-09-18 과 2026-09-14
  두 날만 어긋난다. 2026-09-14 에는 누적이 2,274,791 → −1,836,144 로 뛰는데
  그 값이 그날 손익과 정확히 같다(= 그날부터 다시 셌다). 그래서 기간 손익을
  `cum(끝) − cum(시작)` 으로 구하면 **틀린다.** 일별 손익을 더한다.

★TWR 을 이제는 낼 수 있다. 예전에는 "일별 현금흐름이 정확해야 해서 못 한다"고
  적어 두었는데, **연쇄(chain-link)는 그 문제를 피해 간다** — 입출금이 있는 날도
  그날의 수익률만 곱하면 되기 때문이다. 증권사가 주는 `return_rate` 가 실제로
  `pnl_t ÷ 전일 예탁자산` 임을 110일 중 107일에서 확인했다(나머지 3일은
  소수점 4자리 반올림 오차, 최대 0.0006). 다만 그 반올림이 110번 곱해지면
  누적되므로, **금액에서 직접 일간 수익률을 구해 곱한다**(7.01% vs 7.21%).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

_MONEY = Decimal("0.01")
_RATE = Decimal("0.000001")
_ZERO = Decimal("0")


@dataclass(frozen=True)
class Day:
    """일별 성과 한 줄. 합산이 끝난 뒤의 값을 받는다(계좌가 여럿이면 합쳐서)."""

    base_date: date
    assets_krw: Decimal | None
    pnl_krw: Decimal | None
    deposit_krw: Decimal | None
    withdrawal_krw: Decimal | None


@dataclass(frozen=True)
class Bridge:
    """주가 손익 → 원화 증감 사이의 다리, 그리고 주가 기준 TWR."""

    price_pnl_krw: Decimal | None
    """증권사 일별 손익의 합. 첫날은 뺀다 — 시작 자산에 이미 들어 있다."""

    asset_change_krw: Decimal | None
    """원화 기준 증감 = 끝 자산 − 시작 자산 − 순입금."""

    fx_effect_krw: Decimal | None
    """잔차 = 원화 증감 − 주가 손익. 대부분 환율이지만 '환율'이라 단정하지 않는다."""

    twr: Decimal | None
    """주가 기준 시간가중수익률(연쇄). 환율은 들어 있지 않다."""

    twr_days: int
    """수익률을 실제로 곱한 날 수."""

    unmeasured_days: int
    """전일 자산이 없거나 0 이어서 그날 수익률을 낼 수 없던 날 수."""

    missing_pnl_days: int
    """손익 칸이 비어 있던 날 수. **0 으로 치지 않는다** — 세어서 알린다."""


def build(days: list[Day]) -> Bridge:
    """일별 성과에서 다리와 TWR 을 만든다.

    ⚠️첫날은 **기준선**이다. 첫날의 손익도, 첫날의 입출금도 세지 않는다 —
      둘 다 첫날 마감 자산에 이미 반영돼 있어서 또 더하면 두 번 세는 것이 된다.
    """
    empty = Bridge(
        price_pnl_krw=None, asset_change_krw=None, fx_effect_krw=None,
        twr=None, twr_days=0, unmeasured_days=0, missing_pnl_days=0,
    )
    if len(days) < 2:
        return empty

    rest = days[1:]

    missing_pnl = sum(1 for d in rest if d.pnl_krw is None)
    price_pnl = sum((d.pnl_krw for d in rest if d.pnl_krw is not None), _ZERO)

    start = days[0].assets_krw
    end = days[-1].assets_krw
    net_deposit = sum(
        ((d.deposit_krw or _ZERO) - (d.withdrawal_krw or _ZERO) for d in rest), _ZERO
    )
    asset_change = (
        end - start - net_deposit if start is not None and end is not None else None
    )

    # 연쇄 수익률. 전일 자산이 분모다 — 그날 입금은 분모에 넣지 않는다.
    # (입금은 그날 마감 자산에 들어오지만 그 돈이 그날 수익을 낸 것은 아니다.)
    product = Decimal("1")
    twr_days = 0
    unmeasured = 0
    for prev, cur in zip(days, rest):
        base = prev.assets_krw
        if base is None or base <= 0 or cur.pnl_krw is None:
            unmeasured += 1
            continue
        product *= Decimal("1") + cur.pnl_krw / base
        twr_days += 1

    return Bridge(
        price_pnl_krw=price_pnl.quantize(_MONEY, rounding=ROUND_HALF_UP),
        asset_change_krw=(
            asset_change.quantize(_MONEY, rounding=ROUND_HALF_UP)
            if asset_change is not None
            else None
        ),
        fx_effect_krw=(
            (asset_change - price_pnl).quantize(_MONEY, rounding=ROUND_HALF_UP)
            if asset_change is not None
            else None
        ),
        twr=(
            (product - Decimal("1")).quantize(_RATE, rounding=ROUND_HALF_UP)
            if twr_days > 0
            else None
        ),
        twr_days=twr_days,
        unmeasured_days=unmeasured,
        missing_pnl_days=missing_pnl,
    )
