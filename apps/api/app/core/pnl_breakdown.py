"""손익 분해 시계열 — 실현손익(누적) · 평가손익 · 총기간 손익 · 총 평가액.

★정의(2026-10-01 사용자 지정, 계좌 전체 · 원화):
  · 실현손익(누적) = 매도로 확정된 손익(수수료·세금 뺀 뒤) + 배당. `/realized` 의
    `breakdown.net_krw` 와 같은 식이다. 배당은 원천징수 뒤 금액이라 세금을 또 빼지 않는다.
  · 평가손익     = 지금 들고 있는 종목의 평가손익(키움 pl_amt_krw 기준).
  · 총기간 손익   = 실현손익(누적) + 평가손익. **예수금은 넣지 않는다** — 주식이 처음
    넣은 돈을 얼마나 불렸나를 본다.
  · 총 평가액     = 주식 평가액 + 예수금. 실현손익을 따로 더하지 않는다 — 판 돈은 이미
    예수금 안에 있다(더하면 두 번 센다).

⚠️모르는 날은 **0 이 아니라 None** 이다. 평가손익을 0 으로 채우면 그날 총기간 손익이
  실현손익과 같아져 "그날 평가손익이 0원이었다"는 없는 사실이 그려진다.
  실현손익은 원장이 처음부터 다 있으므로 매일 값이 있다(그날 매도가 없으면 전날과 같다).

이 모듈은 DB 를 모른다 — 날짜별로 이미 합산한 값을 받아 줄을 세운다. 그래야
누적·등식·결측 처리를 DB 없이 시험할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

_MONEY = Decimal("0.01")
_ZERO = Decimal("0")


@dataclass(frozen=True)
class Point:
    date: date
    realized_cum_krw: Decimal
    unrealized_krw: Decimal | None
    total_period_pnl_krw: Decimal | None
    total_value_krw: Decimal | None


def _q(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def build_series(
    start: date,
    end: date,
    realized_by_date: dict[date, Decimal],
    unrealized_by_date: dict[date, Decimal | None],
    total_value_by_date: dict[date, Decimal | None],
) -> list[Point]:
    """start~end(양끝 포함) **달력 하루마다** 한 점.

    `realized_by_date` 는 그날 확정된 실현손익(매매 + 배당)의 합이다. start 앞의
    날짜가 들어 있으면 **누적의 출발값으로 더한다** — 조회 창을 줄여도 누적은
    투자 시작부터 센 값이어야 한다(창 시작에서 0 으로 되돌리면 안 된다).

    ⚠️평가손익이 없는 날은 총기간 손익도 None 이다. 실현손익만으로 채우지 않는다.
    """
    if end < start:
        return []

    running = sum((v for d, v in realized_by_date.items() if d < start), _ZERO)
    points: list[Point] = []
    day = start
    while day <= end:
        running += realized_by_date.get(day, _ZERO)
        unrealized = unrealized_by_date.get(day)
        points.append(
            Point(
                date=day,
                realized_cum_krw=_q(running),
                unrealized_krw=_q(unrealized),
                total_period_pnl_krw=_q(running + unrealized) if unrealized is not None else None,
                total_value_krw=_q(total_value_by_date.get(day)),
            )
        )
        day += timedelta(days=1)
    return points
