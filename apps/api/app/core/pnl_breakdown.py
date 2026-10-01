"""손익 분해 시계열 — 총기간 손익 · 실현손익(누적) · 평가손익 · 총 평가액.

★정의(2026-10-01 사용자 지정, 계좌 전체 · 원화, **투자 시작일(INVESTMENT_START,
  2026-06-01)부터**):
  · 총기간 손익   = 키움 일별 계좌손익(usa21670 pnl_krw)을 시작일부터 그날까지 더한 값.
    **0 에서 출발한다** — 첫 점(시작일)은 그날 하루의 손익이다. 시작일 앞날에 0 점을
    따로 찍지 않는다(그래프가 시작일에서 시작해야 하고, '시작일 장 시작 = 0' 이라는
    뜻은 첫 점이 그날 하루 손익이라는 것으로 이미 드러난다).
    **예수금은 넣지 않는다** — 입출금은 손익이 아니다.
  · 실현손익(누적) = 매도로 확정된 손익(수수료·세금 뺀 뒤) + 배당, 시작일부터 누적
    (역시 0 에서 출발). `/realized` 의 `breakdown.net_krw` 와 같은 식·같은 시작일이다.
    배당은 원천징수 뒤 금액이라 세금을 또 빼지 않는다.
  · 평가손익     = 그 순간 보유분의 평가손익 **수준**이다 — 0 에서 출발하지 않는다.
    첫 거래부터 센 일별 손익 누적 − 첫 거래부터 센 실현 누적(fc2a565 의 역산)과 같다.
    **과거는 역산 값이다** — 그날의 보유분 평가손익을 직접 잰 값이 아니다.
  · 총 평가액     = 주식 평가액 + 예수금. 실현손익을 따로 더하지 않는다 — 판 돈은 이미
    예수금 안에 있다(더하면 두 번 센다).

★등식(모든 점, 오늘 포함):
    총기간(시작일~) − 실현(시작일~) = 평가(그날) − 평가(시작 시점)
  '평가(시작 시점)' = `unrealized_at_start` = 시작일 **장 시작 전**(= 앞날 마감)의 역산
  평가손익 = 시작일 앞의 일별 손익 합 − 시작일 앞의 실현 합. 앞날 마감을 쓰는 것은
  총기간·실현이 시작일 하루치부터 더하기 때문이다(시작일 마감을 쓰면 첫 점에서 등식이
  깨진다).

★오늘(`live`) — 키움 일별 행은 하루 늦게 온다. 오늘 점은
    평가손익 = **키움 실제 평가손익**(/summary)
    총기간 손익 = 실현손익(시작일~오늘) + 실제 평가손익 − unrealized_at_start
  로 둔다(등식을 오늘에도 지키는 가장 단순한 규칙). 그래서 타일 셋과 그래프 끝점이
  똑같다. ⚠️대가: 마지막 일별 행과 오늘 사이에 **계단**이 생길 수 있다 — 일별 손익
  합과 '실현 + 평가'가 정확히 같지 않기 때문이다(키움 일별 손익에는 외화 예수금 환산
  차이 등도 섞인다고 본다). 계단 크기는 fc2a565(첫 거래부터) 때와 같다 — 시작일을
  옮기면 총기간·평가 모두 같은 상수만큼 움직일 뿐이다. 실측은 API 독스트링.

⚠️모르는 날은 **0 이 아니라 None** 이다.
  · 일별 행이 없는 날(또는 그날 손익이 비어 있는 날)은 총기간 손익·평가손익이 None.
    주말·휴장일은 키움이 손익 0 인 행을 주므로 전날 값이 이어진다(행이 있으니까).
  · 빈 날의 손익은 모르므로 **뒤 날짜의 누적에도 더하지 않는다** — 있는 행만 더한다.
  · 실현손익은 원장이 처음부터 다 있으므로 매일 값이 있다(그날 매도가 없으면 전날과 같다).
  · 시작일 앞에 일별 행이 하나도 없는데 실현은 있으면 `unrealized_at_start` 를 모른다
    (None) — 그러면 평가손익 시계열도 None 이다. 시작일 앞에 아무 기록도 없으면 그때
    보유분이 없었던 것이므로 0 이다(의도한 0 — 계좌가 시작일 뒤에 열렸다).

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


def unrealized_at_start(
    start: date,
    daily_pnl_by_date: dict[date, Decimal | None],
    realized_by_date: dict[date, Decimal],
) -> Decimal | None:
    """시작일 장 시작 전(= 앞날 마감)의 역산 평가손익 — 등식의 출발값.

    = 시작일 앞의 일별 손익 합 − 시작일 앞의 실현 합(첫 거래부터).
    ⚠️시작일 앞에 일별 행이 없는데 실현은 있으면 모른다(None). 둘 다 없으면 그때
      보유분이 없었던 것이라 0 이다.
    """
    pnl_before = [v for d, v in daily_pnl_by_date.items() if d < start and v is not None]
    realized_before = [v for d, v in realized_by_date.items() if d < start]
    if not pnl_before:
        return None if realized_before else _ZERO
    return sum(pnl_before, _ZERO) - sum(realized_before, _ZERO)


def build_series(
    start: date,
    end: date,
    daily_pnl_by_date: dict[date, Decimal | None],
    realized_by_date: dict[date, Decimal],
    total_value_by_date: dict[date, Decimal | None],
    live: Live | None = None,
) -> list[Point]:
    """start(투자 시작일)~end(양끝 포함) **달력 하루마다** 한 점.

    `daily_pnl_by_date` 는 그날 키움 일별 계좌손익, `realized_by_date` 는 그날 확정된
    실현손익(매매 + 배당)의 합이다. 총기간·실현은 start 에서 **0 으로 출발**하고,
    start 앞의 날짜는 평가손익의 출발값(`unrealized_at_start`)에만 쓴다.

    평가손익 = unrealized_at_start + 총기간 − 실현. 이 등식은 모든 점에서 성립한다(오늘
    포함 — 오늘은 총기간 손익을 실현 + 실제 평가 − 출발값으로 만들기 때문).
    """
    if end < start:
        return []

    base = unrealized_at_start(start, daily_pnl_by_date, realized_by_date)
    pnl_running = _ZERO
    realized_running = _ZERO
    points: list[Point] = []
    day = start
    while day <= end:
        realized_running += realized_by_date.get(day, _ZERO)
        daily = daily_pnl_by_date.get(day)
        if daily is not None:
            pnl_running += daily

        if live is not None and day == live.date:
            unrealized = live.unrealized_krw
            total_period = (
                realized_running + unrealized - base
                if unrealized is not None and base is not None else None
            )
            total_value = live.total_value_krw
        else:
            total_period = pnl_running if daily is not None else None
            unrealized = (
                base + total_period - realized_running
                if total_period is not None and base is not None else None
            )
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
