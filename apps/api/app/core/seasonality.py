"""계절성 통계 · 3진 시그널 · walk-forward 채점 (계획 C2).

원본 `Downloads/계절성/seasonality.py` 의 계산을 **그대로** 옮겼다 — 원본 산출물
(`seasonality_stats.csv`·`signals_history.csv`·`sector_stats.csv`)과 한 글자도 다르지
않아야 한다(`scripts/verify_seasonality_port.py`). 바꾼 것은 둘뿐이다:

1. ⚠️**수익률은 빈틈없는 월 달력 위에서 낸다**(`monthly_returns`). 원본은 여러 지수를
   한 DataFrame 에 올려 합집합 인덱스가 우연히 빈 달을 메워 줬다. 지수를 하나씩
   따로 계산하면 그 보호가 사라져 항셍 1964~69 의 두세 달 변화가 '한 달 수익률'로
   둔갑한다(계획 §D-0). → 달력을 명시적으로 채우고 `pct_change(fill_method=None)`.
2. 원본의 전역 상태(`sea.MIN_N = 8` 로 모듈을 고쳐 쓰던 산업 스크립트)를 인자로.

★시그널은 예측이 아니다(계획 원칙 5). 특히 `signal()` 은 |t| 가 T_SIG 미만이면
  **근거 없이 '상승'** 을 돌려준다("롱 기본값"). 화면은 이를 `근거 없음` 으로 따로 센다
  (`evidence()`).
"""
from __future__ import annotations

import math
from statistics import NormalDist

import pandas as pd
from scipy.stats import t as _student_t

WINDOWS = [("전구간", None), ("10년", 10), ("5년", 5)]
WIN_NAME = {w: name for name, w in WINDOWS}
MIN_N = 15        # 전구간 최소 관측치 (미만이면 t 무시 → 상승 기본값)
T_SIG = 0.5       # ⚠️원본 이력: 1.0 → 0.5 → 0.75 → 0.5 (같은 백테스트로 골랐다 — 표본 내 수치)
BAND_YEARS = 5    # 중립 밴드: 작년까지 5개 역년의 월수익률 3분위
BAND_MIN_N = 12   # 밴드 계산 최소 개월
FDR_Q = 0.05


def monthly_returns(closes: dict[str, dict[str, float]]) -> pd.DataFrame:
    """{시계열: {'YYYY-MM': 종가}} → 월초 인덱스의 단순수익률 표.

    빈 달은 NaN, **빈 달 다음 달도 NaN** 이다(두세 달 변화를 한 달로 세지 않는다).
    """
    frames = {}
    for key, months in closes.items():
        if not months:
            continue
        s = pd.Series(
            {pd.Timestamp(int(m[:4]), int(m[5:7]), 1): float(v) for m, v in months.items()}
        ).sort_index()
        full = pd.date_range(s.index[0], s.index[-1], freq="MS")
        frames[key] = s.reindex(full)
    px = pd.DataFrame(frames).sort_index()
    return px.pct_change(fill_method=None)


def min_n(window, base: int = MIN_N):
    """구간별 최소 관측치. 5년 구간은 월당 5개뿐이라 구간 길이로 낮춘다."""
    return base if window is None else min(base, window)


def clip_window(r, window, end=None):
    if window is None:
        return r
    end = r.index[-1] if end is None else end
    return r[r.index > end - pd.DateOffset(years=window)]


def tstat(x):
    n = len(x)
    m = x.mean()
    s = x.std(ddof=1)
    if n < 2 or s == 0:
        return 0.0
    return m / (s / math.sqrt(n))


def pvalue(t, n=None):
    """양측 p. n 이 있으면 Student-t(df=n-1) — 정규근사는 n 작은 구간에서 p 를 수십 배 작게 낸다."""
    if n is not None and n >= 2:
        return float(2 * _student_t.sf(abs(t), n - 1))
    return 2 * (1 - NormalDist().cdf(abs(t)))


def tercile_band(r, year):
    """year 직전 BAND_YEARS 개 역년 월수익률의 3분위 (하한, 상한). 표본 부족이면 None."""
    sub = r[(r.index.year >= year - BAND_YEARS) & (r.index.year < year)]
    if len(sub) < BAND_MIN_N:
        return None
    return float(sub.quantile(1 / 3)), float(sub.quantile(2 / 3))


def signal(t, mean, n, band, need=MIN_N):
    """3진 시그널. 반환 (라벨, 방향 -1/0/+1)."""
    if n < need or abs(t) < T_SIG:
        return "상승", 1                      # 1차 필터: 유의하지 않으면 롱 기본값
    if band is not None and band[0] <= mean <= band[1]:
        return "중립", 0
    return ("상승", 1) if t > 0 else ("하락", -1)


def evidence(t, n, need=MIN_N) -> bool:
    """시그널에 근거가 있나. False 면 '상승' 은 기본값일 뿐이다(화면: '근거 없음')."""
    return n >= need and abs(t) >= T_SIG


def hit(direction, realized, band):
    """적중 여부. 중립(방향 0)은 실현수익률이 밴드 안이면 적중."""
    if direction == 0:
        return int(band is not None and band[0] <= realized <= band[1])
    return int(realized > 0) if direction > 0 else int(realized < 0)


def proof_table(rets, window=None, need_base: int = MIN_N):
    """구간 내 (시계열, 월) 통계 + BH-FDR(평균대비 p 기준). 원본과 열 이름·반올림이 같다."""
    need = min_n(window, need_base)
    wname = WIN_NAME[window]
    end = rets.dropna(how="all").index[-1]
    recs = []
    for col in rets.columns:
        r = clip_window(rets[col].dropna(), window, end)
        mu = r.mean()
        for m in range(1, 13):
            x = r[r.index.month == m]
            n = len(x)
            base = dict(구간=wname, 지수=col, 월=m, n=n)
            if n < need:
                recs.append(dict(base, 평균=None, 상승률=None, t=None, 평균대비=None,
                                 상회율=None, t_ex=None, p=None, 전후반부호일치=None,
                                 FDR유의=""))
                continue
            xe = x - mu
            te = tstat(xe)
            half = n // 2
            agree = (xe.iloc[:half].mean() > 0) == (xe.iloc[half:].mean() > 0)
            recs.append(dict(base, 평균=round(x.mean() * 100, 2),
                             상승률=round((x > 0).mean() * 100, 1),
                             t=round(tstat(x), 2),
                             평균대비=round(xe.mean() * 100, 2),
                             상회율=round((xe > 0).mean() * 100, 1),
                             t_ex=round(te, 2), p=pvalue(te, n),
                             전후반부호일치="Y" if agree else "N", FDR유의=""))
    df = pd.DataFrame(recs)
    # Benjamini-Hochberg — 반올림 전 p 로 판정
    tested = df.dropna(subset=["p"]).sort_values("p").reset_index()
    k = len(tested)
    passed = -1
    for j, p in enumerate(tested["p"]):
        if p <= (j + 1) / k * FDR_Q:
            passed = j
    if passed >= 0:
        df.loc[tested.loc[:passed, "index"], "FDR유의"] = "*"
    df["p"] = df["p"].astype(float).round(6)
    return df


def _rec(wname, dt, col, sig, t, n, hist, band, **extra):
    rec = dict(구간=wname, 예측월=dt.strftime("%Y-%m"), 지수=col, 시그널=sig,
               t=round(t, 2), n=n,
               과거평균=round(float(hist.mean()) * 100, 2) if n else None,
               과거상승률=round(float((hist > 0).mean()) * 100, 1) if n else None,
               밴드하한=round(band[0] * 100, 2) if band else None,
               밴드상한=round(band[1] * 100, 2) if band else None)
    rec.update(extra)
    return rec


def walk_forward(rets, window=None, need_base: int = MIN_N):
    """각 월을 그 이전 데이터(구간이면 직전 window 년)만으로 예측 (look-ahead 없음)."""
    need = min_n(window, need_base)
    wname = WIN_NAME[window]
    recs = []
    for col in rets.columns:
        r = rets[col].dropna()
        bands = {y: tercile_band(r, y) for y in sorted(set(r.index.year))}
        by_month = {m: r[r.index.month == m] for m in range(1, 13)}
        for dt, realized in r.items():
            hist = by_month[dt.month]
            hist = hist[hist.index < dt]
            if window is not None:
                hist = hist[hist.index >= dt - pd.DateOffset(years=window)]
            n = len(hist)
            t = tstat(hist) if n >= 2 else 0.0
            mean = float(hist.mean()) if n else 0.0
            band = bands[dt.year]
            sig, d = signal(t, mean, n, band, need)
            recs.append(_rec(wname, dt, col, sig, t, n, hist, band,
                             실현수익률=round(realized * 100, 2),
                             적중=hit(d, realized, band)))
    return pd.DataFrame(recs)


def next_month_signals(rets, proof, window=None, need_base: int = MIN_N):
    """마지막 데이터 달 + 1 의 시그널.

    ⚠️원본 이름은 '다음 달'이지만, 월말이 지나 데이터가 붙은 뒤에는 이 달이 **이미
      진행 중인 이번 달**이다. 화면 라벨은 '이번 달'로 쓴다(계획 C 화면).
    """
    need = min_n(window, need_base)
    wname = WIN_NAME[window]
    last = rets.dropna(how="all").index[-1]
    nxt = last + pd.DateOffset(months=1)
    starred = {(r["지수"], r["월"]) for _, r in proof.iterrows() if r["FDR유의"] == "*"}
    recs = []
    for col in rets.columns:
        r = rets[col].dropna()
        hist = r[r.index.month == nxt.month]
        if window is not None:
            hist = hist[hist.index >= nxt - pd.DateOffset(years=window)]
        n = len(hist)
        t = tstat(hist) if n >= 2 else 0.0
        mean = float(hist.mean()) if n else 0.0
        band = tercile_band(r, nxt.year)
        sig, _ = signal(t, mean, n, band, need)
        recs.append(_rec(wname, nxt, col, sig, t, n, hist, band,
                         실현수익률=float("nan"), 적중="",
                         검증셀="★" if (col, nxt.month) in starred else "",
                         근거=evidence(t, n, need)))
    return pd.DataFrame(recs)
