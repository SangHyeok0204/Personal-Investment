"""[수익률 모니터] — 주간가격모니터 price_monitor.xlsx 판독 (2026-08-26).

[종목 모니터] 우하단 카드의 데이터원. 주간가격모니터 파이프라인이 갱신하는
``price_monitor.xlsx``(data 시트, 일단위·주말 ffill)를 읽어 관심 자산의
YtD·MtD·WtD·DtD + "저점 대비 상승"(1주/1달/3달 중 가장 드라마틱한 것)과
1년 스파크라인을 계산한다.

★관심 자산은 아래 ``ASSETS`` 가 정본이다(2026-08-26 사용자 지시: 지금은
  하드코딩, 단 사람이 고치기 쉬운 형태). 열 이름은 xlsx 1행의 블룸버그
  티커 문자열과 정확히 일치해야 한다 — 열 '위치'가 아니라 '이름'으로 찾기
  때문에 시트에 열이 늘거나 순서가 바뀌어도 안전하다.

단위 두 종류가 이 모듈의 요점이다:
  · unit="pct" — 가격 자산. 수익률 = (현재/기준 - 1) × 100 (%).
  · unit="bp"  — 금리 자산. 금리의 %변화율은 오해를 부르므로(4%→5% 가 +25%)
                 변화폭 bp = (현재 - 기준) × 100 으로 계산한다.

시간창(고정 — 사용자 지시 "timewindow 만 고정해놓으면 바로 계산"):
  · DtD = 전 영업일(토·일 건너뜀) 대비   · WtD = 지난주 금요일 대비
  · MtD = 전월 말일 대비                 · YtD = 전년 12/31 대비
  기준일 값은 "그 날짜 이하의 마지막 행"(주말 ffill 이라 정확히 떨어진다).

저점 대비 상승 3종(1주=7일·1달=30일·3달=91일 달력창) 중 하나를 고르는 규칙:
  창이 길수록 저점이 낮아져 상승폭이 단조증가하므로 그냥 max 를 취하면 항상
  3달이 이긴다. 그래서 |상승폭|/√일수 로 정규화해 비교한다(랜덤워크 기준
  같은 '놀라움'이 되도록) — 1주 만의 +8% 가 3달에 걸친 +10% 보다 드라마틱하다.
"""
from __future__ import annotations

import io
import math
import os
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))

SRC_PATH = os.environ.get(
    "PRICE_MONITOR_XLSX", "/srv/legacy/price_monitor/price_monitor.xlsx"
)
SHEET = "data"

# ── 관심 자산 (사람이 고치는 곳) ──────────────────────────────────────────────
# column 은 price_monitor.xlsx data 시트 1행의 헤더 문자열 그대로.
# unit: "pct"(가격 — %수익률) | "bp"(금리 — 변화폭 bp).
ASSETS: list[dict] = [
    {"key": "gold", "name": "금", "column": "XAU Curncy", "unit": "pct"},
    {"key": "btc", "name": "비트코인", "column": "XBTUSD BGN Curncy", "unit": "pct"},
    # GT30 Govt = 미 국채 30년 수익률(%). 사용자 라벨은 "30년 국채금리".
    {"key": "ust30y", "name": "30년 국채금리", "column": "GT30 Govt", "unit": "bp"},
]

REBOUND_WINDOWS = [("1w", "1주일 저점 대비", 7), ("1m", "1달 저점 대비", 30),
                   ("3m", "3달 저점 대비", 91)]
SPARK_DAYS = 365   # 맨 오른쪽 스파크라인 = 최근 1년
SPARK_POINTS = 60  # index-strip 스파크와 같은 밀도로 솎는다


# ── 순수 계산부 (파일 IO 없음 — 테스트는 여기를 겨눈다) ──────────────────────

def _delta(last: float, base: float | None, unit: str) -> float | None:
    """기준값 대비 변화 — pct 는 %수익률, bp 는 변화폭(bp). 기준 없으면 None."""
    if base is None:
        return None
    if unit == "bp":
        return (last - base) * 100.0
    if base == 0:
        return None
    return (last / base - 1.0) * 100.0


def _value_at_or_before(dates: list[date], values: list[float], target: date) -> float | None:
    """target 이하의 마지막 관측값. 시계열 시작 전이면 None (fail-soft)."""
    i = bisect_right(dates, target)
    return values[i - 1] if i > 0 else None


def _prev_business_day(d: date) -> date:
    out = d - timedelta(days=1)
    while out.weekday() >= 5:  # 토=5 일=6
        out -= timedelta(days=1)
    return out


def _downsample(values: list[float], n: int) -> list[float]:
    """양 끝점을 보존하며 균등 간격으로 n 점 이하로 솎는다."""
    if len(values) <= n:
        return list(values)
    last = len(values) - 1
    return [values[round(i * last / (n - 1))] for i in range(n)]


def compute_asset(series: list[tuple[date, float]], *, key: str, name: str,
                  unit: str) -> dict | None:
    """단일 자산 시계열 → 카드 한 행 payload. 시계열이 비면 None."""
    if not series:
        return None
    series = sorted(series)
    dates = [d for d, _ in series]
    values = [v for _, v in series]
    last_date, last = dates[-1], values[-1]

    # 고정 시간창 4종 — 기준일만 여기서 바꾸면 된다.
    anchors = {
        "dtd": _prev_business_day(last_date),
        # 지난주 금요일: 월(0)→-3일, 화(1)→-4일 … 일(6)→-9일.
        "wtd": last_date - timedelta(days=last_date.weekday() + 3),
        "mtd": last_date.replace(day=1) - timedelta(days=1),
        "ytd": date(last_date.year - 1, 12, 31),
    }
    returns = {
        k: _delta(last, _value_at_or_before(dates, values, a), unit)
        for k, a in anchors.items()
    }

    # 저점 대비 상승 3종 + √시간 정규화로 대표 1개 선정.
    all_rebounds: dict[str, float | None] = {}
    best = None  # (score, win_key, label, value, low, low_date)
    for win_key, label, days in REBOUND_WINDOWS:
        start = last_date - timedelta(days=days)
        lo_i = bisect_right(dates, start)  # start 초과 ~ 끝
        window = values[lo_i:]
        if not window:
            all_rebounds[win_key] = None
            continue
        low = min(window)
        low_date = dates[lo_i + window.index(low)]
        value = _delta(last, low, unit)
        all_rebounds[win_key] = value
        if value is None:
            continue
        score = abs(value) / math.sqrt(days)
        # 동점이면 짧은 창(더 최근의 움직임)이 이긴다 — 리스트가 짧은 창 순서.
        if best is None or score > best[0]:
            best = (score, win_key, label, value, low, low_date)

    rebound = None
    if best is not None:
        _, win_key, label, value, low, low_date = best
        rebound = {
            "window": win_key,
            "label": label,
            "value": value,
            "low": low,
            "low_date": low_date.isoformat(),
            "all": all_rebounds,
        }

    spark_start = last_date - timedelta(days=SPARK_DAYS)
    spark = _downsample(values[bisect_right(dates, spark_start):], SPARK_POINTS)

    return {
        "key": key,
        "name": name,
        "unit": unit,
        "asof": last_date.isoformat(),
        "last": last,
        "returns": returns,
        "rebound": rebound,
        "spark": spark,
    }


# ── xlsx 판독 (mtime+size 캐시) ──────────────────────────────────────────────
# 1.4MB·2천행이라 매 요청 파싱은 수 초 — 파일 서명이 같으면 재사용한다.
# ★S: 쪽 파이프라인이 제자리 저장하는 파일이라 반쯤 쓰인 순간을 읽을 수 있다
#   → 바이트를 통째로 읽어 BytesIO 로 열고, 열기 실패면 직전 캐시를 그대로 낸다
#   (stock_monitor 캐시 DB 의 "제자리 덮어쓰기 경쟁" 교훈, 2026-08-25).
_CACHE: dict = {"sig": None, "series": None}


def _load_series(path: str = SRC_PATH) -> dict[str, list[tuple[date, float]]]:
    st = os.stat(path)
    sig = (st.st_mtime_ns, st.st_size)
    if _CACHE["sig"] == sig and _CACHE["series"] is not None:
        return _CACHE["series"]

    with open(path, "rb") as f:
        blob = f.read()
    try:
        import openpyxl  # 지연 import — 순수 계산부 테스트가 openpyxl 없이 돌도록

        wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
        ws = wb[SHEET]
        rows = ws.iter_rows(values_only=True)
        header = next(rows)
        col_idx = {a["key"]: header.index(a["column"]) for a in ASSETS}
        series: dict[str, list[tuple[date, float]]] = {a["key"]: [] for a in ASSETS}
        for r in rows:
            d = r[0]
            if not isinstance(d, datetime):  # '#REF!' 행·미래 빈 행 스킵
                continue
            for k, i in col_idx.items():
                v = r[i] if i < len(r) else None
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    series[k].append((d.date(), float(v)))
        wb.close()
    except Exception:
        if _CACHE["series"] is not None:  # 반쯤 쓰인 파일 등 — 직전 캐시로 버틴다
            return _CACHE["series"]
        raise

    _CACHE["sig"] = sig
    _CACHE["series"] = series
    return series


def build_price_returns() -> dict:
    """xlsx → 카드 payload 한 장.

    반환::

        { "generated_at": KST, "asof": "YYYY-MM-DD"(자산 중 최신),
          "assets": [ compute_asset(...) 결과, ... ] }
    """
    series = _load_series()
    assets = []
    for a in ASSETS:
        row = compute_asset(series.get(a["key"], []),
                            key=a["key"], name=a["name"], unit=a["unit"])
        if row is not None:
            assets.append(row)
    return {
        "generated_at": datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S"),
        "asof": max((r["asof"] for r in assets), default=None),
        "assets": assets,
    }
