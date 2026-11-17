"""투자 전략 연구실 — ① 바스켓 괴리(Strategy 1) ② 웅덩이 매수(Strategy 2). 화면 `/strategy/basket-spread`·`/strategy/dip-buy`.

★2026-10-29 사용자 요청(질문 4개로 정의 확정):
  · 분석 기간 2026-01-21 ~ 오늘. 지표 계산에 필요한 그 이전 가격(이평 60일 + n)은 쓴다 — 신호·결과만 기간 안에서 센다.
  · [전략1] 괴리 = 바스켓 A 의 n일 지표 − 바스켓 B 의 n일 지표(바스켓 지표 = 편입 종목 지표의 평균).
      지표: 수익률(종가_t / 종가_{t−n} − 1) · MA5/MA20/MA60 변화율(MA_t / MA_{t−n} − 1). n = 5·10·20·40 영업일.
      경계 = 괴리 분포의 상·하위 10% — ⚠️미래를 쓰지 않으려고 **직전 120 영업일**(그날 제외)의 백분위로 잡는다.
      괴리가 상위 10% 로 커지면 A 가 비싸다 → **B 를 산다**, 하위 10% 면 **A 를 산다**(사용자 정의).
      hit = 산 바스켓이 5·10 영업일 뒤 **+5% 이상** 오름. 진입은 신호 다음 영업일 종가, 같은 쌍은 보유기간 동안 새 신호를 받지 않는다.
  · [전략2] 웅덩이 = ① n 영업일 연속 종가 하락(3·4·5일) ② 종가 < 볼린저 하단(20일, 2σ). 그때 샀다면 5·10일 뒤 수익을 기준선(아무 날 매수)과 비교.
⚠️분석 기간이 9개월 남짓이라 신호가 적다. 조합이 많으면 1등 hit ratio 는 운으로도 높다 — 표본 수·기준선을 늘 같이 낸다.
⚠️가격은 야후 일봉(수정 종가 아님 — 배당 미포함, 분할은 야후가 반영). 1시간 캐시.
"""
from __future__ import annotations

import itertools
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

WORKER_PATH = str(Path(__file__).resolve().parents[3] / "worker")
if WORKER_PATH not in sys.path:
    sys.path.insert(0, WORKER_PATH)
from prices.history import fetch_candles  # noqa: E402

START = pd.Timestamp("2026-01-21")
NS = (5, 10, 20, 40)
HOLDS = (5, 10)
HIT = 0.05
PCT_WINDOW = 120
PCT_MIN = 60
LO_Q, HI_Q = 0.10, 0.90
INDICATORS: dict[str, str] = {"ret": "수익률", "ma5": "MA5 변화율", "ma20": "MA20 변화율", "ma60": "MA60 변화율"}
DOWN_STREAKS = (3, 4, 5)
# ★2026-10-29 3회차: 웅덩이 매수에 손절을 걸면? — 보유 중 종가가 진입가 대비 −7% 이하로 닫히면 그 종가에 판다.
STOP = 0.07
# ★2026-10-29 3회차: 다른 기간에서도 같은가 — 분석 기간 직전 1년(2025-01-02 ~ 2026-01-20)을 '검증 기간'으로 따로 돌린다.
CHECK_START, CHECK_END = pd.Timestamp("2025-01-02"), pd.Timestamp("2026-01-20")
BB_WINDOW, BB_SIGMA = 20, 2.0

# (키, 이름, 종목, 묶음 기준) — 1~5종목, 섹터·업종·밸류체인으로 묶는다(사용자 선호). 앞의 셋은 사용자 예시 그대로.
BASKETS: list[tuple[str, str, tuple[str, ...], str]] = [
    ("HYPER", "하이퍼스케일러 top3", ("GOOGL", "MSFT", "AAPL"), "빅테크"),
    ("SEMI", "반도체 top3", ("NVDA", "AMD", "SNDK"), "반도체"),
    ("AIINFRA", "AI 인프라", ("BE", "LITE", "VRT"), "AI 인프라"),
    ("MEMORY", "메모리·스토리지", ("MU", "WDC", "STX"), "반도체"),
    ("EQUIP", "반도체 장비", ("AMAT", "LRCX", "KLAC", "ASML"), "반도체"),
    ("FOUNDRY", "파운드리·패키징", ("TSM", "INTC", "AMKR"), "반도체"),
    ("NETWORK", "네트워크·광통신", ("ANET", "CSCO", "CIEN", "COHR"), "AI 인프라"),
    ("POWERGEN", "전력 생산", ("VST", "CEG", "NRG", "TLN"), "전력"),
    ("POWEREQ", "전력 장비", ("ETN", "GEV", "PWR"), "전력"),
    ("NUCLEAR", "원전·SMR", ("OKLO", "SMR", "CCJ"), "전력"),
    ("NEOCLOUD", "네오클라우드·AI 서버", ("CRWV", "NBIS", "SMCI", "DELL"), "AI 인프라"),
    ("SAAS", "업무 소프트웨어", ("CRM", "NOW", "ADBE", "INTU"), "소프트웨어"),
    ("CYBER", "사이버보안", ("CRWD", "PANW", "ZS", "FTNT"), "소프트웨어"),
    ("PLATFORM", "소비자 플랫폼", ("META", "AMZN", "NFLX"), "빅테크"),
    ("BIO", "바이오 대장", ("LLY", "NVO", "JNJ"), "헬스케어"),
]
BASKET = {k: (name, ts, grp) for k, name, ts, grp in BASKETS}

_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}
_cache: dict[str, tuple[float, object]] = {}
CACHE_SECONDS = 3600


def _cached(key: str, build, cacheable=lambda v: True):
    """키마다 잠금을 잡고 만든다 — 화면이 meta·spread·leaderboard 를 동시에 불러도 야후는 한 번만 받는다."""
    with _lock:
        klock = _key_locks.setdefault(key, threading.Lock())
    with klock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        value = build()
        if cacheable(value):
            _cache[key] = (time.time(), value)
        return value


def _fetch_closes() -> tuple[float, pd.DataFrame, list[str]]:
    tickers = sorted({t for _, _, ts, _ in BASKETS for t in ts})
    with ThreadPoolExecutor(8) as ex:
        got = dict(zip(tickers, ex.map(lambda s: fetch_candles(s, years=2), tickers)))
    for s in [s for s, c in got.items() if c is None]:      # 빠진 종목은 한 번 더
        got[s] = fetch_candles(s, years=2)
    cols = {s: pd.Series(c.close, index=pd.to_datetime(c.time)) for s, c in got.items() if c is not None}
    missing = sorted(s for s, c in got.items() if c is None)
    df = pd.DataFrame(cols).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    # ⚠️야후는 장중에 오늘 봉을 준다 — '최근 종가' 기준이므로 미국장이 닫히기 전(16:15 ET)엔 오늘 행을 뺀다.
    now_et = pd.Timestamp.now(tz="America/New_York")
    if len(df) and df.index[-1].date() == now_et.date() and (now_et.hour, now_et.minute) < (16, 15):
        df = df.iloc[:-1]
    # ⚠️한 종목만 하루 빠지면(거래정지·야후 빈 봉) MA60 이 60일 동안 NaN 이 된다 — 3일까지만 앞 값으로 채운다.
    df = df.ffill(limit=3)
    return time.time(), df, missing


def _closes_bundle() -> tuple[float, pd.DataFrame, list[str]]:
    # 빠진 종목이 있으면 캐시하지 않는다(다음 요청이 다시 받는다).
    return _cached("closes", _fetch_closes, cacheable=lambda v: not v[2])


def closes() -> pd.DataFrame:
    """종목별 일 종가(날짜 × 티커). 1시간 캐시."""
    return _closes_bundle()[1]


def spy_regime() -> pd.Series:
    """★2026-10-29 4회차: 시장 국면 — SPY 종가가 200일 이동평균 위인 날 True(그날까지의 정보만). 종목 날짜에 맞춘다."""
    def build():
        c = fetch_candles("SPY", years=2)
        if c is None:
            raise ValueError("SPY 일봉을 받지 못했습니다")
        spy = pd.Series(c.close, index=pd.to_datetime(c.time))
        return spy > spy.rolling(200).mean()
    reg = _cached(f"spy:{_closes_bundle()[0]}", build)
    return reg.reindex(closes().index).ffill().fillna(False).astype(bool)


def _available() -> list[tuple[str, str, tuple[str, ...], str]]:
    """가격이 하나라도 있는 바스켓만 — 전부 빠진 바스켓을 '보합'으로 세지 않는다."""
    cols = set(closes().columns)
    return [b for b in BASKETS if any(t in cols for t in b[2])]


# ── 지표 ──────────────────────────────────────────────────────────────────────

def member_indicator(px: pd.DataFrame, ind: str, n: int) -> pd.DataFrame:
    """종목마다 n일 지표. ret = 종가_t/종가_{t−n} − 1, maK = MA_K(t)/MA_K(t−n) − 1."""
    if ind == "ret":
        return px / px.shift(n) - 1
    k = int(ind[2:])
    ma = px.rolling(k, min_periods=k).mean()
    return ma / ma.shift(n) - 1


def basket_mean(df: pd.DataFrame, tickers: tuple[str, ...]) -> pd.Series:
    cols = [t for t in tickers if t in df.columns]
    return df[cols].mean(axis=1, skipna=True)


def basket_level(px: pd.DataFrame, tickers: tuple[str, ...]) -> pd.Series:
    """바스켓 가격 지수(동일 가중 — 하루 수익률 = 편입 종목 등락률 평균)."""
    cols = [t for t in tickers if t in px.columns]
    r = px[cols].pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0.0)
    return (1 + r).cumprod()


def bands(spread: pd.Series) -> tuple[pd.Series, pd.Series]:
    """직전 120 영업일(그날 제외)의 하위 10%·상위 10% 경계."""
    past = spread.shift(1).rolling(PCT_WINDOW, min_periods=PCT_MIN)
    return past.quantile(LO_Q), past.quantile(HI_Q)


@dataclass(frozen=True)
class Signal:
    date: pd.Timestamp
    side: str           # "hi"(A 비쌈 → B 매수) | "lo"(A 쌈 → A 매수)
    bought: str         # 바스켓 키
    entry: pd.Timestamp | None
    ret: float | None   # 진입 다음 hold 영업일 수익(아직 안 끝났으면 None)
    hit: bool | None


def spread_signals(spread: pd.Series, lo: pd.Series, hi: pd.Series, a: str, b: str,
                   lev: dict[str, pd.Series], hold: int, start: pd.Timestamp = START) -> list[Signal]:
    """경계를 **처음 넘는 날**만 신호. 진입 = 다음 영업일 종가, 같은 쌍은 보유 중 새 신호 무시."""
    idx = spread.index
    out: list[Signal] = []
    prev_state = None
    block_until = -1
    for i, d in enumerate(idx):
        s, l_, h_ = spread.iat[i], lo.iat[i], hi.iat[i]
        if any(map(lambda v: v is None or (isinstance(v, float) and math.isnan(v)), (s, l_, h_))):
            continue                     # 빈 날은 건너뛰되 상태는 지우지 않는다 — 빈칸 뒤 같은 꼬리를 '새 신호'로 세지 않게
        state = "hi" if s >= h_ else "lo" if s <= l_ else None
        fresh = state is not None and state != prev_state
        prev_state = state
        if not fresh or d < start or i <= block_until:
            continue
        bought = b if state == "hi" else a
        e, x = i + 1, i + 1 + hold
        if e >= len(idx):
            out.append(Signal(d, state, bought, None, None, None))
            continue
        if x >= len(idx):
            out.append(Signal(d, state, bought, idx[e], None, None))
            block_until = len(idx)
            continue
        lv = lev[bought]
        r = float(lv.iat[x] / lv.iat[e] - 1)
        out.append(Signal(d, state, bought, idx[e], r, r >= HIT))
        block_until = x
    return out


def baseline_hit(level: pd.Series, hold: int, start: pd.Timestamp = START) -> float | None:
    """같은 기간 아무 날 샀을 때 hold 일 뒤 +5% 이상일 확률(진입 = 다음 날 종가와 같은 방식)."""
    fwd = level.shift(-hold - 1) / level.shift(-1) - 1
    fwd = fwd[(fwd.index >= start)].dropna()
    return float((fwd >= HIT).mean()) if len(fwd) else None


def _ctx():
    px = closes()
    lev = {k: basket_level(px, ts) for k, _, ts, _ in _available()}
    ind_cache: dict[tuple[str, int], pd.DataFrame] = {}

    def ind(i, n):
        if (i, n) not in ind_cache:
            ind_cache[(i, n)] = member_indicator(px, i, n)
        return ind_cache[(i, n)]
    return px, lev, ind


def spread_detail(a: str, b: str, ind: str, n: int, hold: int) -> dict:
    """한 쌍·한 설정의 괴리 시계열 + 경계 + 신호(차트용)."""
    px, lev, indf = _ctx()
    if a not in lev or b not in lev:
        raise ValueError(f"가격이 없는 바스켓: {[k for k in (a, b) if k not in lev]}")
    df = indf(ind, n)
    spread = basket_mean(df, BASKET[a][1]) - basket_mean(df, BASKET[b][1])
    lo, hi = bands(spread)
    sigs = spread_signals(spread, lo, hi, a, b, lev, hold)
    view = spread.index >= START
    done = [s for s in sigs if s.hit is not None]
    base = {k: baseline_hit(lev[k], hold) for k in (a, b)}
    return {
        "a": a, "b": b, "ind": ind, "n": n, "hold": hold,
        "dates": [d.strftime("%Y-%m-%d") for d in spread.index[view]],
        "spread": _clean_list(spread[view]),
        "lo": _clean_list(lo[view]), "hi": _clean_list(hi[view]),
        "level_a": _clean_list(lev[a][view] / lev[a][view].iloc[0]),
        "level_b": _clean_list(lev[b][view] / lev[b][view].iloc[0]),
        "signals": [_sig_dict(s) for s in sigs],
        "stats": _stats(done, base),
        "now": {"spread": _f(spread.iloc[-1]), "lo": _f(lo.iloc[-1]), "hi": _f(hi.iloc[-1])},
    }


def leaderboard(hold: int, min_signals: int = 4, scope: str = "all") -> dict:
    """모든 쌍 × 지표 × n 의 hit ratio — 표본이 min_signals 이상인 것만 순위.

    ★2026-10-29 2회차: '같은 묶음(섹터·밸류체인) 쌍'과 '다른 묶음 쌍'을 따로 합산한다 — 괴리가 되돌아올 이유는
      비슷한 업종끼리 더 크다는 가설을 확인한다. scope = all | same | cross 로 순위 표를 거른다.
    """
    full = _leaderboard_full(hold, min_signals)
    rows = [r for r in full["rows"] if scope == "all" or (scope == "same") == r["same"]]
    ranked = sorted((r for r in rows if r["signals"] >= min_signals),
                    key=lambda r: (r["hit_ratio"] or 0, r["signals"], r["avg_ret"] or 0), reverse=True)
    live = [x for x in full["live"] if scope == "all" or (scope == "same") == x["same"]]
    return {**{k: v for k, v in full.items() if k not in ("rows", "live")}, "scope": scope,
            "check": spread_check(hold), "direction": direction_compare(hold),
            "eligible": len(ranked), "top": ranked[:30], "live": live[:20]}


def spread_check(hold: int) -> dict:
    """★2026-10-29 3회차 — 전략1 을 검증 기간(분석 기간 직전 1년)에 같은 규칙으로 돌린 합산 hit ratio vs 기준선."""
    def build():
        px, lev, indf = _ctx()
        def base_in(level):
            fwd = level.shift(-hold - 1) / level.shift(-1) - 1
            fwd = fwd[(fwd.index >= CHECK_START) & (fwd.index <= CHECK_END)].dropna()
            return float((fwd >= HIT).mean()) if len(fwd) else None
        base = {k: base_in(v) for k, v in lev.items()}
        acc = {"all": [0, 0, []], "same": [0, 0, []], "cross": [0, 0, []]}
        avail = _available()
        for ind, n in itertools.product(INDICATORS, NS):
            df = indf(ind, n)
            bm = {k: basket_mean(df, ts) for k, _, ts, _ in avail}
            for a, b in itertools.combinations([k for k, *_ in avail], 2):
                spread = bm[a] - bm[b]
                lo, hi = bands(spread)
                sigs = [g for g in spread_signals(spread, lo, hi, a, b, lev, hold, start=CHECK_START)
                        if g.date <= CHECK_END and g.hit is not None]
                kind = "same" if BASKET[a][2] == BASKET[b][2] else "cross"
                for k in ("all", kind):
                    acc[k][0] += len(sigs)
                    acc[k][1] += sum(1 for g in sigs if g.hit)
                    acc[k][2].extend(base[g.bought] for g in sigs if base[g.bought] is not None)
        return {"start": CHECK_START.strftime("%Y-%m-%d"), "end": CHECK_END.strftime("%Y-%m-%d"),
                **{k: {"signals": v[0], "hit": v[1] / v[0] if v[0] else None,
                       "baseline": float(np.mean(v[2])) if v[2] else None} for k, v in acc.items()}}
    return _cached(f"spcheck:{hold}:{_closes_bundle()[0]}", build)


def direction_compare(hold: int) -> list[dict]:
    """★2026-10-29 5회차 — 같은 신호에서 '뒤처진 쪽(되돌림)'과 '앞선 쪽(추세)'을 샀을 때를 두 기간에 비교."""
    def build():
        px, lev, indf = _ctx()
        avail = [k for k, *_ in _available()]

        def base_in(level, s, e):
            fwd = level.shift(-hold - 1) / level.shift(-1) - 1
            fwd = fwd[(fwd.index >= s) & (fwd.index <= e)].dropna()
            return float((fwd >= HIT).mean()) if len(fwd) else None

        out = []
        for pname, (s, e) in (("분석 기간", (START, px.index[-1])), ("검증 기간", (CHECK_START, CHECK_END))):
            base = {k: base_in(lev[k], s, e) for k in avail}
            acc = {"reversion": [0, 0, []], "momentum": [0, 0, []]}
            for ind, n in itertools.product(INDICATORS, NS):
                df = indf(ind, n)
                bm = {k: basket_mean(df, BASKET[k][1]) for k in avail}
                for a, b in itertools.combinations(avail, 2):
                    spread = bm[a] - bm[b]
                    lo, hi = bands(spread)
                    for g in spread_signals(spread, lo, hi, a, b, lev, hold, start=s):
                        if g.date > e or g.hit is None:
                            continue
                        other = a if g.bought == b else b
                        lv = lev[other]
                        i = lv.index.get_loc(g.entry)
                        mom_hit = bool(lv.iat[i + hold] / lv.iat[i] - 1 >= HIT)
                        for mode, bought, hit in (("reversion", g.bought, g.hit), ("momentum", other, mom_hit)):
                            acc[mode][0] += 1
                            acc[mode][1] += int(hit)
                            if base[bought] is not None:
                                acc[mode][2].append(base[bought])
            for mode, (n_, h_, bl_) in acc.items():
                out.append({"period": pname, "mode": mode, "signals": n_, "hit": h_ / n_ if n_ else None,
                            "baseline": float(np.mean(bl_)) if bl_ else None})
        return out
    return _cached(f"dir:{hold}:{_closes_bundle()[0]}", build)


def _leaderboard_full(hold: int, min_signals: int) -> dict:
    def build():
        px, lev, indf = _ctx()
        base = {k: baseline_hit(lev[k], hold) for k in lev}
        rows, live = [], []
        for ind, n in itertools.product(INDICATORS, NS):
            df = indf(ind, n)
            avail = _available()
            bm = {k: basket_mean(df, ts) for k, _, ts, _ in avail}
            for a, b in itertools.combinations([k for k, *_ in avail], 2):
                spread = bm[a] - bm[b]
                lo, hi = bands(spread)
                sigs = spread_signals(spread, lo, hi, a, b, lev, hold)
                done = [s for s in sigs if s.hit is not None]
                st = _stats(done, {a: base[a], b: base[b]})
                same = BASKET[a][2] == BASKET[b][2]
                rows.append({"a": a, "b": b, "ind": ind, "n": n, "same": same, **st})
                last = sigs[-1] if sigs else None
                if last is not None and last.ret is None and last.date >= spread.index[-3]:
                    live.append({"a": a, "b": b, "ind": ind, "n": n, "date": last.date.strftime("%Y-%m-%d"),
                                 "bought": last.bought, "side": last.side, "same": same,
                                 "hit_ratio": st["hit_ratio"], "signals": st["signals"]})
        def pool(rs):
            n_ = sum(r["signals"] for r in rs)
            return {"hit": sum(r["hits"] for r in rs) / n_ if n_ else None, "signals": n_,
                    "baseline": _f(np.average([r["baseline"] for r in rs if r["baseline"] is not None and r["signals"]],
                                              weights=[r["signals"] for r in rs if r["baseline"] is not None and r["signals"]]))
                    if any(r["signals"] for r in rs) else None}
        total = pool(rows)
        live.sort(key=lambda r: (-(r["hit_ratio"] or 0), -r["signals"]))
        return {"hold": hold, "configs": len(rows), "min_signals": min_signals,
                "pooled_hit": total["hit"], "pooled_signals": total["signals"],
                "baseline_avg": _f(np.nanmean([v for v in base.values() if v is not None])),
                "pooled": {"all": total, "same": pool([r for r in rows if r["same"]]),
                           "cross": pool([r for r in rows if not r["same"]])},
                "rows": rows, "live": live}
    return _cached(f"lbfull:{hold}:{min_signals}:{_closes_bundle()[0]}", build)


def _stats(done: list[Signal], base: dict[str, float | None]) -> dict:
    n = len(done)
    hits = sum(1 for s in done if s.hit)
    rets = [s.ret for s in done if s.ret is not None]
    b = [base[s.bought] for s in done if base.get(s.bought) is not None]
    bl = float(np.mean(b)) if b else None
    hr = hits / n if n else None
    return {"signals": n, "hits": hits, "hit_ratio": hr,
            "avg_ret": float(np.mean(rets)) if rets else None,
            "baseline": bl, "edge": (hr - bl) if hr is not None and bl is not None else None}


def _sig_dict(s: Signal) -> dict:
    return {"date": s.date.strftime("%Y-%m-%d"), "side": s.side, "bought": s.bought,
            "entry": s.entry.strftime("%Y-%m-%d") if s.entry is not None else None,
            "ret": s.ret, "hit": s.hit}


# ── 전략2: 웅덩이 ─────────────────────────────────────────────────────────────

def dip_masks(px: pd.Series) -> dict[str, pd.Series]:
    """조건이 **처음 성립한 날** True. down_k = k 일 연속 종가 하락, bb = 종가 < 20일 볼린저 하단(2σ)."""
    down = px < px.shift(1)
    out = {}
    for k in DOWN_STREAKS:
        streak = down.rolling(k).sum() == k
        out[f"down{k}"] = streak & ~streak.shift(1, fill_value=False)
    ma = px.rolling(BB_WINDOW).mean()
    sd = px.rolling(BB_WINDOW).std()
    below = px < ma - BB_SIGMA * sd
    out["bb"] = below & ~below.shift(1, fill_value=False)
    # ★2026-10-29 2회차: 두 조건이 겹친 날 — 볼린저 하단을 처음 깬 날에 이미 3일 이상 연속 하락 중
    out["bb_down3"] = out["bb"] & (down.rolling(3).sum() == 3)
    return out


DIP_LABELS = {"down3": "3일 연속 하락", "down4": "4일 연속 하락", "down5": "5일 연속 하락",
              "bb": "볼린저 하단(2σ) 이탈", "bb_down3": "볼린저 이탈 + 3일 연속 하락"}


def _dip_events(px: pd.Series, mask: pd.Series, hold: int,
                start: pd.Timestamp = START, end: pd.Timestamp | None = None) -> list[dict]:
    """조건 첫날 → 다음 영업일 종가 진입 → hold 일 뒤 종가. `ret_stop` 은 보유 중 −STOP 이하로 닫히면 그 종가에 판 수익."""
    idx = px.index
    vals = px.to_numpy()
    out, block = [], -1
    for i in np.flatnonzero(mask.to_numpy()):
        d = idx[i]
        if d < start or (end is not None and d > end) or i <= block:
            continue
        e, x = i + 1, i + 1 + hold
        if x >= len(idx):
            out.append({"date": d, "ret": None, "ret_stop": None})
            continue
        path = vals[e + 1 : x + 1] / vals[e] - 1
        hit_stop = np.flatnonzero(path <= -STOP)
        ret = float(vals[x] / vals[e] - 1)
        out.append({"date": d, "ret": ret, "ret_stop": float(path[hit_stop[0]]) if len(hit_stop) else ret})
        block = x
    return out


def dip_study() -> dict:
    """종목 기준·바스켓 기준 각각: 조건 × 보유기간별 평균 수익·승률·hit(+5%) vs 기준선, 바스켓별 분해, 지금 웅덩이."""
    def build():
        px = closes()
        series = {"stock": {t: px[t].dropna() for t in px.columns},
                  "basket": {k: basket_level(px, ts) for k, _, ts, _ in _available()}}
        owner = {t: k for k, _, ts, _ in BASKETS for t in ts}
        result = {}
        masks = {unit: {name: dip_masks(s) for name, s in ss.items()} for unit, ss in series.items()}
        for unit, ss in series.items():
            table, by_basket = [], {}
            for hold in HOLDS:
                fw_all = []
                for s in ss.values():
                    fw = (s.shift(-hold - 1) / s.shift(-1) - 1)[s.index >= START].dropna()
                    fw_all.extend(fw.tolist())
                base = _summ(fw_all)
                for cond in DIP_LABELS:
                    rets, stops = [], []
                    for name, s in ss.items():
                        ev = _dip_events(s, masks[unit][name][cond], hold)
                        r = [e["ret"] for e in ev if e["ret"] is not None]
                        rets.extend(r)
                        stops.extend(e["ret_stop"] for e in ev if e["ret_stop"] is not None)
                        if unit == "stock" and hold == 10 and r:
                            by_basket.setdefault(owner[name], {}).setdefault(cond, []).extend(r)
                        if unit == "basket" and hold == 10 and r:
                            by_basket.setdefault(name, {}).setdefault(cond, []).extend(r)
                    table.append({"cond": cond, "label": DIP_LABELS[cond], "hold": hold, **_summ(rets),
                                  "stop": _summ(stops), "base": base})
            result[unit] = {"table": table,
                            "by_basket": {k: {c: _summ(v) for c, v in d.items()} for k, d in by_basket.items()}}
        # 검증 기간(분석 기간 직전 1년) — 종목 기준만, 같은 규칙
        check = []
        stock = series["stock"]
        for hold in HOLDS:
            fw_all = []
            for s in stock.values():
                fw = (s.shift(-hold - 1) / s.shift(-1) - 1)
                fw_all.extend(fw[(fw.index >= CHECK_START) & (fw.index <= CHECK_END)].dropna().tolist())
            base = _summ(fw_all)
            for cond in DIP_LABELS:
                rets = []
                for name, s in stock.items():
                    ev = _dip_events(s, masks["stock"][name][cond], hold, start=CHECK_START, end=CHECK_END)
                    rets.extend(e["ret"] for e in ev if e["ret"] is not None)
                check.append({"cond": cond, "label": DIP_LABELS[cond], "hold": hold, **_summ(rets), "base": base})
        result["check"] = {"start": CHECK_START.strftime("%Y-%m-%d"), "end": CHECK_END.strftime("%Y-%m-%d"),
                           "table": check}
        # 시장 국면 필터 — SPY 가 200일선 위일 때만 산다. 기준선도 같은 날들로만 잰다(공정 비교). 종목 기준·10일 보유.
        reg = spy_regime()
        regime_rows = []
        for plabel, (ps, pe) in (("분석 기간", (START, px.index[-1])), ("검증 기간", (CHECK_START, CHECK_END))):
            for filt in (False, True):
                fw = []
                for s in stock.values():
                    x = s.shift(-11) / s.shift(-1) - 1
                    sel = (x.index >= ps) & (x.index <= pe)
                    if filt:
                        sel &= reg.reindex(x.index).fillna(False).to_numpy()
                    fw.extend(x[sel].dropna().tolist())
                base = _summ(fw)
                for cond in ("bb", "bb_down3"):
                    rets = []
                    for name, s in stock.items():
                        m = masks["stock"][name][cond]
                        if filt:
                            m = m & reg.reindex(m.index).fillna(False)
                        ev = _dip_events(s, m, 10, start=ps, end=pe)
                        rets.extend(e["ret"] for e in ev if e["ret"] is not None)
                    regime_rows.append({"period": plabel, "filter": filt, "cond": cond, "label": DIP_LABELS[cond],
                                        **_summ(rets), "base": base})
        result["regime"] = regime_rows
        # 지금 웅덩이 — 최근 3 영업일 안에 조건이 처음 성립한 종목
        recent = []
        last3 = px.index[-3:]
        for t in px.columns:
            s = px[t].dropna()
            if s.empty:
                continue
            m = dip_masks(s)
            hits = [c for c in DIP_LABELS if bool(m[c].loc[m[c].index.isin(last3)].any())]
            if hits:
                recent.append({"ticker": t, "basket": owner.get(t), "conds": hits,
                               "chg5": _f(s.iloc[-1] / s.iloc[-6] - 1) if len(s) > 6 else None})
        recent.sort(key=lambda r: (r["chg5"] or 0))
        return {**result, "recent": recent, "as_of": px.index[-1].strftime("%Y-%m-%d")}
    return _cached(f"dip3:{_closes_bundle()[0]}", build)


def _summ(rets: list[float]) -> dict:
    if not rets:
        return {"n": 0, "avg": None, "med": None, "win": None, "hit": None}
    a = np.asarray(rets)
    return {"n": int(len(a)), "avg": float(a.mean()), "med": float(np.median(a)),
            "win": float((a > 0).mean()), "hit": float((a >= HIT).mean())}


def meta() -> dict:
    _, px, missing = _closes_bundle()
    return {
        "missing": missing,
        "start": START.strftime("%Y-%m-%d"), "as_of": px.index[-1].strftime("%Y-%m-%d"),
        "baskets": [{"key": k, "name": n, "tickers": list(ts), "group": g} for k, n, ts, g in BASKETS],
        "indicators": INDICATORS, "ns": list(NS), "holds": list(HOLDS), "hit": HIT,
        "pct": {"window": PCT_WINDOW, "lo": LO_Q, "hi": HI_Q},
    }


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _clean_list(s: pd.Series) -> list:
    return [_f(v) for v in s.tolist()]
