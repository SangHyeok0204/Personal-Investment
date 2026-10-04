"""내 계좌 수익률 — 투자 시작일(INVESTMENT_START, 2026-06-01)부터, 일별.

★정의(2026-10-04 사용자 지정, 계좌 전체 · 원화) — 성과 분석 화면들의 **정본**이다:
    수익률(t)        = 시작일 이후 손익(t) ÷ 투입 원금(t)
    시작일 이후 손익(t) = 총기간 손익(t) − unrealized_at_start
                     = 실현(시작일~t) + (평가(t) − 평가(시작 시점))
    투입 원금(t)      = A0 + 시작일부터 t 까지의 순외부입금 누적
    A0              = 시작일 장 시작 전 총자산(주식 + 예수금) = 시작일 **앞** 마지막 일별 행의
                      `deposit_assets_krw`(실측 05-31 = 29,176,951)
    순외부입금        = 그날 `deposit_krw − withdrawal_krw` — 계좌 밖에서 들어오고 나간 돈만.
                      ⚠️주식을 판 돈은 흐름이 아니다(이미 예수금 안에 있다).

  · 총기간 손익은 `app.core.pnl_breakdown` 의 시계열을 **그대로** 받는다 — 손익을 여기서
    따로 다시 세지 않는다. 오늘 점도 그쪽의 live 점(실현 + 키움 실제 평가)이다.
  · unrealized_at_start 를 빼는 이유: A0 안에 시작 시점 평가익이 이미 들어 있다. 빼지
    않으면 첫날부터 +5% 쯤으로 뜬다(분자·분모가 같은 돈을 두 번 센다).
  · 입금은 **분모만** 올린다 — 손익은 그대로다. 그래서 입금 날 수익률이 음수로 꺾이지
    않는다(잠깐 희석될 뿐). 출금은 분모를 내린다.

★기준점: 시계열 맨 앞에 `시작일 − 1일`(장 시작 전) 점을 하나 둔다 — 손익 0 · 원금 A0 ·
  수익률 0. 차트가 이 점을 100 으로 두고 출발한다.

⚠️모르는 것은 **0 이 아니라 None** 이다.
  · 손익이 None 인 날(일별 행이 아직 없는 날 등)은 수익률도 None 이다.
  · 일별 행이 있는데 입금·출금 칸이 비어 있으면 그날 흐름을 모른다 — 그날부터 뒤의
    누적·원금·수익률이 모두 None 이다(빈 칸을 0 으로 읽으면 분모가 조용히 틀린다).
  · 일별 행이 **없는** 날(마지막 행 뒤 — 보통 어제·오늘)은 흐름을 아직 모른다. 손익 쪽
    규칙과 같이 **있는 행만 더한다** — 누적은 마지막 행 값이 이어진다.
    ⚠️대가: 마지막 일별 행 뒤에 들어온 입금은 행이 올 때까지 분모에 없다(오늘 점이
    그만큼 덜 희석된다). 손익에는 영향이 없다.
  · A0 를 모르면(시작일 앞 마지막 행의 자산이 비어 있으면) 원금·수익률 전부 None.
    시작일 앞에 행이 **하나도** 없으면 그때 계좌에 돈이 없었던 것이므로 0 이다(의도한 0).
  · 원금이 0 이하이면 나눌 수 없다 — None.

이 모듈은 DB 를 모른다 — 이미 날짜별로 합산한 값을 받아 줄을 세운다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.core import pnl_breakdown as pb

_MONEY = Decimal("0.01")
_RATIO = Decimal("0.000001")
_ZERO = Decimal("0")


@dataclass(frozen=True)
class Point:
    date: date
    pnl_since_start_krw: Decimal | None
    invested_krw: Decimal | None
    cum_net_flow_krw: Decimal | None
    # 그날 순외부입금(차트 표식용). 행이 없거나 흐름이 없으면 None — '흐름 0' 과 같다.
    net_flow_krw: Decimal | None
    return_ratio: Decimal | None


def _q(value: Decimal | None, step: Decimal = _MONEY) -> Decimal | None:
    return None if value is None else value.quantize(step, rounding=ROUND_HALF_UP)


def build(
    pnl_points: Sequence[pb.Point],
    unrealized_at_start: Decimal | None,
    start_assets: Decimal | None,
    net_flow_by_date: dict[date, Decimal | None],
) -> list[Point]:
    """`pnl_points`(pnl_breakdown.build_series 결과, 시작일부터 달력 하루마다) 위에
    수익률 시계열을 얹는다. 맨 앞에 기준점(시작일 − 1일, 수익률 0)을 붙인다.

    `net_flow_by_date` 는 일별 행이 있는 날의 순외부입금이다. 값이 None 이면 그날
    행은 있는데 흐름 칸이 비어 있다(모른다). 키가 없으면 그날 행이 없다.
    """
    if not pnl_points:
        return []

    start = pnl_points[0].date
    baseline = Point(
        date=start - timedelta(days=1),
        pnl_since_start_krw=_ZERO.quantize(_MONEY),
        invested_krw=_q(start_assets),
        cum_net_flow_krw=_ZERO.quantize(_MONEY),
        net_flow_krw=None,
        return_ratio=_ZERO.quantize(_RATIO) if start_assets else None,
    )
    out = [baseline]
    cum: Decimal | None = _ZERO
    for p in pnl_points:
        flow = None
        if p.date in net_flow_by_date:
            flow = net_flow_by_date[p.date]
            # 행이 있는데 흐름을 모른다 → 그날부터 누적을 모른다.
            cum = None if cum is None or flow is None else cum + flow

        pnl = (
            None
            if p.total_period_pnl_krw is None or unrealized_at_start is None
            else p.total_period_pnl_krw - unrealized_at_start
        )
        invested = None if start_assets is None or cum is None else start_assets + cum
        ratio = (
            pnl / invested
            if pnl is not None and invested is not None and invested > 0
            else None
        )
        out.append(
            Point(
                date=p.date,
                pnl_since_start_krw=_q(pnl),
                invested_krw=_q(invested),
                cum_net_flow_krw=_q(cum),
                net_flow_krw=_q(flow) if flow else None,
                return_ratio=_q(ratio, _RATIO),
            )
        )
    return out
