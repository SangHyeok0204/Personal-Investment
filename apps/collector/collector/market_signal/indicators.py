# -*- coding: utf-8 -*-
r"""[시장 시그널] 1단 — 일별 종가 하나로 뽑을 수 있는 지표 전수 (2026-08-31 신설).

price_monitor.xlsx 는 **일별 종가 한 줄**만 준다. 고가·저가·거래량·시가총액이 없다.
그래서 여기 있는 것이 이 파이프라인이 볼 수 있는 세계의 **전부**다. 아래 목록은
"종가만으로 계산 가능한가"를 기준으로 추린 것이고, 계산 불가인 것도 왜 불가인지
남겨 뒀다(나중에 누가 다시 시도하지 않도록).

━━ 계산 가능 (이 모듈이 내는 것) ━━
  A. 달력 앵커 수익률   dtd wtd mtd qtd ytd ytd2
  B. 롤링 수익률        r1w r1m r3m r6m r1y r2y
  C. 레인지 위치        ytd_low_gain ytd_high_drawdown range_pos_252
                        is_high_252 is_low_252 mdd_252 ath_gap
  D. 추세(이평)         ma5 ma20 ma60 ma120 ma200
                        dev20 dev60 dev120  (이격도 = P/MA-1)
                        ma_stack (정배열 +1 / 역배열 -1 / 혼조 0)
                        cross_20_60 (며칠 전 골든/데드크로스, 부호가 방향)
                        ma20_slope (MA20 의 20일 변화율)
  E. 변동성             vol20 vol60 vol252 (연율화 %) · vol_ratio = vol20/vol252
                        down_vol20 (음수 수익률만)
  F. 희소도 ★핵심      z_{h} (자기 σ 대비) · pct_{h} (자기 과거 분위수)
                        pct1y_{h} (최근 1년 분위수 — 체제 이중 트리거용)
  G. 모멘텀 질          streak (연속 동일부호 일수, 부호가 방향)
                        winrate60 · accel = r1m - r3m · mom_12_1 = r1y - r1m

━━ 계산 불가 (종가만으로는 안 됨 — 재시도 금지) ━━
  · ATR·진짜 갭·장중 변동폭   → 고가·저가 없음
  · 거래량·OBV·자금흐름       → 거래량 없음
  · RSI 는 계산은 되지만 넣지 않았다 — 종가 기반 z/분위수와 정보가 겹치는데
    임계(70/30)가 고정값이라 [[weekly-price-monitor-anomaly-rules]] 가 버린
    "고정 임계" 함정을 그대로 다시 들여온다.
  · 밸류에이션(PER·PBR)·수급   → 원천 자체가 없음

━━ ★★두 가지 규칙을 반드시 지킬 것 (전부 생성기가 겪고 고친 자리) ━━
  1. **분포 추정에는 이월(ffill 복사본)을 걷어낸 시계열을 쓴다.** 시트가 주말·휴일을
     forward-fill 하므로 0% 가 분포에 섞여 σ 가 과소 추정되고 z 가 통째로 부풀려진다.
  2. **기간 이동은 영업일 위치(shift)가 아니라 달력 일수로 한다.** 이월을 걷어낸
     시계열에서 shift(5) 를 하면 달력으로 열흘 넘게 거슬러 간다.

단위: 채권(is_yield)은 **bp**(차이×100), 나머지는 **%**(비율−1)×100.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date, timedelta

# 롤링 창 — 전부 **달력 일수**. 거래일로 세려면 ffill 판정이 필요한데 그 판정이
# 금리처럼 자릿수 짧은 열에서 오탐한다(price_board.ROLLING 과 같은 이유).
ROLLING = [("r1w", 7), ("r1m", 30), ("r3m", 91), ("r6m", 182), ("r1y", 365), ("r2y", 730)]

# 희소도를 재는 기간 — 1단 트리거가 실제로 보는 것들.
# ★DtD·WtD·MtD 만 본다. 분기 이상은 '튀었다'가 아니라 '추세'라서 1단이 아니라
#   온톨로지 단계(체제 판정)에서 쓴다.
HORIZONS = [("dtd", 1), ("wtd", 7), ("mtd", 30)]

MA_WINDOWS = [5, 20, 60, 120, 200]
MIN_HISTORY = 250  # 이보다 짧으면 z·분위수를 포기한다(σ 가 못 미덥다)


# ── 기본 도구 ────────────────────────────────────────────────────────────────

def _real_moves(series: dict[date, float]) -> dict[date, float]:
    """이월(BDH Fill=P 복사본)을 걷어낸 '실제로 값이 달라진 날'만의 시계열.

    ★분포(σ·분위수) 추정은 **반드시** 이걸 쓴다. 원본을 쓰면 주말·휴장의 0% 가
      섞여 σ 가 과소 추정되고 발화율이 목표의 2배 이상으로 뜬다.
    """
    out: dict[date, float] = {}
    prev = None
    for d in sorted(series):
        v = series[d]
        if prev is None or v != prev:
            out[d] = v
        prev = v
    return out


class _Lookup:
    """정렬된 날짜 배열 + 이분탐색. 달력 기준 '그 날짜 이하 마지막 값'을 O(log n) 으로."""

    def __init__(self, series: dict[date, float]):
        self.ds = sorted(series)
        self.vs = [series[d] for d in self.ds]

    def at_or_before(self, target: date) -> float | None:
        i = bisect_right(self.ds, target) - 1
        return self.vs[i] if i >= 0 else None

    def window(self, lo: date, hi: date) -> list[float]:
        a = bisect_right(self.ds, lo - timedelta(days=1))
        b = bisect_right(self.ds, hi)
        return self.vs[a:b]


def change(cur: float, ref: float | None, is_yield: bool) -> float | None:
    """금리는 bp 변화폭, 그 외는 % 수익률. price_board._change 와 **같은 정의**여야 한다."""
    if ref is None:
        return None
    if is_yield:
        return (cur - ref) * 100.0
    if ref == 0:
        return None
    return (cur / ref - 1.0) * 100.0


def _dtd_ref(series: dict[date, float], today: date) -> float | None:
    """DtD 기준값 — 값이 **실제로 달라지는** 직전 관측일. 최대 7일 소급.
    price_board._dtd_ref 와 같은 규칙(표와 숫자가 갈리면 안 된다)."""
    cur = series.get(today)
    if cur is None:
        return None
    d = today - timedelta(days=1)
    limit = today - timedelta(days=7)
    while d >= limit:
        v = series.get(d)
        if v is not None and v != cur:
            return v
        d -= timedelta(days=1)
    return None


def _pct_rank(sample: list[float], v: float) -> float | None:
    """v 가 sample 안에서 차지하는 분위(0~1). |값| 기준이 아니라 **부호 있는** 값 기준.

    ★z 가 아니라 이걸 쓰는 이유: 꼬리 두께가 시장마다 달라 같은 z 가 다른 희소도를
      뜻한다(과창판 주간 +12.31% 는 z=2.1 인데 실제로는 상위 1.2%). 분위수면 발화율이
      정의상 균일해지고 "과거 N년 중 상위 X%" 를 문장에 그대로 쓸 수 있다.
    """
    if len(sample) < 30:
        return None
    below = sum(1 for x in sample if x < v)
    return below / len(sample)


def _stdev(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var) if var > 0 else None


# ── 지표 계산 ────────────────────────────────────────────────────────────────

def _hist_changes(moves: dict[date, float], days: int, is_yield: bool) -> list[float]:
    """과거 분포 — '달력 days 일 전 대비' 변화의 전 구간 표본."""
    lk = _Lookup(moves)
    out: list[float] = []
    for d in lk.ds:
        c = change(moves[d], lk.at_or_before(d - timedelta(days=days)), is_yield)
        if c is not None:
            out.append(c)
    return out


def compute(series: dict[date, float], is_yield: bool = False,
            asof: date | None = None) -> dict:
    """일별 종가 시계열 하나 → 지표 한 묶음. 값이 없으면 그 항목만 None."""
    if not series:
        return {}
    ds = sorted(series)
    a = max(d for d in ds if asof is None or d <= asof) if (asof is None or any(d <= asof for d in ds)) else None
    if a is None:
        return {}
    cur = series[a]

    moves = _real_moves(series)          # 분포 추정 전용
    lk = _Lookup(series)                 # 값 조회는 원본(표와 일치해야 하므로)
    mlk = _Lookup(moves)

    out: dict = {"asof": a.isoformat(), "price": cur, "is_yield": is_yield,
                 "unit": "bp" if is_yield else "%"}

    # ── A. 달력 앵커 수익률 ──
    out["dtd"] = change(cur, _dtd_ref(series, a), is_yield)
    out["wtd"] = change(cur, lk.at_or_before(a - timedelta(days=7)), is_yield)
    out["mtd"] = change(cur, lk.at_or_before(a.replace(day=1) - timedelta(days=1)), is_yield)
    q_first = date(a.year, ((a.month - 1) // 3) * 3 + 1, 1)
    out["qtd"] = change(cur, lk.at_or_before(q_first - timedelta(days=1)), is_yield)
    out["ytd"] = change(cur, lk.at_or_before(date(a.year - 1, 12, 31)), is_yield)
    out["ytd2"] = change(cur, lk.at_or_before(date(a.year - 2, 12, 31)), is_yield)

    # ── B. 롤링 수익률 ──
    for key, days in ROLLING:
        out[key] = change(cur, lk.at_or_before(a - timedelta(days=days)), is_yield)

    # ── C. 레인지 위치 ──
    ytd_win = lk.window(date(a.year - 1, 12, 31), a)
    if ytd_win:
        lo, hi = min(ytd_win), max(ytd_win)
        out["ytd_low"] = lo
        out["ytd_high"] = hi
        out["ytd_low_gain"] = change(cur, lo, is_yield)        # 연저점 대비 상승
        out["ytd_high_drawdown"] = change(cur, hi, is_yield)   # 연고점 대비 (음수)
    win252 = lk.window(a - timedelta(days=365), a)
    if win252:
        lo, hi = min(win252), max(win252)
        rng = hi - lo
        out["range_pos_252"] = None if rng == 0 else (cur - lo) / rng * 100.0
        out["is_high_252"] = cur >= hi - 1e-12
        out["is_low_252"] = cur <= lo + 1e-12
        # MDD — 최근 1년 고점 이후 최대 낙폭(가격 자산만 의미 있다)
        if not is_yield:
            peak, mdd = None, 0.0
            for v in win252:
                peak = v if peak is None or v > peak else peak
                if peak and peak > 0:
                    mdd = min(mdd, (v / peak - 1) * 100.0)
            out["mdd_252"] = mdd
    all_hi = max(lk.vs)
    out["ath_gap"] = change(cur, all_hi, is_yield)  # 전 구간 고점 대비(음수 or 0)

    # ── D. 추세(이평) ──
    #   ★이평은 **거래일 개수**가 아니라 달력 창 안의 관측치 평균이다. 시트가 ffill 이라
    #     '최근 20행'을 세면 주말이 섞여 실제로는 14거래일치가 된다.
    for w in MA_WINDOWS:
        vals = lk.window(a - timedelta(days=int(w * 7 / 5)), a)
        out[f"ma{w}"] = sum(vals) / len(vals) if vals else None
    for w in (20, 60, 120):
        ma = out.get(f"ma{w}")
        out[f"dev{w}"] = change(cur, ma, is_yield) if ma else None
    stack = [out.get(f"ma{w}") for w in (5, 20, 60, 120)]
    if all(x is not None for x in stack):
        if all(stack[i] > stack[i + 1] for i in range(3)):
            out["ma_stack"] = 1        # 정배열
        elif all(stack[i] < stack[i + 1] for i in range(3)):
            out["ma_stack"] = -1       # 역배열
        else:
            out["ma_stack"] = 0
    out["cross_20_60"] = _cross_days(lk, a, 20, 60)
    ma20_prev = _ma_at(lk, a - timedelta(days=28), 20)
    if out.get("ma20") and ma20_prev:
        out["ma20_slope"] = change(out["ma20"], ma20_prev, is_yield)

    # ── E. 변동성 (일간 수익률 기준, 연율화) ──
    dr = _daily_returns(moves, is_yield)
    for win, key in ((20, "vol20"), (60, "vol60"), (252, "vol252")):
        sub = [v for d, v in dr if d > a - timedelta(days=int(win * 7 / 5))]
        sd = _stdev(sub)
        out[key] = sd * math.sqrt(252) if sd else None
    if out.get("vol20") and out.get("vol252"):
        out["vol_ratio"] = out["vol20"] / out["vol252"]
    sub20 = [v for d, v in dr if d > a - timedelta(days=28) and v < 0]
    sd = _stdev(sub20)
    out["down_vol20"] = sd * math.sqrt(252) if sd else None

    # ── F. 희소도 ★1단 트리거의 재료 ──
    enough = len(moves) >= MIN_HISTORY
    for key, days in HORIZONS:
        v = out.get(key if key != "wtd" else "wtd")
        if v is None or not enough:
            continue
        hist = _hist_changes(moves, days, is_yield)
        sd = _stdev(hist)
        mu = sum(hist) / len(hist) if hist else 0.0
        out[f"z_{key}"] = (v - mu) / sd if sd else None
        out[f"pct_{key}"] = _pct_rank(hist, v)
        # 체제 이중 트리거 — 최근 1년만의 분포에서도 본다.
        # ★왜 둘 다 보나: 금 주간 +7.12%(2026-08-10)가 '최근 1년' 기준으로는 안 걸렸다.
        #   1월 고점 이후 변동성이 커진 탓이다. "요즘 원래 이 정도"는 맞지만 회의에서
        #   금 7% 를 안 짚을 수는 없다 → 전 구간 OR 최근 1년, 하나만 걸려도 발화.
        hist1y = _hist_changes(
            {d: moves[d] for d in moves if d > a - timedelta(days=365 + days)}, days, is_yield)
        out[f"pct1y_{key}"] = _pct_rank(hist1y, v)

    # ── G. 모멘텀 질 ──
    out["streak"] = _streak(dr)
    recent60 = [v for d, v in dr if d > a - timedelta(days=84)]
    out["winrate60"] = (sum(1 for v in recent60 if v > 0) / len(recent60) * 100.0
                        if recent60 else None)
    if out.get("r1m") is not None and out.get("r3m") is not None:
        out["accel"] = out["r1m"] - out["r3m"]          # 단기가 중기를 추월 = 가속
    if out.get("r1y") is not None and out.get("r1m") is not None:
        out["mom_12_1"] = out["r1y"] - out["r1m"]       # 12-1 모멘텀(학술 표준)
    return out


def _daily_returns(moves: dict[date, float], is_yield: bool) -> list[tuple[date, float]]:
    """실제 변동일 사이의 변화. 이월이 걷힌 뒤라 '연속 관측치 간' 변화가 곧 일간 변화다."""
    ds = sorted(moves)
    out = []
    for i in range(1, len(ds)):
        c = change(moves[ds[i]], moves[ds[i - 1]], is_yield)
        if c is not None:
            out.append((ds[i], c))
    return out


def _ma_at(lk: _Lookup, at: date, w: int) -> float | None:
    vals = lk.window(at - timedelta(days=int(w * 7 / 5)), at)
    return sum(vals) / len(vals) if vals else None


def _cross_days(lk: _Lookup, a: date, short: int, long: int) -> int | None:
    """마지막 골든/데드크로스가 며칠 전인가. 부호가 방향(+골든 / -데드). 없으면 None.

    ★90일까지만 거슬러 본다 — 그보다 오래된 크로스는 '사건'이 아니라 '상태'이고,
      상태는 ma_stack 이 이미 말한다.
    """
    prev_sign = None
    for back in range(0, 91):
        d = a - timedelta(days=back)
        ms, ml = _ma_at(lk, d, short), _ma_at(lk, d, long)
        if ms is None or ml is None:
            break
        sign = 1 if ms > ml else -1
        if prev_sign is not None and sign != prev_sign:
            return (back - 1) * prev_sign   # prev_sign = 오늘 쪽 방향
        prev_sign = sign
    return None


def _streak(dr: list[tuple[date, float]]) -> int | None:
    """연속 동일부호 일수. 부호가 방향(+3 = 3일 연속 상승)."""
    if not dr:
        return None
    sign = 1 if dr[-1][1] > 0 else -1 if dr[-1][1] < 0 else 0
    if sign == 0:
        return 0
    n = 0
    for _, v in reversed(dr):
        if (v > 0) == (sign > 0) and v != 0:
            n += 1
        else:
            break
    return n * sign
