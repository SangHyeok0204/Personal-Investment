"""투자 전략 API — 타점 승률(1단계). 화면 `/strategy/entry-odds` 가 쓴다.

지수·섹터는 `monthly_closes`(계절성과 같은 원천·같은 이어붙이기), 종목은 저장소의 OHLCV DuckDB
(`storage/ohlcv/ohlcv.duckdb`, adj_close)에서 읽는다. 계산은 `core/entry_odds.py`.
⚠️과거 통계다. 예측이 아니다 — 응답에 표본(독립 회차)과 하한을 같이 싣는다.
"""
from __future__ import annotations

import math
import os
import re
import threading
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import entry_odds
from app.core.config import settings
from app.core.errors import AppError
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/strategy", tags=["strategy"])

_TICKER = re.compile(r"^[A-Za-z0-9.\-^=]{1,20}$")
_lock = threading.Lock()
_cache: dict[tuple, dict] = {}
_CACHE_MAX = 128


def _duckdb_path() -> Path:
    return Path(settings.STORAGE_DIR) / "ohlcv" / "ohlcv.duckdb"


def _clean(obj):
    """NaN·inf 를 JSON 이 받는 None 으로."""
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _remember(key: tuple, build) -> dict:
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    value = build()
    with _lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = value
    return value


@router.get("/entry-odds/universe")
def universe(db: Session = Depends(get_db)) -> dict:
    """고를 수 있는 지수·섹터 목록과 종목 데이터 범위."""
    series = db.execute(
        text("SELECT key, label, grp FROM seasonality_series ORDER BY sort")
    ).mappings().all()
    path = _duckdb_path()
    return {
        "series": [dict(s) for s in series],
        "ohlcv_available": path.exists(),
    }


@router.get("/entry-odds")
def entry_odds_for(
    series: str | None = Query(None, max_length=20),
    ticker: str | None = Query(None, max_length=20),
    db: Session = Depends(get_db),
) -> dict:
    if (series is None) == (ticker is None):
        raise AppError(400, "BAD_REQUEST", "series 와 ticker 중 하나만 주세요.")
    if series is not None:
        return _series_odds(db, series)
    assert ticker is not None
    if not _TICKER.match(ticker):
        raise AppError(400, "BAD_TICKER", "티커 형식이 아닙니다.")
    return _ticker_odds(ticker.upper())


def _series_odds(db: Session, key: str) -> dict:
    meta = db.execute(
        text("SELECT key, label, grp FROM seasonality_series WHERE key = :k"), {"k": key}
    ).mappings().first()
    if meta is None:
        raise AppError(404, "UNKNOWN_SERIES", f"지수 '{key}' 가 없습니다.")
    version = db.execute(
        text("SELECT max(loaded_at) FROM monthly_closes WHERE series = :k"), {"k": key}
    ).scalar()

    def build() -> dict:
        rows = db.execute(
            text("SELECT month, close, source FROM monthly_closes WHERE series = :k"), {"k": key}
        ).all()
        level, dropped = _index_level(rows)
        if level.empty:
            raise AppError(404, "NO_DATA", f"'{key}' 월말 종가가 없습니다.")
        return _clean({
            "kind": "series",
            "key": key,
            "label": meta["label"],
            "basis": "가격(배당 제외)",
            "dropped_before": dropped,
            **entry_odds.compute(level),
        })

    return _remember(("series", key, str(version)), build)


def _index_level(rows) -> tuple[pd.Series, str | None]:
    """[(month, close, source)] → 월말 레벨. 블룸버그를 기준으로 두고, 그 뒤 달은 야후 종가를
    **겹치는 달의 비율로** 이어붙인다(수익률을 잇지 않는다 — 빈 달이 있으면 수익률 잇기는 두 달 치 움직임을 잃는다).

    ⚠️중간에 빈 달이 있으면 그 앞 구간을 버린다 — 표는 '연속한 월'을 전제로 h 개월 뒤를 센다
      (HSI 1960년대에 빈 달이 있다). 버린 시점을 돌려준다.
    """
    by: dict[str, dict[str, float]] = {}
    for month, close, source in rows:
        if close is not None and float(close) > 0:
            by.setdefault(source, {})[month] = float(close)
    bbg, yahoo = by.get("bloomberg", {}), by.get("yahoo", {})
    merged = dict(bbg)
    if bbg and yahoo:
        cut = max(bbg)
        if cut in yahoo:
            ratio = bbg[cut] / yahoo[cut]
            merged.update({m: v * ratio for m, v in yahoo.items() if m > cut})
    elif yahoo:
        merged = dict(yahoo)
    if not merged:
        return pd.Series(dtype=float), None
    s = pd.Series(merged)
    s.index = pd.to_datetime([f"{m}-01" for m in s.index])
    s = s.sort_index()
    full = s.reindex(pd.date_range(s.index[0], s.index[-1], freq="MS"))
    gaps = full[full.isna()]
    if gaps.empty:
        return full, None
    last_gap = gaps.index[-1]
    return full[full.index > last_gap], last_gap.strftime("%Y-%m")


def _ohlcv_version(path: Path) -> float:
    """결과 캐시 키 — DB 파일·WAL·수집 매니페스트 중 가장 늦게 바뀐 시각(뷰가 읽는 Parquet 은 매니페스트와 같이 바뀐다)."""
    cands = [path, path.with_name(path.name + ".wal"), path.parent / "_manifest.csv"]
    return max((os.path.getmtime(p) for p in cands if p.exists()), default=0.0)


def _ticker_odds(ticker: str) -> dict:
    path = _duckdb_path()
    if not path.exists():
        raise AppError(503, "OHLCV_MISSING", "OHLCV 저장소가 없습니다(storage/ohlcv).")
    version = _ohlcv_version(path)

    def build() -> dict:
        try:
            import duckdb
        except ImportError as exc:
            raise AppError(503, "DUCKDB_MISSING", "duckdb 패키지가 없습니다(apps/api/requirements.txt).") from exc
        try:
            con = duckdb.connect(str(path), read_only=True)
        except Exception as exc:  # 수집 스크립트가 쓰는 중이면 열리지 않는다
            raise AppError(503, "OHLCV_BUSY", f"OHLCV 저장소를 열 수 없습니다: {exc}") from exc
        try:
            df = con.execute(
                "SELECT date, adj_close FROM ohlcv WHERE ticker = ? "
                "UNION ALL SELECT date, adj_close FROM wls_ohlcv WHERE ticker = ? AND NOT EXISTS "
                "(SELECT 1 FROM ohlcv WHERE ticker = ?)",
                [ticker, ticker, ticker],
            ).df()
            name = con.execute(
                "SELECT name_ko FROM wls_map WHERE yahoo = ? AND name_ko IS NOT NULL LIMIT 1", [ticker]
            ).fetchone()
        finally:
            con.close()
        if df.empty:
            raise AppError(404, "UNKNOWN_TICKER", f"'{ticker}' 의 OHLCV 가 없습니다.")
        daily = pd.Series(df["adj_close"].to_numpy(), index=pd.to_datetime(df["date"])).sort_index()
        daily = daily[~daily.index.duplicated(keep="last")]
        level = entry_odds.month_end(daily)
        # 마지막 달이 아직 안 끝났으면(마지막 거래일 < 그 달 마지막 영업일) 과거 표에서 뺀다 — '지금 상태'에만 쓴다.
        last_day = daily.index[-1]
        partial = last_day < last_day + pd.offsets.BMonthEnd(0)
        if len(level) < 24:
            raise AppError(422, "TOO_SHORT", f"'{ticker}' 는 데이터가 {len(level)}개월뿐입니다.")
        return _clean({
            "kind": "ticker",
            "key": ticker,
            "label": name[0] if name else ticker,
            "basis": "수정주가(배당·분할 반영)",
            "data_until": daily.index[-1].strftime("%Y-%m-%d"),
            **entry_odds.compute(level, partial_last=partial),
        })

    return _remember(("ticker", ticker, version), build)


# ── 연구실: 바스켓 괴리(전략1) · 웅덩이 매수(전략2) — core/basket_lab.py ─────────────

def _lab():
    from app.core import basket_lab

    return basket_lab


def _lab_call(fn, *args):
    try:
        return _clean(fn(*args))
    except AppError:
        raise
    except Exception as exc:  # 야후 일봉을 못 받으면 화면에 이유를 보인다
        raise AppError(503, "LAB_UNAVAILABLE", f"가격을 불러오지 못했습니다: {exc}") from exc


@router.get("/lab/meta")
def lab_meta() -> dict:
    return _lab_call(_lab().meta)


@router.get("/lab/spread")
def lab_spread(a: str, b: str, ind: str = "ret", n: int = 20, hold: int = 10) -> dict:
    bl = _lab()
    if a not in bl.BASKET or b not in bl.BASKET or a == b:
        raise AppError(400, "BAD_BASKET", "서로 다른 바스켓 두 개를 고르세요.")
    if ind not in bl.INDICATORS or n not in bl.NS or hold not in bl.HOLDS:
        raise AppError(400, "BAD_PARAM", "지표·n·보유기간 값이 목록에 없습니다.")
    return _lab_call(bl.spread_detail, a, b, ind, n, hold)


@router.get("/lab/leaderboard")
def lab_leaderboard(hold: int = 10, scope: str = "all") -> dict:
    bl = _lab()
    if hold not in bl.HOLDS or scope not in ("all", "same", "cross"):
        raise AppError(400, "BAD_PARAM", "보유기간·범위 값이 목록에 없습니다.")
    return _lab_call(bl.leaderboard, hold, 4, scope)


@router.get("/lab/dip")
def lab_dip() -> dict:
    return _lab_call(_lab().dip_study)
