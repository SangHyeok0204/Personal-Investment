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

★원화 실질(환차 포함) — 2026-10-04 사용자 지정("둘 다 표시"). 위 수익률은 키움 손익
  (USD 손익 × 그때 환율)에서 나오므로 **보유 USD 자산의 환산 손실·이익이 빠진다**(환율
  제외). 원화로 실제 얼마가 됐는지는 총자산으로 따로 잰다 — 분모는 같다:
    원화 손익(t)   = 총자산(t) − A0 − 순외부입금 누적(t)
    원화 수익률(t) = 원화 손익(t) ÷ 투입 원금(t)
    총자산(t)      = pnl_breakdown 점의 `total_value_krw` 를 그대로 쓴다 — 과거는 그날
                     `deposit_assets_krw`(모든 계좌 행이 있는 날만), 행이 없는 날은 그날
                     마지막 스냅샷 총자산, 오늘은 /summary 총자산. 단 미국 휴장이면 마지막
                     일별 행 값(아래 ★미국 휴장일).
  짝: 환율 제외 계좌 ↔ 지수 USD, 원화 실질 계좌 ↔ 지수 원화 환산.
  실측(2026-10-04): 10-01 행 37,392,099 → −1,499,881(−3.86%). 같은 기간 키움 손익 합
  +2,308,295 와의 차 ≈ 3.8M 이 환산 손실(환율 1,507 → 1,343)이다. 오늘(일)은 미국
  휴장이라 10-03 행 38,444,390 → −447,590(−1.15%) — 규칙 전 live 38,027,894(−2.22%).
  ⚠️총자산을 모르는 날(행도 스냅샷도 없거나 자산 칸이 빈 날)은 원화 손익·수익률이 None
    이다 — 앞날 값을 끌어오지 않는다(예외: 아래 미국 휴장일 규칙). 원금을 모르면 역시
    None. 기준점은 0.
  ⚠️마지막 일별 행 뒤(보통 오늘)에 들어온 입금은 총자산에는 있고 원금에는 아직 없다 —
    그만큼 원화 손익이 부풀어 보인다(행이 오면 바로잡힌다). 환율 제외 쪽은 손익에 영향 없음.

★미국 휴장일엔 마지막 일별 행 그대로(`carry_closed_days`) — 2026-10-04 사용자 지정.
  일별 행의 총자산은 **키움 정산 환율**, 오늘 live 총자산은 **지금 환율**로 환산한다. 행
  뒤에 미국 장이 한 번도 안 열렸는데(주말·휴장) live 를 쓰면 기준 환율만 바뀐 것이 차트 끝
  하락으로 보였다 — 실측(2026-10-04 일): 10-02 행 38,444,390(−1.15%) → 오늘 live
  38,027,894(−2.22%), 그 −1.07%p 전부가 환율 기준 차이였다.
    · 행이 **없는** 날 d 에서, 직전 행 날짜 r 뒤로 끝난 미국 정규장(ET 날짜 s, r < s ≤ d)이
      없고 (d 가 마지막 점이면) 지금 정규장이 열려 있지도 않으면 → 총자산 = r 의 값.
    · 그 외(행 뒤에 장이 열렸거나 열려 있다) → 지금처럼 live/스냅샷.
    · 날짜 대응: 미국 ET 날짜 D 의 정규장은 키움 base_date D 행에 들어간다. 실측 — 금요일 행
      = 토·일 행(10-02 = 10-03, 09-25 = 09-26 = 09-27), 월요일 행에서 바뀐다. 벤치마크의
      lag 0 상관(+0.699)과도 맞다.
    · ⚠️공휴일 파일을 두지 않는다 — 장이 열렸는지는 이미 받는 ^GSPC 일봉(봉이 있으면 연
      날)으로 본다(`quote_cache.us_session_dates`). 예전 수집기의 휴일 파일은 외부 드라이브
      의존이라 일부러 지웠다. ^GSPC 를 못 받으면(None) 지금처럼 live 다 — 깨지지 않는다.
    · 시계열이 r 뒤를 덮지 못하면(일봉 첫 날 > r) 모른다 → 그날은 손대지 않는다.
    · 환율 제외(return_ratio)는 키움 손익이라 상관없다 — 이 규칙은 원화 실질에만 쓴다.
      /portfolio 총 평가액 타일은 그대로 live 다(pnl_breakdown 은 바꾸지 않는다).

이 모듈은 DB 를 모른다 — 이미 날짜별로 합산한 값을 받아 줄을 세운다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
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
    # 원화 실질(환차 포함) — 총자산 − A0 − 순외부입금 누적. 정의는 머리말.
    krw_pnl_since_start_krw: Decimal | None
    krw_return_ratio: Decimal | None


def _q(value: Decimal | None, step: Decimal = _MONEY) -> Decimal | None:
    return None if value is None else value.quantize(step, rounding=ROUND_HALF_UP)


def carry_closed_days(
    pnl_points: Sequence[pb.Point],
    row_dates: set[date],
    us_sessions: Sequence[date] | None,
    session_open: bool,
) -> list[pb.Point]:
    """미국 장이 안 열린 행 없는 날의 `total_value_krw` 를 직전 일별 행 값으로 바꾼다(머리말).

    `row_dates` 는 일별 행(모든 계좌 · 자산 칸 있음)이 있는 날, `us_sessions` 는 끝난
    미국 정규장 날짜(ET, 오름차순) — None 이면 모른다(그대로 돌려준다). `session_open` 은
    지금 정규장이 열려 있나 — 마지막 점(오늘)에만 쓴다.
    """
    if not us_sessions:
        return list(pnl_points)
    first_known = us_sessions[0]
    out: list[pb.Point] = []
    prev_row: pb.Point | None = None
    for i, p in enumerate(pnl_points):
        if p.date in row_dates:
            prev_row = p
        elif (
            prev_row is not None
            and prev_row.date >= first_known
            and not any(prev_row.date < s <= p.date for s in us_sessions)
            and not (session_open and i == len(pnl_points) - 1)
        ):
            p = replace(p, total_value_krw=prev_row.total_value_krw)
        out.append(p)
    return out


def build(
    pnl_points: Sequence[pb.Point],
    unrealized_at_start: Decimal | None,
    start_assets: Decimal | None,
    net_flow_by_date: dict[date, Decimal | None],
) -> list[Point]:
    """`pnl_points`(pnl_breakdown.build_series 결과, 시작일부터 달력 하루마다) 위에
    수익률 시계열을 얹는다. 맨 앞에 기준점(시작일 − 1일, 수익률 0)을 붙인다.

    원화 실질 수익률의 총자산은 각 점의 `total_value_krw` 다(머리말).
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
        krw_pnl_since_start_krw=_ZERO.quantize(_MONEY),
        krw_return_ratio=_ZERO.quantize(_RATIO) if start_assets else None,
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
        # 원화 실질 — 그날 총자산(pnl_breakdown 의 total_value_krw)에서 원금을 뺀다.
        krw_pnl = (
            None
            if p.total_value_krw is None or invested is None
            else p.total_value_krw - invested
        )
        krw_ratio = (
            krw_pnl / invested
            if krw_pnl is not None and invested is not None and invested > 0
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
                krw_pnl_since_start_krw=_q(krw_pnl),
                krw_return_ratio=_q(krw_ratio, _RATIO),
            )
        )
    return out
