"""증권사 평가손익이 왜 (평가액 − 매입액) 과 다른가.

★화면에서 산수가 안 맞았다. 보유 종목 화면의 칸 셋이 이랬다.

      총 매입금액   33,352,051
      평가손익      +2,881,334
      ───────────────────────
      더하면        36,233,385
      총 평가금액   36,407,647   ← 174,262 모자란다

  더해 봤으면 틀렸다는 걸 알았을 사람에게 이 화면은 고장 난 화면이다.

★원인을 찾았다 — **키움의 평가손익은 제비용을 뺀 값이다.** 낼 수수료를 미리
  빼 두고 "지금 다 팔면 손에 남는 것"을 적는다. 모형으로 확인했다:

      모형 = 0.25% × 매입금액 + 0.25% × 평가금액
             (이미 낸 매수 수수료 + 지금 팔면 낼 매도 수수료)

      17종목 합계  실측 괴리 174,262  vs  모형 174,399   (차이 137원, 99.9%)

  종목별로도 SOXL 36,293 vs 36,312, SCHD 24,361 vs 24,363 처럼 붙는다.
  0.25% 는 체결 원장에서 실제로 잰 매수 수수료율과 같다(17종목 전부
  0.241~0.250%). `rebalance.MEASURED_COST_RATE` 와 같은 값이고, 서로 다른
  경로로 같은 값이 나온 셈이다.

⚠️**화면에 내보내는 값은 모형이 아니라 실측 잔차다.** 모형은 "이게 제비용이다"를
  설명할 때만 쓴다. 모형 숫자를 칸에 적으면 합이 안 맞고, 합이 안 맞는 것이
  애초에 고치려던 문제다.

⚠️0.25% 를 여기 다시 적지 않는다 — `rebalance.MEASURED_COST_RATE` 하나를 쓴다.
  같은 사실을 두 군데 적으면 한쪽만 고치게 된다.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.core.rebalance import MEASURED_COST_RATE

_MONEY = Decimal("0.01")


def reserve_krw(
    market_value_krw: Decimal | None,
    purchase_krw: Decimal | None,
    unrealized_pnl_krw: Decimal | None,
) -> Decimal | None:
    """증권사가 평가손익에서 미리 빼 둔 제비용. **실측 잔차**다.

    셋 중 하나라도 없으면 None 이다 — 0 으로 두면 "제비용 없음"으로 읽힌다.
    """
    if market_value_krw is None or purchase_krw is None or unrealized_pnl_krw is None:
        return None
    return (market_value_krw - purchase_krw - unrealized_pnl_krw).quantize(
        _MONEY, rounding=ROUND_HALF_UP
    )


def modelled_krw(
    market_value_krw: Decimal | None, purchase_krw: Decimal | None
) -> Decimal | None:
    """모형값 — 매수분 + 매도 예상분. 실측 잔차가 제비용임을 **설명**하는 데 쓴다.

    ⚠️칸에 적는 값으로 쓰지 말 것. 이 값으로는 매입 + 손익 + 제비용 = 평가액이
      정확히 닫히지 않는다(실측 차이 137원).
    """
    if market_value_krw is None or purchase_krw is None:
        return None
    return (MEASURED_COST_RATE * (market_value_krw + purchase_krw)).quantize(
        _MONEY, rounding=ROUND_HALF_UP
    )
