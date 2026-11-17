"""타점 승률 — "이 상태에서 사서 n개월 들고 있으면 몇 %가 이익이었나" (투자 전략 1단계).

★2026-10-28 사용자 요청: 롱온리 장기투자. "지금 사면 n개월 이상에서 90% 이상 확률로 수익인 타점"을 찾는다.
  1단계는 **한 시계열**(지수 1개 또는 종목 1개)의 표다. 바스켓(2~3종목)은 다음 단계.

계산(월말 기준):
  · 진입월 i 마다 그때까지의 정보만으로 상태를 정한다 — 고점 대비 낙폭(그 달까지의 최고치), 10개월 이동평균 위/아래.
  · 보유 h 개월 뒤 값이 진입값보다 크면 '이익'.
  · 조건 × 보유기간마다 승률(겹치는 창 전부) · 중앙/최악 수익 · 보유 중 최악 낙폭.

⚠️겹치는 창의 승률은 표본이 많아 보이지만 **서로 독립이 아니다**(SPX 를 −20% 에서 산 131개월은 실제로는
  약세장 예닐곱 번이다). 그래서 진입 후 h 개월을 건너뛰며 뽑은 **독립 회차**를 따로 세고, 그 회차들로
  Wilson 95% 하한을 낸다. 화면은 이 하한을 '믿을 만한 승률'로 보여 준다.
⚠️지수(monthly_closes)는 **가격만**(배당 제외), 종목(OHLCV adj_close)은 배당·분할 반영 — 같은 표에 섞지 않는다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

HORIZONS: tuple[int, ...] = (6, 12, 24, 36, 60, 120)
TARGET = 0.9
MIN_EPISODES = 5   # 이보다 적은 독립 회차로는 '몇 개월이면 90%'를 판정하지 않는다

# (키, 라벨, 조건) — 조건은 진입월의 (낙폭, 10개월선 아래 여부)를 받는다.
CONDITIONS: tuple[tuple[str, str], ...] = (
    ("all", "언제 사든"),
    ("dd10", "고점 대비 −10% 이하"),
    ("dd20", "고점 대비 −20% 이하"),
    ("dd30", "고점 대비 −30% 이하"),
    ("dd50", "고점 대비 −50% 이하"),
    ("below_ma10", "10개월 이동평균 아래"),
)
_DD = {"dd10": -0.10, "dd20": -0.20, "dd30": -0.30, "dd50": -0.50}


def wilson_lower(wins: int, n: int, z: float = 1.96) -> float | None:
    """이항 비율의 Wilson 하한. 표본이 적으면 낮게 나온다 — 그게 의도다."""
    if n <= 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def _meets(key: str, drawdown: float, below_ma: bool | None) -> bool:
    if key == "all":
        return True
    if key == "below_ma10":
        return bool(below_ma)
    return drawdown <= _DD[key]


@dataclass(frozen=True)
class Cell:
    n: int                 # 겹치는 창 수
    win_rate: float | None
    median: float | None
    worst: float | None    # 최악의 최종 수익
    worst_dip: float | None  # 보유 중 최악 낙폭(진입가 대비)
    episodes: int          # 독립 회차 수(h 개월씩 건너뛰며)
    episode_wins: int
    lower: float | None    # 독립 회차 기준 Wilson 95% 하한


def compute(level: pd.Series, partial_last: bool = False) -> dict:
    """월말 값(오름차순, 결측 없음) → 조건 × 보유기간 표 + 지금 상태.

    `level` 의 인덱스는 월(Timestamp), 값은 양수 레벨(가격 또는 누적지수).
    `partial_last` — 마지막 값이 아직 안 끝난 달이면 True. 과거 표(진입·결과)에서는 빼고 '지금 상태'에만 쓴다.
    """
    s = level.dropna()
    s = s[s > 0]
    values = s.to_list()
    months = [d.strftime("%Y-%m") for d in s.index]
    n = len(values)

    peak = 0.0
    drawdown: list[float] = []
    below: list[bool | None] = []
    for i, v in enumerate(values):
        peak = max(peak, v)
        drawdown.append(v / peak - 1)
        below.append(v < sum(values[i - 9 : i + 1]) / 10 if i >= 9 else None)

    # 과거 표가 쓰는 구간 — 미완성 마지막 달은 진입으로도, h 개월 뒤 결과로도 쓰지 않는다.
    hist = n - 1 if partial_last and n > 0 else n
    table: dict[str, dict[int, Cell]] = {}
    for key, _ in CONDITIONS:
        entries = [i for i in range(hist) if _meets(key, drawdown[i], below[i])]
        row: dict[int, Cell] = {}
        for h in HORIZONS:
            usable = [i for i in entries if i + h < hist]
            if not usable:
                row[h] = Cell(0, None, None, None, None, 0, 0, None)
                continue
            rets = [values[i + h] / values[i] - 1 for i in usable]
            dips = [min(values[i : i + h + 1]) / values[i] - 1 for i in usable]
            # 독립 회차 — 진입하면 h 개월 동안 다음 진입을 받지 않는다.
            picks, nxt = [], -1
            for i in usable:
                if i >= nxt:
                    picks.append(i)
                    nxt = i + h
            ep_wins = sum(values[i + h] > values[i] for i in picks)
            row[h] = Cell(
                n=len(usable),
                win_rate=sum(r > 0 for r in rets) / len(rets),
                median=float(pd.Series(rets).median()),
                worst=min(rets),
                worst_dip=min(dips),
                episodes=len(picks),
                episode_wins=int(ep_wins),
                lower=wilson_lower(int(ep_wins), len(picks)),
            )
        table[key] = row

    def min_months(row: dict[int, Cell], field: str) -> int | None:
        """이 보유기간부터 **그 이상 모든 기간**에서 기준(90%)을 넘는 가장 짧은 기간.

        ⚠️독립 회차가 MIN_EPISODES 보다 적은 기간은 판정에서 뺀다 — 1회 1승을 '100%'로 세면
          −50% 같은 드문 조건이 늘 '6개월이면 90%'로 뜬다. 판정할 기간이 하나도 없으면 None.
        """
        judged = [h for h in HORIZONS if row[h].episodes >= MIN_EPISODES]
        found = None
        for h in reversed(judged):
            v = getattr(row[h], field)
            if v is None or v < TARGET:
                break
            found = h
        return found

    now = {
        "month": months[-1] if months else None,
        "drawdown": drawdown[-1] if drawdown else None,
        "below_ma10": below[-1] if below else None,
    }
    active = [k for k, _ in CONDITIONS if n and _meets(k, now["drawdown"], now["below_ma10"])]

    return {
        "first_month": months[0] if months else None,
        "last_month": months[-1] if months else None,
        "months": n,
        "horizons": list(HORIZONS),
        "target": TARGET,
        "min_episodes": MIN_EPISODES,
        "now": {**now, "active": active, "partial": partial_last},
        "rows": [
            {
                "key": key,
                "label": label,
                "active": key in active,
                "min_months_rate": min_months(table[key], "win_rate"),
                "min_months_lower": min_months(table[key], "lower"),
                "cells": [{"h": h, **table[key][h].__dict__} for h in HORIZONS],
            }
            for key, label in CONDITIONS
        ],
    }


def month_end(daily: pd.Series) -> pd.Series:
    """일별 값 → 월말 값(그 달 마지막 거래일). 인덱스는 그 달 1일(monthly_closes 와 같은 꼴)."""
    s = daily.dropna().sort_index()
    if s.empty:
        return s
    last = s.groupby(s.index.to_period("M")).last()
    last.index = last.index.to_timestamp()
    return last
