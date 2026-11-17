"""바스켓 대 바스켓 괴리 백테스트 — 회차별 개선 → storage/research/투자전략벡테스트결과.html

★2026-10-28 사용자 요청
  · 보유 2개월(42거래일) 승률로 잰다. 페어 트레이딩 관점: 괴리 = 바스켓 A 수익률 − 바스켓 B 수익률.
    괴리가 경계를 넘으면 한쪽 바스켓을 **산다**(롱 온리). 바스켓 = 1~3종목, 하루 수익률 = 종목 등락률 평균.
    괴리 통계는 2020-05 이후만 쓴다. 결과는 ASD-STE100 문체로 보고서에 쓴다.
  · "회차마다 한계를 찾고, 큰 틀은 유지하되 개선해서 실제 투자 의사결정에 쓸 전략으로 완성" —
    ROUNDS 에 회차를 하나씩 더한다. 회차마다 (발견한 한계 → 바꾼 것 → 결과 → 판정)을 보고서에 남긴다.

공통 정의(모든 회차가 같다 — '큰 틀'):
  · 괴리 G_t(L) = A 의 최근 L 거래일 누적 로그수익 − B 의 같은 값.
  · z_t = (G_t − 평균) / 표준편차, 평균·표준편차는 2020-05-01 ~ t(확장 창). 미래를 쓰지 않는다.
  · 신호 |z| ≥ k → 다음 거래일 종가에 한쪽을 사고 42거래일 뒤 종가에 판다. 보유 중 같은 페어의 새 신호는 무시.
  · 승리 = 산 바스켓 보유 수익 > 0. 기준선 = 같은 바스켓을 같은 기간 아무 날 샀을 때의 승률.
  · 표본 내(IS) 2020-11~2023-12 진입 / 표본 외(OOS) 2024-01~. 판단은 OOS 로 한다.
⚠️OHLCV 는 지금 상장된 종목만 있다. 수수료·세금 없음. 바스켓은 2026 년 지식으로 골랐다.

실행: .venv/bin/python scripts/pair_backtest.py
"""
from __future__ import annotations

import html
import itertools
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "storage" / "ohlcv" / "ohlcv.duckdb"
OUT_DIR = ROOT / "storage" / "research"
REPORT = OUT_DIR / "투자전략벡테스트결과.html"
LOG = OUT_DIR / "pair_backtest_runs.json"

HOLD = 42
STATS_START = pd.Timestamp("2020-05-01")
MIN_STATS = 120
IS_END = pd.Timestamp("2023-12-31")
PERMUTATIONS = 2000
SEED = 7

# 채택 기준 — 이 넷을 모두 넘어야 '실전 후보'로 쓴다.
ADOPT = {"oos_edge": 0.05, "oos_p": 0.10, "oos_n": 30, "is_edge": 0.0}

# ── 바스켓 ────────────────────────────────────────────────────────────────────
# 1회차 — 서로 다른 테마 26개(사용자 예시 포함)
THEMES: list[tuple[str, str, tuple[str, ...]]] = [
    ("HYPER3", "하이퍼스케일러 3", ("MSFT", "GOOGL", "AMZN")),
    ("BIGTECH_EX", "빅테크(예시)", ("AAPL", "GOOGL", "MSFT")),
    ("GPU1", "GPU 1대장", ("NVDA",)),
    ("GPU_CHAL", "AI 가속기 도전자", ("AMD", "AVGO", "MRVL")),
    ("MEMORY", "메모리", ("MU",)),
    ("FAB", "파운드리·노광", ("TSM", "ASML")),
    ("SEMI_EQ", "반도체 장비 3", ("AMAT", "LRCX", "KLAC")),
    ("LEGACY_SEMI", "레거시 반도체", ("INTC", "TXN", "QCOM")),
    ("AI_SERVER", "AI 서버·네트워크", ("ANET", "SMCI", "DELL")),
    ("POWER_GEAR", "전력 장비", ("VRT", "ETN", "PWR")),
    ("POWER_GEN", "전력 생산", ("VST", "NRG", "CCJ")),
    ("GLP1", "비만약 2강", ("LLY", "NVO")),
    ("BIO_LEAD", "바이오 대장", ("LLY", "NVO", "JNJ")),
    ("PHARMA_VAL", "빅파마 가치", ("MRK", "PFE", "ABBV")),
    ("CRYPTO_MINER", "크립토 채굴·보유", ("MSTR", "MARA", "RIOT")),
    ("PENNY", "동전주·투기 성장", ("PLUG", "FCEL", "NIO")),
    ("MEME", "밈 주식", ("GME", "AMC")),
    ("DEFENSIVE", "방어 소비재", ("KO", "PG", "WMT")),
    ("BANKS", "대형 은행", ("JPM", "BAC", "GS")),
    ("OIL", "석유 메이저", ("XOM", "CVX", "OXY")),
    ("DEFENSE", "방산", ("LMT", "NOC", "RTX")),
    ("SAAS", "SaaS 3", ("CRM", "NOW", "ADBE")),
    ("CYBER", "사이버보안", ("CRWD", "PANW", "FTNT")),
    ("TSLA", "테슬라", ("TSLA",)),
    ("GOLD", "금", ("GLD",)),
    ("STREAM", "스트리밍·미디어", ("NFLX", "SPOT", "DIS")),
]
THEME = {k: (n, ts) for k, n, ts in THEMES}

# 2회차~ — 같은 업종 안의 맞수(대체재). 괴리가 벌어졌다 돌아올 경제적 이유가 있는 짝.
RIVALS: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("GPU", ("NVDA",), ("AMD",)),
    ("GLP-1", ("LLY",), ("NVO",)),
    ("클라우드 플랫폼", ("MSFT",), ("GOOGL",)),
    ("클라우드 1·2위", ("AMZN",), ("MSFT",)),
    ("음료", ("KO",), ("PEP",)),
    ("카드 결제망", ("V",), ("MA",)),
    ("주택 개량", ("HD",), ("LOW",)),
    ("석유 메이저", ("XOM",), ("CVX",)),
    ("상업 은행", ("JPM",), ("BAC",)),
    ("투자 은행", ("GS",), ("MS",)),
    ("방산 기체", ("LMT",), ("NOC",)),
    ("대형 유통", ("COST",), ("WMT",)),
    ("사이버보안", ("CRWD",), ("PANW",)),
    ("업무 SaaS", ("CRM",), ("NOW",)),
    ("반도체 장비", ("AMAT",), ("LRCX",)),
    ("철도", ("UNP",), ("CSX",)),
    ("택배", ("UPS",), ("FDX",)),
    ("항공", ("DAL",), ("UAL",)),
    ("온라인 여행", ("BKNG",), ("EXPE",)),
    ("중장비", ("CAT",), ("DE",)),
    ("빅파마", ("MRK",), ("PFE",)),
    ("통신", ("T",), ("VZ",)),
    ("메모리·스토리지", ("MU",), ("WDC",)),
    ("아날로그 반도체", ("TXN",), ("ADI",)),
    ("의료기기", ("MDT",), ("ABT",)),
    ("생명과학 장비", ("TMO",), ("DHR",)),
    ("유틸리티", ("NEE",), ("DUK",)),
    ("도료", ("SHW",), ("PPG",)),
    ("산업 가스", ("LIN",), ("APD",)),
    ("GPU 1등 vs 도전자", ("NVDA",), ("AMD", "AVGO", "MRVL")),
    ("장비 vs 파운드리", ("AMAT", "LRCX", "KLAC"), ("TSM", "ASML")),
    ("전력 장비 vs 생산", ("VRT", "ETN", "PWR"), ("VST", "NRG", "CCJ")),
    ("비만약 vs 빅파마", ("LLY", "NVO"), ("MRK", "PFE", "ABBV")),
]


def label_of(ts: tuple[str, ...]) -> str:
    return "+".join(ts)


# ── 회차 정의 ─────────────────────────────────────────────────────────────────

@dataclass
class Round:
    no: int
    title: str
    limit: str                      # 직전 회차에서 찾은 한계
    change: str                     # 이번에 바꾼 것
    kind: str                       # "search"(전수 탐색 후 상위 고르기) | "rule"(미리 정한 규칙 1개)
    pairs: str                      # "themes" | "rivals"
    L: tuple[int, ...] = (60,)
    k: tuple[float, ...] = (2.0,)
    modes: tuple[str, ...] = ("reversion",)
    trend_filter: int | None = None  # 산 쪽 바스켓이 N일 이동평균 위일 때만 산다
    dd_filter: float | None = None   # 산 쪽 바스켓이 1년 고점 대비 이만큼(예: 0.2) 이상 빠졌을 때만 산다
    extra: dict = field(default_factory=dict)


ROUNDS: list[Round] = [
    Round(
        1, "교차 테마 전수 탐색",
        limit="(첫 회차)",
        change="테마 바스켓 26개의 모든 짝(325쌍) × 괴리 창 20·60·120일 × 경계 ±1.5·2.0·2.5 × 역추세·추세 = 5,850 조합에서 표본 내 상위 20개를 고른다.",
        kind="search", pairs="themes", L=(20, 60, 120), k=(1.5, 2.0, 2.5), modes=("reversion", "momentum"),
    ),
    Round(
        2, "같은 업종 맞수 · 미리 정한 규칙 1개",
        limit="① 서로 다른 테마끼리는 괴리가 되돌아올 이유가 없다. ② 5,850 조합에서 1등을 고르면 운이 섞인다(표본 외 순위상관 −0.01). ③ 절대 승률은 오르는 바스켓을 사기만 해도 높다 — 기준선 대비로 봐야 한다.",
        change="같은 업종 맞수 33쌍(대체재)만 쓴다. 규칙을 미리 하나로 정한다: 60일 괴리, ±2.0, 뒤처진 쪽 매수. 모든 짝의 거래를 합쳐 한 전략으로 평가하고, 기준선 대비 차이와 순열 검정으로 판단한다.",
        kind="rule", pairs="rivals", L=(60,), k=(2.0,), modes=("reversion",),
    ),
    Round(
        3, "같은 업종 맞수 · 추세(앞선 쪽 매수)",
        limit="① 맞수 역추세는 표본 내·외 모두 기준선과 같다(표본 외 −4%p). 산 쪽이 맞수를 이긴 비율 49% — 2개월 안에 괴리가 되돌아오지 않는다. ② 민감도 9칸 중 표본 외 +3%p 넘는 칸이 없다 — 창·경계 문제가 아니다.",
        change="방향을 뒤집는다. 학계의 중기 모멘텀(6개월 형성)에 맞춰 120일 괴리, ±1.5, 앞선 쪽 매수로 미리 정한다.",
        kind="rule", pairs="rivals", L=(120,), k=(1.5,), modes=("momentum",),
    ),
    Round(
        4, "맞수 역추세 + 200일선 필터",
        limit="① 추세 방향도 표본 내·외 모두 기준선 이하(표본 외 −4%p). 두 방향 모두 '산 쪽이 맞수를 이긴 비율'이 47~49% — 맞수끼리의 괴리는 2개월 상대 성과를 알려 주지 않는다. ② 롱 온리 절대 승률은 괴리보다 시장 국면이 정한다(손실이 2022 년에 몰림).",
        change="표본 내 성적이 나았던 2회차 규칙(60일, ±2.0, 뒤처진 쪽)을 유지하고, 산 쪽 바스켓이 200 거래일 이동평균 위일 때만 산다(떨어지는 칼날 피하기). 필터 기간은 관행값 200일로 미리 정한다.",
        kind="rule", pairs="rivals", L=(60,), k=(2.0,), modes=("reversion",), trend_filter=200,
    ),
    Round(
        5, "맞수 역추세 + 절대 낙폭 조건",
        limit="① 200일선 필터는 오히려 나빠졌다(표본 외 −14%p) — 아직 덜 빠진 뒤처진 쪽을 사면 더 빠진다. ② 즉 효과가 있다면 '상대 괴리'보다 '절대 할인'에서 온다(지수 분석에서도 고점 대비 −20% 이하 매수의 승률이 높았다).",
        change="2회차 규칙에 '산 쪽 바스켓이 1년 고점 대비 −20% 이하' 조건을 더한다. ⚠️이 가설은 4회차 표본 외 결과를 본 뒤에 세웠다 — 표본 외가 완전히 깨끗하지 않다.",
        kind="rule", pairs="rivals", L=(60,), k=(2.0,), modes=("reversion",), dd_filter=0.20,
    ),
    Round(
        6, "통제 실험 — 낙폭 조건만",
        limit="① 5회차는 표본 내 +10%p 지만 표본 외 +1%p 로 기각. ② 그런데 민감도 9칸 전부가 표본 내·외 모두 플러스다(표본 외 +1~+14%p) — 효과는 있을 수 있다. ③ 그 효과가 '괴리' 덕인지 '−20% 낙폭' 덕인지 모른다.",
        change="괴리 조건을 빼고 낙폭 조건만 남긴 통제 전략을 같은 종목(맞수 종목들)으로 돌린다. 이것보다 나아야 괴리가 일을 한 것이다.",
        kind="control", pairs="rivals", dd_filter=0.20,
    ),
    Round(
        7, "괴리 창 앙상블 + 낙폭 조건",
        limit="① 5회차는 창 하나(60일)·경계 하나(±2.0)를 미리 골라 그 칸의 운에 좌우됐다. 민감도는 대부분 칸이 플러스였다.",
        change="창을 고르지 않는다: 20·60·120일 괴리 중 하나라도 |z| ≥ 1.5 이면 신호(가장 큰 |z| 의 방향). 뒤처진 쪽이 1년 고점 대비 −20% 이하일 때만 산다.",
        kind="rule", pairs="rivals", L=(20, 60, 120), k=(1.5,), modes=("reversion",), dd_filter=0.20,
        extra={"ensemble": True},
    ),
    Round(
        8, "괴리를 '고르기'로 쓰기 — 낙폭 매수 분해",
        limit="① 7회차는 채택 기준은 넘지만 표본 외 +7%p 로, 괴리를 뺀 6회차(+11%p)보다 못하다 — 괴리 조건이 효과를 더하지 않았다. ② 그래도 괴리가 '같은 낙폭 후보 중 무엇을 살지' 고르는 데 쓸모 있는지는 아직 모른다.",
        change="6회차의 낙폭 매수를 그날 '맞수보다 괴리로 뒤처짐' 여부로 둘로 나눠 비교한다. 괴리 있음 쪽 승률이 괴리 없음 쪽보다 높아야 괴리가 쓸모 있다.",
        kind="split", pairs="rivals", L=(20, 60, 120), k=(1.5,), dd_filter=0.20,
    ),
    Round(
        9, "생존 편향 스트레스 테스트 — 고변동·투기 바스켓",
        limit="① 낙폭 매수 효과(6·8회차)는 '지금 살아남은 우량 대형주' 목록에서 나왔다. 2023 년 SVB·퍼스트리퍼블릭처럼 −20% 뒤 더 빠져 사라진 종목은 데이터에 없다. ② 괴리는 고르기에서 +1~2%p 만 더한다(유의하지 않음).",
        change="같은 낙폭 규칙(−20%, 2개월)을 망가지기 쉬운 바스켓 7개(동전주·밈·크립토 채굴·테슬라·AI 서버·전력 생산·레거시 반도체)에 돌린다. 여기서도 기준선보다 낫다면 효과가 우량주 생존 편향만은 아니다.",
        kind="control", pairs="themes", dd_filter=0.20, extra={"sides": "speculative"},
    ),
]


# ── 데이터 ────────────────────────────────────────────────────────────────────

def load_prices(tickers: list[str]) -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        q = ",".join("?" for _ in tickers)
        df = con.execute(
            f"SELECT ticker, date, adj_close FROM ohlcv WHERE ticker IN ({q}) AND date >= DATE '2019-01-01' "
            f"UNION ALL SELECT ticker, date, adj_close FROM wls_ohlcv WHERE ticker IN ({q}) AND date >= DATE '2019-01-01' "
            f"AND ticker NOT IN (SELECT DISTINCT ticker FROM ohlcv WHERE ticker IN ({q}))",
            tickers * 3,
        ).df()
    finally:
        con.close()
    px = df.drop_duplicates(["ticker", "date"]).pivot(index="date", columns="ticker", values="adj_close")
    px.index = pd.to_datetime(px.index)
    return px.sort_index()


class Market:
    """가격 → 바스켓 로그 레벨(캐시), 진입일 범위, 무작위 진입 기준."""

    def __init__(self, px: pd.DataFrame):
        self.rets = px.pct_change(fill_method=None)
        self.dates = px.index
        self.n = len(self.dates)
        self.last_entry = self.n - 1 - HOLD
        self.stats_mask = np.asarray(self.dates >= STATS_START)
        self.first_signal = self.dates[self.stats_mask][MIN_STATS]
        self._lv: dict[tuple[str, ...], np.ndarray] = {}
        self._ma: dict[tuple, np.ndarray] = {}
        idx = np.arange(self.last_entry + 1)
        d = self.dates[: self.last_entry + 1]
        self.is_days = idx[(d >= self.first_signal) & (d <= IS_END)]
        self.oos_days = idx[d > IS_END]

    def level(self, ts: tuple[str, ...]) -> np.ndarray:
        if ts not in self._lv:
            r = self.rets[list(ts)].mean(axis=1, skipna=True).fillna(0.0)
            self._lv[ts] = np.log1p(r).cumsum().to_numpy()
        return self._lv[ts]

    def fwd(self, ts: tuple[str, ...]) -> np.ndarray:
        """진입일 i 별 42거래일 보유 수익(마지막 진입일까지)."""
        lv = self.level(ts)
        return np.expm1(lv[HOLD:] - lv[:-HOLD])[: self.last_entry + 1]

    def dd_ok(self, ts: tuple[str, ...], depth: float) -> np.ndarray:
        """그날 레벨이 직전 252 거래일(그날 포함) 최고치 대비 depth 이상 빠졌나."""
        key = ("dd", ts, depth)
        if key not in self._ma:
            lv = pd.Series(self.level(ts))
            peak = lv.rolling(252, min_periods=60).max()
            self._ma[key] = (np.expm1(lv - peak) <= -depth).to_numpy()
        return self._ma[key]

    def ma_ok(self, ts: tuple[str, ...], window: int) -> np.ndarray:
        """그날 종가 레벨이 window 일 이동평균 위인가(그날까지의 정보만)."""
        key = (ts, window)
        if key not in self._ma:
            lv = pd.Series(self.level(ts))
            self._ma[key] = (lv > lv.rolling(window).mean()).to_numpy()
        return self._ma[key]


def zscores(m: Market, la: np.ndarray, lb: np.ndarray, L: int) -> np.ndarray:
    g = np.full(len(la), np.nan)
    g[L:] = (la[L:] - la[:-L]) - (lb[L:] - lb[:-L])
    v = pd.Series(np.where(m.stats_mask & ~np.isnan(g), g, np.nan))
    cnt = v.expanding().count().to_numpy()
    z = (g - v.expanding().mean().to_numpy()) / v.expanding().std().to_numpy()
    z[(cnt < MIN_STATS) | ~m.stats_mask] = np.nan
    return z


@dataclass
class Trade:
    pair: str
    signal: int
    entry: int
    bought: tuple[str, ...]
    other: tuple[str, ...]
    ret: float
    rel: float
    z: float


def simulate(m: Market, pair: str, A, B, L, k, mode, trend_filter=None, dd_filter=None) -> list[Trade]:
    la, lb = m.level(A), m.level(B)
    if isinstance(L, tuple):
        # 앙상블 — 여러 괴리 창 중 그날 |z| 가 가장 큰 것을 쓴다(창 하나를 고르지 않는다)
        zs = np.vstack([zscores(m, la, lb, x) for x in L])
        absz = np.where(np.isnan(zs), -1, np.abs(zs))
        pick = absz.argmax(axis=0)
        z = zs[pick, np.arange(zs.shape[1])]
    else:
        z = zscores(m, la, lb, L)
    okA = np.ones(m.n, bool)
    okB = np.ones(m.n, bool)
    if trend_filter:
        okA, okB = okA & m.ma_ok(A, trend_filter), okB & m.ma_ok(B, trend_filter)
    if dd_filter:
        okA, okB = okA & m.dd_ok(A, dd_filter), okB & m.dd_ok(B, dd_filter)
    out, i = [], 0
    while i < m.n:
        zi = z[i]
        if np.isnan(zi) or abs(zi) < k:
            i += 1
            continue
        e = i + 1
        if e > m.last_entry:
            break
        a_lags = zi < 0
        buy_a = a_lags if mode == "reversion" else not a_lags
        if not (okA[i] if buy_a else okB[i]):
            i += 1                       # 추가 조건이 안 맞으면 이날은 사지 않는다(다음 날 다시 본다)
            continue
        Bt, Ot = (A, B) if buy_a else (B, A)
        lB, lO = (la, lb) if buy_a else (lb, la)
        x = e + HOLD
        r = math.expm1(lB[x] - lB[e])
        out.append(Trade(pair, i, e, Bt, Ot, r, r - math.expm1(lO[x] - lO[e]), float(zi)))
        i = x
    return out


# ── 평가 ──────────────────────────────────────────────────────────────────────

def wilson(w: int, n: int, z: float = 1.96) -> float | None:
    if n == 0:
        return None
    p = w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    mg = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - mg) / d)


def evaluate(m: Market, trades: list[Trade], rng: np.random.Generator, perms: int = PERMUTATIONS) -> dict:
    """IS/OOS 별: 거래 수·승률·평균 수익·맞수 대비 승률·기준선·차이·순열 p."""
    out = {}
    for part, days in (("is", m.is_days), ("oos", m.oos_days)):
        dayset = set(days.tolist())
        ts = [t for t in trades if t.entry in dayset]
        n = len(ts)
        if n == 0:
            out[part] = {"n": 0}
            continue
        wins = sum(t.ret > 0 for t in ts)
        fw = {t.bought: m.fwd(t.bought) for t in ts}
        # 기준선 — 산 바스켓을 같은 기간 아무 날 샀을 때의 승률(거래마다 그 바스켓 기준을 평균)
        base = float(np.mean([(fw[t.bought][days] > 0).mean() for t in ts]))
        # 순열 검정 — 거래마다 같은 바스켓·같은 기간에서 진입일을 무작위로 뽑아 승률 분포를 만든다
        null = np.zeros(perms)
        for t in ts:
            null += (fw[t.bought][rng.choice(days, size=perms)] > 0)
        null /= n
        win = wins / n
        out[part] = {
            "n": n, "wins": wins, "win": win, "lower": wilson(wins, n),
            "avg": float(np.mean([t.ret for t in ts])),
            "med": float(np.median([t.ret for t in ts])),
            "worst": float(min(t.ret for t in ts)),
            "p10": float(np.percentile([t.ret for t in ts], 10)),
            "rel_win": sum(t.rel > 0 for t in ts) / n,
            "avg_rel": float(np.mean([t.rel for t in ts])),
            "base": base, "edge": win - base,
            "p": float((null >= win).mean()),
        }
    return out


def run_round(m: Market, rd: Round, rng) -> dict:
    if rd.pairs == "themes":
        pairs = [(f"{THEME[a][0]} − {THEME[b][0]}", THEME[a][1], THEME[b][1])
                 for a, b in itertools.combinations([k for k, *_ in THEMES], 2)]
    else:
        pairs = [(f"{name} ({label_of(A)} vs {label_of(B)})", A, B) for name, A, B in RIVALS]

    if rd.kind == "search":
        # 조합마다 IS 성적 → 상위 20 을 골라 그 거래를 합쳐 본다(고르기가 표본 외에서도 통하나)
        cand = []
        for (name, A, B), L, k, mode in itertools.product(pairs, rd.L, rd.k, rd.modes):
            tr = simulate(m, name, A, B, L, k, mode, rd.trend_filter, rd.dd_filter)
            is_tr = [t for t in tr if m.first_signal <= m.dates[t.entry] <= IS_END]
            if len(is_tr) < 6:
                continue
            w = sum(t.ret > 0 for t in is_tr)
            cand.append((wilson(w, len(is_tr)), w / len(is_tr), name, L, k, mode, tr))
        cand.sort(key=lambda c: (c[0], c[1]), reverse=True)
        top = cand[:20]
        trades = [t for c in top for t in c[6]]
        best = top[0] if top else None
        return {
            "round": rd, "pairs": len(pairs), "eval": evaluate(m, trades, rng), "trades": trades,
            "rule_text": (f"상위 20 조합 묶음 (1등: {best[2]} · {best[3]}일 · ±{best[4]} · "
                          f"{'역추세' if best[5] == 'reversion' else '추세'})" if best else "—"),
            "chosen": [(c[2], c[3], c[4], c[5]) for c in top],
        }

    if rd.kind == "control":
        sides = sorted({ts for _, A, B in pairs for ts in (A, B)})
        if rd.extra.get("sides") == "speculative":
            sides = [THEME[k][1] for k in ("PENNY", "MEME", "CRYPTO_MINER", "TSLA", "AI_SERVER", "POWER_GEN", "LEGACY_SEMI")]
        trades = []
        for ts in sides:
            ok = m.dd_ok(ts, rd.dd_filter)
            lv = m.level(ts)
            i = int(np.argmax(m.stats_mask)) + MIN_STATS
            while i < m.n:
                if not ok[i]:
                    i += 1
                    continue
                e = i + 1
                if e > m.last_entry:
                    break
                r = math.expm1(lv[e + HOLD] - lv[e])
                trades.append(Trade(f"(통제) {label_of(ts)}", i, e, ts, ts, r, 0.0, 0.0))
                i = e + HOLD
        return {"round": rd, "pairs": len(sides), "eval": evaluate(m, trades, rng), "trades": trades,
                "rule_text": (f"괴리 조건 없음 · {'고변동·투기 바스켓' if rd.extra.get('sides') == 'speculative' else '맞수 종목'} {len(sides)}개 "
                              f"각각 1년 고점 대비 −{rd.dd_filter:.0%} 이하이면 매수"), "chosen": [], "sides": sides}

    if rd.kind == "split":
        # 통제(낙폭만) 매수를 '그날 맞수보다 괴리로 뒤처졌나'로 둘로 나눈다 — 괴리가 고르기에 쓸모 있나
        lag_any: dict[tuple[str, ...], np.ndarray] = {}
        for _, A, B in pairs:
            la, lb = m.level(A), m.level(B)
            zs = np.vstack([zscores(m, la, lb, x) for x in rd.L])
            a_lag = np.nanmin(np.where(np.isnan(zs), np.inf, zs), axis=0) <= -rd.k[0]     # A 가 뒤처짐
            b_lag = np.nanmax(np.where(np.isnan(zs), -np.inf, zs), axis=0) >= rd.k[0]     # B 가 뒤처짐
            lag_any[A] = lag_any.get(A, np.zeros(m.n, bool)) | a_lag
            lag_any[B] = lag_any.get(B, np.zeros(m.n, bool)) | b_lag
        base_rd = Round(0, "", "", "", "control", "rivals", dd_filter=rd.dd_filter)
        ctrl = run_round(m, base_rd, rng)["trades"]
        withz = [t for t in ctrl if lag_any[t.bought][t.signal]]
        without = [t for t in ctrl if not lag_any[t.bought][t.signal]]
        ev_with, ev_without = evaluate(m, withz, rng), evaluate(m, without, rng)
        # 동시 후보 수(시장 전체 하락의 대리 지표)별 성적 — 국면 위험
        sides = sorted(lag_any)
        cnt = np.sum([m.dd_ok(ts, rd.dd_filter) for ts in sides], axis=0)
        regime = []
        for lo, hi, lab in ((1, 4, "1~4"), (5, 9, "5~9"), (10, 15, "10~15"), (16, 999, "16 이상")):
            row = {"label": lab}
            for part, cond in (("is", lambda d: d <= IS_END), ("oos", lambda d: d > IS_END)):
                ts = [t for t in ctrl if lo <= cnt[t.signal] <= hi and cond(m.dates[t.entry])]
                row[part] = {"n": len(ts), "win": (sum(t.ret > 0 for t in ts) / len(ts)) if ts else None,
                             "avg": float(np.mean([t.ret for t in ts])) if ts else None}
            regime.append(row)
        now_count = int(cnt[-1])
        return {"round": rd, "pairs": len(pairs), "eval": ev_with, "eval_without": ev_without, "trades": withz,
                "lag_any": lag_any, "pair_defs": pairs, "regime": regime, "now_count": now_count, "n_sides": len(sides),
                "rule_text": f"낙폭 −{rd.dd_filter:.0%} 매수 중 '맞수보다 괴리로 뒤처짐(20·60·120일 중 하나 z ≤ −{rd.k[0]})'인 것만", "chosen": []}

    # rule — 미리 정한 규칙 하나. 민감도(창·경계 바꿔 보기)는 참고로만.
    L0 = rd.L if rd.extra.get("ensemble") else rd.L[0]
    k0, mode0 = rd.k[0], rd.modes[0]
    trades = [t for name, A, B in pairs for t in simulate(m, name, A, B, L0, k0, mode0, rd.trend_filter, rd.dd_filter)]
    ev = evaluate(m, trades, rng)
    sens = {}
    for L, k in itertools.product((20, 60, 120), (1.5, 2.0, 2.5)):
        tr = [t for name, A, B in pairs for t in simulate(m, name, A, B, L, k, mode0, rd.trend_filter, rd.dd_filter)]
        sens[f"{L}|{k}"] = evaluate(m, tr, rng, perms=300)
    per_pair = []
    for name, *_ in pairs:
        ts = [t for t in trades if t.pair == name]
        o = [t for t in ts if m.dates[t.entry] > IS_END]
        per_pair.append({"pair": name, "n": len(ts), "win": (sum(t.ret > 0 for t in ts) / len(ts)) if ts else None,
                         "oos_n": len(o), "oos_win": (sum(t.ret > 0 for t in o) / len(o)) if o else None,
                         "avg": float(np.mean([t.ret for t in ts])) if ts else None})
    Ltxt = "·".join(map(str, L0)) + "일 중 하나" if isinstance(L0, tuple) else f"{L0}일"
    text = (f"맞수 {len(pairs)}쌍 · {Ltxt} 괴리 · ±{k0} · {'뒤처진 쪽' if mode0 == 'reversion' else '앞선 쪽'} 매수"
            + (f" · 산 쪽이 {rd.trend_filter}일선 위일 때만" if rd.trend_filter else "")
            + (f" · 산 쪽이 1년 고점 대비 −{rd.dd_filter:.0%} 이하일 때만" if rd.dd_filter else ""))
    return {"round": rd, "pairs": len(pairs), "eval": ev, "trades": trades, "sens": sens,
            "per_pair": per_pair, "pair_defs": pairs, "rule_text": text}


def adopted(ev: dict) -> bool:
    o, i = ev.get("oos", {}), ev.get("is", {})
    return bool(o.get("n", 0) >= ADOPT["oos_n"] and o.get("edge", -1) >= ADOPT["oos_edge"]
                and o.get("p", 1) <= ADOPT["oos_p"] and i.get("edge", -1) > ADOPT["is_edge"])


def live_signals(m: Market, res: dict) -> list[dict]:
    rd: Round = res["round"]
    if rd.kind == "split":
        out = []
        for ts in sorted(res["lag_any"]):
            if m.dd_ok(ts, rd.dd_filter)[-1]:
                lv = pd.Series(m.level(ts))
                dd = float(np.expm1(lv.iloc[-1] - lv.iloc[-252:].max()))
                out.append({"pair": f"1년 고점 대비 {dd * 100:.0f}%", "buy": label_of(ts), "z": 0.0,
                            "trend_ok": True, "lag": bool(res["lag_any"][ts][-1]), "dd": dd})
        return sorted(out, key=lambda x: (not x["lag"], x["dd"]))
    if rd.kind != "rule":
        return []
    out = []
    for name, A, B in res["pair_defs"]:
        if rd.extra.get("ensemble"):
            zz = [zscores(m, m.level(A), m.level(B), x)[-1] for x in rd.L]
            zz = [v for v in zz if not np.isnan(v)]
            z = max(zz, key=abs) if zz else np.nan
        else:
            z = zscores(m, m.level(A), m.level(B), rd.L[0])[-1]
        if np.isnan(z) or abs(z) < rd.k[0]:
            continue
        a_lags = z < 0
        buy_a = a_lags if rd.modes[0] == "reversion" else not a_lags
        bt = A if buy_a else B
        ok = (bool(m.ma_ok(bt, rd.trend_filter)[-1]) if rd.trend_filter else True) and (
            bool(m.dd_ok(bt, rd.dd_filter)[-1]) if rd.dd_filter else True)
        out.append({"pair": name, "buy": label_of(bt), "z": round(float(z), 2), "trend_ok": ok})
    return out


# ── 보고서 ────────────────────────────────────────────────────────────────────

def pct(v, d=0):
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:.{d}f}%"


def pp(v):
    return "—" if v is None else f"{v * 100:+.0f}%p"


def sgn(v):
    return "—" if v is None else f"{v * 100:+.1f}%"


def esc(s) -> str:
    return html.escape(str(s))


def kpi_block(ev: dict) -> str:
    def one(part, title):
        e = ev.get(part, {})
        if not e.get("n"):
            return f"<div><span>{title}</span><b>—</b><em>거래 없음</em></div>"
        cls = "good" if e["edge"] >= ADOPT["oos_edge"] else ("bad" if e["edge"] < 0 else "")
        return (f"<div><span>{title}</span><b>{pct(e['win'])}</b>"
                f"<em>{e['wins']}/{e['n']}회 · 기준선 {pct(e['base'])} · <b class='{cls}'>{pp(e['edge'])}</b> · p={e['p']:.2f}</em>"
                f"<em>평균 {sgn(e['avg'])} · 중앙 {sgn(e['med'])} · 하위 10% {sgn(e['p10'])} · 최악 {sgn(e['worst'])}</em>"
                + (f"<em>맞수보다 나음 {pct(e['rel_win'])} (평균 {sgn(e['avg_rel'])})</em>" if e['rel_win'] or e['avg_rel'] else "")
                + "</div>")
    return f"<div class='kpis'>{one('is', '표본 내 2020-11~2023')}{one('oos', '표본 외 2024~')}</div>"


def trade_plot(m: Market, trades: list[Trade]) -> str:
    if not trades:
        return ""
    W, H, P = 900, 200, 30
    t0, t1 = m.first_signal.value, m.dates[m.last_entry].value
    rs = [t.ret for t in trades]
    lo, hi = min(min(rs), -0.3), max(max(rs), 0.3)
    X = lambda d: P + (W - 2 * P) * (d.value - t0) / (t1 - t0)  # noqa: E731
    Y = lambda v: P + (H - 2 * P) * (hi - v) / (hi - lo)  # noqa: E731
    dots = "".join(
        f'<circle cx="{X(m.dates[t.entry]):.1f}" cy="{Y(t.ret):.1f}" r="3" fill="var({"--good" if t.ret > 0 else "--bad"})" opacity=".75">'
        f'<title>{esc(t.pair)} · {m.dates[t.entry]:%Y-%m-%d} {label_of(t.bought)} 매수 {sgn(t.ret)}</title></circle>'
        for t in trades)
    cut = X(IS_END)
    years = "".join(f'<text x="{X(pd.Timestamp(f"{y}-01-01")):.1f}" y="{H - 6}" class="ax">{y}</text>'
                    for y in range(m.first_signal.year + 1, m.dates[-1].year + 1))
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="거래별 2개월 수익">'
            f'<line x1="{P}" x2="{W - P}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" class="zero"/>'
            f'<line x1="{cut:.1f}" x2="{cut:.1f}" y1="{P - 10}" y2="{H - P}" class="bd"/>'
            f'<text x="{cut + 4:.1f}" y="{P - 2}" class="ax">표본 외 →</text>{dots}{years}'
            f'<text x="{P}" y="{Y(hi) + 10:.1f}" class="ax">{sgn(hi)}</text><text x="{P}" y="{Y(lo) - 2:.1f}" class="ax">{sgn(lo)}</text></svg>')


def ste_split(res: dict) -> str:
    rd: Round = res["round"]
    n_sides = len(res["lag_any"])
    steps = [
        f"대상은 '맞수 목록'의 업종 대표 대형주 {n_sides}개다. 동전주·밈·크립토 같은 고변동 종목에는 이 절차를 쓰지 않는다(9회차).",
        "매 거래일 종가 뒤에 각 종목의 최근 1년(252 거래일) 최고 종가를 확인한다.",
        f"종가가 1년 최고 종가보다 {rd.dd_filter:.0%} 이상 낮으면 그 종목을 후보로 둔다.",
        f"후보마다 맞수와의 괴리를 확인한다: 최근 {', '.join(map(str, rd.L))} 거래일 누적 수익률 차이의 z 값을 각각 계산한다.",
        f"z 값 중 하나라도 −{rd.k[0]} 이하이면(맞수보다 뒤처짐) 그 후보를 먼저 산다. 돈이 남으면 나머지 후보를 산다.",
        "후보를 다음 거래일 종가에 산다. 후보마다 같은 금액을 넣는다.",
        f"{HOLD} 거래일(약 2개월) 동안 보유한다. 같은 종목의 새 신호는 무시한다.",
        f"{HOLD} 번째 거래일 종가에 판다. 손절 규칙은 시험하지 않았다 — 하위 10% 거래의 손실 크기를 감당할 수 있는 금액만 넣는다.",
        "후보가 16 개 이상이면 시장 전체가 빠지는 중이다. 이때는 종목당 금액을 평소의 절반으로 줄인다(2022 년처럼 하락이 길면 승률이 기준선 근처로 떨어졌다).",
    ]
    return "".join(f"<li>{s}</li>" for s in steps)


def ste_rule(res: dict) -> str:
    rd: Round = res["round"]
    word = "뒤처진" if rd.modes[0] == "reversion" else "앞선"
    steps = [
        "아래 '맞수 목록'의 각 짝을 바스켓 A 와 바스켓 B 로 둔다.",
        "매 거래일 종가 뒤에 각 바스켓의 당일 수익률을 계산한다. 당일 수익률은 편입 종목 등락률의 평균이다.",
        (f"최근 {', '.join(map(str, rd.L))} 거래일 누적 수익률의 차이(A − B)를 각각 계산한다. 이 값들이 괴리다."
         if rd.extra.get("ensemble") else f"최근 {rd.L[0]} 거래일 누적 수익률의 차이(A − B)를 계산한다. 이 값이 괴리다."),
        "2020-05-01 부터 오늘까지의 괴리 평균과 표준편차로 z 값을 계산한다.",
        (f"z 값 중 하나라도 −{rd.k[0]} 이하 또는 +{rd.k[0]} 이상인지 확인한다. 여러 개면 절댓값이 가장 큰 것을 쓴다."
         if rd.extra.get("ensemble") else f"z 값이 −{rd.k[0]} 이하 또는 +{rd.k[0]} 이상인지 확인한다."),
    ]
    if rd.trend_filter:
        steps.append(f"{word} 바스켓의 종가가 {rd.trend_filter} 거래일 이동평균보다 높은지 확인한다. 낮으면 사지 않는다.")
    if rd.dd_filter:
        steps.append(f"{word} 바스켓이 최근 1년 최고치보다 {rd.dd_filter:.0%} 이상 낮은지 확인한다. 아니면 사지 않는다.")
    steps += [
        f"조건이 맞으면 {word} 바스켓을 다음 거래일 종가에 산다. 다른 바스켓은 사지 않는다.",
        f"{HOLD} 거래일(약 2개월) 동안 보유한다. 같은 짝의 새 신호는 무시한다.",
        f"{HOLD} 번째 거래일 종가에 판다.",
    ]
    return "".join(f"<li>{s}</li>" for s in steps)


def verdict_text(rd: Round, ok: bool) -> str:
    """통제·스트레스 회차는 전략이 아니다 — 채택/기각 대신 실험 결과로 적는다."""
    if rd.kind == "control":
        return "통제 · 효과 있음" if ok else "통제 · 효과 없음"
    return "채택" if ok else "기각"


def final_of(results: list[dict]) -> dict | None:
    """채택 전략 = 채택 기준을 넘은 마지막 '전략' 회차(통제 실험은 전략이 아니다)."""
    return next((r for r in reversed(results) if r["round"].kind != "control" and adopted(r["eval"])), None)


def render(m: Market, results: list[dict], history: list[dict], run_at: str) -> str:
    final = final_of(results)
    latest = results[-1]

    rounds_rows = ""
    for r in results:
        rd, ev = r["round"], r["eval"]
        o, i = ev.get("oos", {}), ev.get("is", {})
        ok = adopted(ev)
        rounds_rows += (
            f"<tr><td><b>{rd.no}</b></td><td><b>{esc(rd.title)}</b><span class='sub'>{esc(r['rule_text'])}</span></td>"
            f"<td>{esc(rd.limit)}</td><td>{esc(rd.change)}</td>"
            f"<td class='num'>{pct(i.get('win'))} <span class='sub'>{i.get('n', 0)}회 · {pp(i.get('edge'))}</span></td>"
            f"<td class='num'>{pct(o.get('win'))} <span class='sub'>{o.get('n', 0)}회 · {pp(o.get('edge'))} · p={o.get('p', float('nan')):.2f}</span></td>"
            f"<td class='{'good' if ok else 'bad'}'><b>{verdict_text(rd, ok)}</b></td></tr>")

    compare = ""
    if final and final.get("eval_without"):
        compare = ("<h3>비교 — 같은 낙폭 매수 중 괴리 신호가 없던 것</h3>" + kpi_block(final["eval_without"]))
    if final and final.get("regime"):
        rows = "".join(
            f"<tr><td>{r['label']}</td><td class='num'>{pct(r['is']['win'])} <span class='sub'>{r['is']['n']}회 · 평균 {sgn(r['is']['avg'])}</span></td>"
            f"<td class='num'>{pct(r['oos']['win'])} <span class='sub'>{r['oos']['n']}회 · 평균 {sgn(r['oos']['avg'])}</span></td></tr>"
            for r in final["regime"])
        compare += (f"<h3>국면 위험 — 그날 동시에 −20% 인 대상 종목 수별 성적 (오늘 {final['now_count']}/{final['n_sides']}개)</h3>"
                    f"<div class='tw'><table><thead><tr><th>동시 후보 수</th><th>표본 내(2022 긴 약세장 포함)</th><th>표본 외(2024~, 짧은 급락 위주)</th></tr></thead><tbody>{rows}</tbody></table></div>")
    if final:
        head = f"""<section class="card hero"><p class="eyebrow">채택 전략 · {final['round'].no}회차 · 채택 기준: 표본 외 거래 ≥ {ADOPT['oos_n']}회, 기준선 대비 ≥ {pp(ADOPT['oos_edge'])}, 순열 p ≤ {ADOPT['oos_p']}, 표본 내도 기준선보다 높음</p>
<h2>{esc(final['rule_text'])}</h2>{kpi_block(final['eval'])}
{compare}
<h3>절차 (ASD-STE100)</h3><ol class="ste">{ste_split(final) if final['round'].kind == 'split' else ste_rule(final)}</ol>
<h3>쓰기 전에 확인할 것</h3><ul>
<li>효과의 근원은 '괴리'보다 '업종 대표 대형주의 −20% 낙폭'이다(6회차 통제 실험). 괴리는 같은 후보 중 우선순위를 정하는 데만 쓴다(효과 +1~2%p, 통계적으로 확실하지 않음).</li>
<li>같은 규칙이 고변동·투기 종목에서는 효과가 없다(9회차). 지금 살아남은 종목만 데이터에 있어 대형주 결과도 실제보다 좋게 나왔을 수 있다(예: 2023 SVB 같은 사례가 빠졌다).</li>
<li>2024 년 이후는 대체로 상승장이었다. 하락장이 길게 이어지면 −20% 매수가 연달아 손실을 낼 수 있다.</li>
</ul></section>"""
    else:
        head = f"""<section class="card" style="border-color:var(--bad)"><h3 style="margin-top:0">채택 전략 (ASD-STE100)</h3>
<ol class="ste"><li>채택 기준을 모두 넘은 전략이 아직 없다.</li><li>기준: 표본 외 거래 {ADOPT['oos_n']}회 이상, 기준선 대비 {pp(ADOPT['oos_edge'])} 이상, 순열 p {ADOPT['oos_p']} 이하, 표본 내도 기준선보다 높음.</li>
<li>아래 신호로 매매하지 않는다. 다음 회차에서 한계를 고친다.</li></ol></section>"""

    show = final or latest
    detail = ""
    for r in results:
        rd = r["round"]
        if rd.kind == "rule":
            sens_rows = "".join(
                f"<tr><td>{key.split('|')[0]}일</td><td>±{key.split('|')[1]}</td>"
                f"<td class='num'>{pct(v.get('is', {}).get('win'))} <span class='sub'>{v.get('is', {}).get('n', 0)}회 · {pp(v.get('is', {}).get('edge'))}</span></td>"
                f"<td class='num'>{pct(v.get('oos', {}).get('win'))} <span class='sub'>{v.get('oos', {}).get('n', 0)}회 · {pp(v.get('oos', {}).get('edge'))}</span></td></tr>"
                for key, v in r["sens"].items())
            pair_rows = "".join(
                f"<tr><td>{esc(p['pair'])}</td><td class='num'>{p['n']}</td><td class='num'>{pct(p['win'])}</td>"
                f"<td class='num'>{p['oos_n']}</td><td class='num'>{pct(p['oos_win'])}</td><td class='num'>{sgn(p['avg'])}</td></tr>"
                for p in sorted(r["per_pair"], key=lambda p: -(p["n"])))
            extra = (f"<h3>민감도 — 창·경계를 바꾸면 (참고용 · 판단은 미리 정한 규칙으로)</h3><div class='tw'><table><thead><tr><th>괴리 창</th><th>경계</th><th>표본 내</th><th>표본 외</th></tr></thead><tbody>{sens_rows}</tbody></table></div>"
                     f"<h3>짝별 거래</h3><div class='tw'><table><thead><tr><th>맞수</th><th>거래</th><th>승률</th><th>표본 외 거래</th><th>표본 외 승률</th><th>평균 수익</th></tr></thead><tbody>{pair_rows}</tbody></table></div>")
        else:
            extra = "<h3>고른 상위 20 조합</h3><ul>" + "".join(
                f"<li>{esc(c[0])} · {c[1]}일 · ±{c[2]} · {'역추세' if c[3] == 'reversion' else '추세'}</li>" for c in r["chosen"]) + "</ul>"
        detail += (f"<section class='card'><details><summary>{rd.no}회차 상세 — {esc(rd.title)}</summary>"
                   f"{kpi_block(r['eval'])}<h3>거래별 2개월 수익 (점 하나 = 거래 하나)</h3><div class='chart'>{trade_plot(m, r['trades'])}</div>{extra}</details></section>")

    live = live_signals(m, show)
    if show["round"].kind == "split":
        live_html = "".join(
            f"<li><b>{esc(x['buy'])}</b> — {esc(x['pair'])}"
            f"{' · <b class=good>맞수보다 괴리로 뒤처짐(우선)</b>' if x['lag'] else ' · 괴리 신호 없음'}</li>" for x in live
        ) or "<li>지금 조건을 만족하는 종목이 없다.</li>"
    else:
        live_html = "".join(
            f"<li><b>{esc(x['buy'])}</b> 매수 신호 — {esc(x['pair'])}, z {x['z']:+.2f}{'' if x['trend_ok'] else ' · 추가 조건 불충족(사지 않음)'}</li>" for x in live
        ) or "<li>지금 경계를 넘은 짝이 없다.</li>"
    rivals_html = "".join(f"<li>{esc(n)}: {label_of(A)} vs {label_of(B)}</li>" for n, A, B in RIVALS)
    hist_rows = "".join(f"<tr><td>{esc(h['run_at'][:16].replace('T', ' '))}</td><td>{h['rounds']}</td><td>{esc(h['final'])}</td></tr>" for h in reversed(history))
    live_title = "채택 전략" if final else f"{latest['round'].no}회차 규칙 · 미채택 — 기록용, 매매 근거 아님"

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>투자전략 백테스트 결과</title>
<style>
:root{{--bg:#f7f6f3;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e6e3dc;--accent:#5a3a22;--good:#2f7d4f;--bad:#b23b2b;--soft:#f1eee8}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#151514;--card:#1f1f1d;--ink:#ecebe8;--muted:#a3a19b;--line:#33322f;--accent:#d9b08c;--good:#6cc58f;--bad:#ef7d6c;--soft:#262623}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard",sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px 60px}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:18px;margin:4px 0 14px}}h3{{font-size:13px;margin:18px 0 8px;color:var(--muted)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin:14px 0}}.hero{{border-color:var(--good)}}
.eyebrow{{font-size:12px;color:var(--accent);font-weight:700;margin:0}}.muted{{color:var(--muted);font-size:12px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:10px}}.kpis>div{{background:var(--soft);border-radius:10px;padding:10px 12px}}
.kpis span{{display:block;font-size:11px;color:var(--muted)}}.kpis>div>b{{font-size:24px}}.kpis em{{display:block;font-style:normal;font-size:11.5px;color:var(--muted)}}
.good{{color:var(--good)}}.bad{{color:var(--bad)}}ol.ste{{margin:0;padding-left:22px}}ol.ste li{{margin:3px 0}}
.chart svg{{width:100%;height:auto}}.bd{{stroke:var(--accent);stroke-dasharray:4 4;opacity:.7}}.zero{{stroke:var(--line)}}.ax{{fill:var(--muted);font-size:10px}}
.tw{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:12.5px;min-width:720px}}th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{font-size:11px;color:var(--muted);font-weight:700}}td:first-child,td:last-child,th:first-child,th:last-child{{white-space:nowrap}}td.num{{text-align:right;white-space:nowrap}}.sub{{display:block;font-size:10.5px;color:var(--muted);font-weight:400}}
details summary{{cursor:pointer;font-weight:700}}ul{{padding-left:20px}}
</style></head><body><main>
<h1>투자전략 백테스트 결과</h1>
<p class="muted">바스켓 − 바스켓 괴리 → 한쪽 바스켓 매수(롱 온리) · 보유 2개월(42거래일) · 괴리 통계 2020-05~ · 가격 {m.dates[0]:%Y-%m-%d} ~ {m.dates[-1]:%Y-%m-%d} · 마지막 실행 {esc(run_at[:16].replace('T', ' '))} UTC</p>

{head}

<section class="card"><h3 style="margin-top:0">회차 기록 — 한계 → 개선 → 결과</h3>
<div class="tw"><table><thead><tr><th>회차</th><th>전략</th><th>발견한 한계</th><th>바꾼 것</th><th>표본 내 승률</th><th>표본 외 승률</th><th>판정</th></tr></thead><tbody>{rounds_rows}</tbody></table></div>
<p class="muted">승률 아래 = 거래 수 · 기준선(같은 바스켓을 같은 기간 아무 날 샀을 때) 대비 차이 · 순열 p(무작위 진입으로 이 승률 이상이 나올 확률). 채택 기준: 표본 외 거래 ≥ {ADOPT['oos_n']}회, 기준선 대비 ≥ {pp(ADOPT['oos_edge'])}, p ≤ {ADOPT['oos_p']}, 표본 내도 기준선 위.</p></section>

<section class="card"><h3 style="margin-top:0">지금 신호 ({m.dates[-1]:%Y-%m-%d} 종가 · {live_title})</h3><ul>{live_html}</ul></section>

{detail}

<section class="card"><details><summary>맞수 목록 ({len(RIVALS)}쌍)</summary><ul>{rivals_html}</ul></details></section>

<section class="card"><h3 style="margin-top:0">공통 방법 (ASD-STE100)</h3>
<ol class="ste">
<li>각 종목의 수정주가(배당·분할 반영)를 쓴다.</li>
<li>바스켓의 당일 수익률은 편입 종목 당일 등락률의 평균이다.</li>
<li>괴리는 최근 L 거래일 누적 로그수익의 차이(A − B)다.</li>
<li>괴리의 평균과 표준편차는 2020-05-01 부터 그날까지만 쓴다. 미래 데이터는 쓰지 않는다.</li>
<li>관측이 {MIN_STATS}개 모이기 전에는 신호를 내지 않는다. 첫 신호 가능일은 {m.first_signal:%Y-%m-%d} 이다.</li>
<li>신호 다음 거래일 종가에 산다. {HOLD} 거래일 뒤 종가에 판다.</li>
<li>산 바스켓의 보유 수익이 0 보다 크면 승리로 센다.</li>
<li>2023-12-31 까지 진입한 거래는 표본 내, 그 뒤는 표본 외다. 판단은 표본 외로 한다. 마지막 진입 가능일은 {m.dates[m.last_entry]:%Y-%m-%d} 이다.</li>
<li>순열 검정은 거래마다 같은 바스켓·같은 기간의 진입일을 {PERMUTATIONS}번 무작위로 뽑아 비교한다. 거래끼리 시기가 겹치면 p 가 실제보다 작게 나올 수 있다.</li>
</ol>
<h3>주의</h3><ul>
<li>OHLCV 에는 지금 상장된 종목만 있다. 상장폐지 종목이 빠져 승률이 실제보다 높게 나온다.</li>
<li>수수료·세금·슬리피지를 넣지 않았다.</li>
<li>바스켓과 맞수는 2026 년 시점의 지식으로 골랐다(사후 선택).</li>
</ul></section>

<section class="card"><h3 style="margin-top:0">실행 기록</h3><div class="tw"><table><thead><tr><th>실행(UTC)</th><th>회차 수</th><th>채택 전략</th></tr></thead><tbody>{hist_rows}</tbody></table></div></section>
</main></body></html>"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tickers = sorted({t for _, _, ts in THEMES for t in ts} | {t for _, A, B in RIVALS for t in A + B})
    px = load_prices(tickers)
    missing = [t for t in tickers if t not in px.columns]
    if missing:
        raise SystemExit(f"OHLCV 에 없는 종목: {missing}")
    m = Market(px)
    rng = np.random.default_rng(SEED)
    results = [run_round(m, rd, rng) for rd in ROUNDS]
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    final = final_of(results)
    raw = LOG.read_text() if LOG.exists() else "[]"
    history = [h for h in json.loads(raw) if "rounds" in h]   # 1회차 단독 시절 기록 형식은 버린다
    entry = {"run_at": run_at, "rounds": len(results),
             "final": f"{final['round'].no}회차 · {final['rule_text']}" if final else "없음"}
    if history and {k: v for k, v in history[-1].items() if k != "run_at"} == {k: v for k, v in entry.items() if k != "run_at"}:
        history[-1] = entry
    else:
        history.append(entry)
    LOG.write_text(json.dumps(history, ensure_ascii=False, indent=1))
    REPORT.write_text(render(m, results, history, run_at), encoding="utf-8")
    print(f"보고서: {REPORT}")
    for r in results:
        ev = r["eval"]
        print(f"{r['round'].no}회차 {r['round'].title}: {r['rule_text']}")
        for part in ("is", "oos"):
            e = ev.get(part, {})
            if e.get("n"):
                print(f"   {part}: n={e['n']} win={pct(e['win'])} base={pct(e['base'])} edge={pp(e['edge'])} p={e['p']:.3f} "
                      f"avg={sgn(e['avg'])} rel_win={pct(e['rel_win'])} avg_rel={sgn(e['avg_rel'])}")
        if r.get("eval_without"):
            for part in ("is", "oos"):
                e = r["eval_without"].get(part, {})
                if e.get("n"):
                    print(f"   (괴리 없음) {part}: n={e['n']} win={pct(e['win'])} base={pct(e['base'])} edge={pp(e['edge'])} p={e['p']:.3f} avg={sgn(e['avg'])}")
        if r.get("sens"):
            print("   sens(is,oos edge):", {k: (pp(v.get('is', {}).get('edge')), pp(v.get('oos', {}).get('edge'))) for k, v in r["sens"].items()})
        print("   채택" if adopted(ev) else "   기각")


if __name__ == "__main__":
    main()
