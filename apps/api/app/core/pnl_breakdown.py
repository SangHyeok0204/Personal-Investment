"""손익 분해 시계열 — 총기간 손익 · 실현손익(누적) · 평가손익 · 총 평가액.

★정의(2026-10-01 사용자 지정, 계좌 전체 · 원화, **첫 거래일부터**):
  · 총기간 손익   = 키움 일별 계좌손익(usa21670 pnl_krw)을 첫 거래일부터 그날까지 더한 값.
    **예수금은 넣지 않는다** — 입출금은 손익이 아니다.
  · 실현손익(누적) = 매도로 확정된 손익(수수료·세금 뺀 뒤) + 배당, 첫 거래일부터 누적.
    `/realized` 의 `breakdown.net_krw` 와 같은 식이다(그쪽은 투자 시작일부터 자른다).
    배당은 원천징수 뒤 금액이라 세금을 또 빼지 않는다.
  · 평가손익     = 총기간 손익 − 실현손익(누적). **과거는 역산 값이다** — 그날의 보유분
    평가손익을 직접 잰 값이 아니다(아래 '오늘' 참고).
  · 총 평가액     = 주식 평가액 + 예수금. 실현손익을 따로 더하지 않는다 — 판 돈은 이미
    예수금 안에 있다(더하면 두 번 센다).

★오늘(`live`) — 키움 일별 행은 하루 늦게 온다. 오늘 점은
    총기간 손익 = 실현손익(누적, 오늘까지) + **키움 실제 평가손익**(/summary)
  로 둔다. 그래서 오늘 점의 평가손익은 역산이 아니라 실제 값이고, 타일 셋과 그래프
  끝점이 똑같다. ⚠️대가: 어제(마지막 일별 행)의 총기간 손익과 오늘 사이에 **계단**이
  생길 수 있다 — 일별 손익 합과 '실현 + 평가'가 정확히 같지 않기 때문이다
  (키움 일별 손익에는 외화 예수금 환산 차이 등도 섞인다고 본다). 실측은 API 독스트링.

⚠️모르는 날은 **0 이 아니라 None** 이다.
  · 일별 행이 없는 날(또는 그날 손익이 비어 있는 날)은 총기간 손익·평가손익이 None.
    주말·휴장일은 키움이 손익 0 인 행을 주므로 전날 값이 이어진다(행이 있으니까).
  · 빈 날의 손익은 모르므로 **뒤 날짜의 누적에도 더하지 않는다** — 있는 행만 더한다.
  · 실현손익은 원장이 처음부터 다 있으므로 매일 값이 있다(그날 매도가 없으면 전날과 같다).

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


@dataclass(frozen=True)
class Live:
    """오늘 점 — 일별 행 대신 지금 값(/summary)으로 채운다."""

    date: date
    unrealized_krw: Decimal | None
    total_value_krw: Decimal | None


def _q(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def build_series(
    start: date,
    end: date,
    daily_pnl_by_date: dict[date, Decimal | None],
    realized_by_date: dict[date, Decimal],
    total_value_by_date: dict[date, Decimal | None],
    live: Live | None = None,
) -> list[Point]:
    """start~end(양끝 포함) **달력 하루마다** 한 점.

    `daily_pnl_by_date` 는 그날 키움 일별 계좌손익, `realized_by_date` 는 그날 확정된
    실현손익(매매 + 배당)의 합이다. 둘 다 start 앞의 날짜가 들어 있으면 **누적의
    출발값으로 더한다** — 조회 창을 줄여도 누적은 첫 거래부터 센 값이어야 한다.

    평가손익 = 총기간 손익 − 실현손익(누적). 이 등식은 모든 점에서 성립한다(오늘 포함 —
    오늘은 총기간 손익을 실현 + 실제 평가로 만들기 때문).
    """
    if end < start:
        return []

    pnl_running = sum((v for d, v in daily_pnl_by_date.items() if d < start and v is not None), _ZERO)
    realized_running = sum((v for d, v in realized_by_date.items() if d < start), _ZERO)
    points: list[Point] = []
    day = start
    while day <= end:
        realized_running += realized_by_date.get(day, _ZERO)
        daily = daily_pnl_by_date.get(day)
        if daily is not None:
            pnl_running += daily

        if live is not None and day == live.date:
            unrealized = live.unrealized_krw
            total_period = realized_running + unrealized if unrealized is not None else None
            total_value = live.total_value_krw
        else:
            total_period = pnl_running if daily is not None else None
            unrealized = total_period - realized_running if total_period is not None else None
            total_value = total_value_by_date.get(day)

        points.append(
            Point(
                date=day,
                realized_cum_krw=_q(realized_running),
                unrealized_krw=_q(unrealized),
                total_period_pnl_krw=_q(total_period),
                total_value_krw=_q(total_value),
            )
        )
        day += timedelta(days=1)
    return points
