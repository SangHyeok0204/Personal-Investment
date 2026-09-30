"""계절성 API (계획 C4) — `/market/seasonality` 화면이 쓴다.

⚠️이 화면은 **"과거에 어땠나"** 를 보여 준다. 예측이 아니다(계획 원칙 5):
  - 원본 `signal()` 은 근거가 없으면 '상승'을 기본값으로 낸다 → 응답에 `evidence` 를 같이 준다.
  - 원본의 '다음 달'은 데이터가 붙은 뒤에는 **이미 진행 중인 이번 달**이다 → `signal_month` 로만 부른다.
  - 적중률은 T_SIG 를 그 백테스트로 고른 **표본 내 수치** → '항상 상승' 기준선과 같이 준다.

계산(walk-forward 포함)이 수 초 걸린다. 데이터가 바뀔 때만(월 1회) 다시 계산한다 —
캐시 키는 (구간, `monthly_closes` 의 마지막 적재 시각).
"""
from __future__ import annotations

import math
import threading

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import seasonality as sea
from app.core.errors import AppError
from app.core.seasonality_sync import chained_returns
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/market/seasonality", tags=["seasonality"])

_WINDOWS = {name: w for name, w in sea.WINDOWS}
_lock = threading.Lock()
_cache: dict[tuple, dict] = {}


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _load(db: Session):
    series = db.execute(
        text(
            "SELECT key, label, grp, continuation, yahoo_symbol FROM seasonality_series ORDER BY sort"
        )
    ).mappings().all()
    rows = db.execute(
        text(
            "SELECT s.grp, s.key, c.month, c.close, c.source FROM seasonality_series s "
            "JOIN monthly_closes c ON c.series = s.key"
        )
    ).all()
    version = db.execute(text("SELECT max(loaded_at) FROM monthly_closes")).scalar()
    return series, rows, version


def _backtest(wf: pd.DataFrame) -> dict:
    """시그널별 적중률 + '항상 상승' 기준선(같은 표본에서 실현수익률 > 0 비율)."""
    out = {}
    for sig in ("상승", "중립", "하락"):
        sub = wf[wf["시그널"] == sig]
        out[sig] = {"n": int(len(sub)), "hit": _num(sub["적중"].mean()) if len(sub) else None}
    out["항상상승"] = {"n": int(len(wf)), "hit": _num((wf["실현수익률"] > 0).mean()) if len(wf) else None}
    return out


def _compute(series, rows, window_name: str) -> dict:
    window = _WINDOWS[window_name]
    frames = chained_returns(rows)
    meta = {s["key"]: s for s in series}
    groups = {}
    for grp, rets in frames.items():
        cols = [s["key"] for s in series if s["grp"] == grp and s["key"] in rets.columns]
        rets = rets[cols]
        proof = sea.proof_table(rets, window)
        wf = sea.walk_forward(rets, window)
        nm = sea.next_month_signals(rets, proof, window)
        last_month = rets.dropna(how="all").index[-1].strftime("%Y-%m")
        cells = [
            {
                "series": r["지수"], "month": int(r["월"]), "n": int(r["n"]),
                "mean": _num(r["평균"]), "win_rate": _num(r["상승률"]), "t": _num(r["t"]),
                "excess": _num(r["평균대비"]), "p": _num(r["p"]), "fdr": r["FDR유의"] == "*",
                "halves_agree": {"Y": True, "N": False}.get(r["전후반부호일치"]),
            }
            for _, r in proof.iterrows()
        ]
        signals = []
        for _, r in nm.iterrows():
            key = r["지수"]
            own_last = rets[key].dropna().index[-1].strftime("%Y-%m")
            signals.append({
                "series": key, "label": meta[key]["label"],
                "continuation": meta[key]["continuation"], "last_month": own_last,
                "signal": r["시그널"], "evidence": bool(r["근거"]), "t": _num(r["t"]), "n": int(r["n"]),
                "hist_mean": _num(r["과거평균"]), "hist_win_rate": _num(r["과거상승률"]),
                "band": (
                    [_num(r["밴드하한"]), _num(r["밴드상한"])]
                    if _num(r["밴드하한"]) is not None else None
                ),
                "fdr": r["검증셀"] == "★",
            })
        groups[grp] = {
            "last_month": last_month,
            "signal_month": nm["예측월"].iloc[0] if len(nm) else None,
            "series": [
                {"key": k, "label": meta[k]["label"], "continuation": meta[k]["continuation"],
                 "proxy": meta[k]["yahoo_symbol"] if meta[k]["continuation"] == "proxy" else None}
                for k in cols
            ],
            "cells": cells,
            "signals": signals,
            "backtest": _backtest(wf),
        }
    return {"window": window_name, "t_sig": sea.T_SIG, "groups": groups}


@router.get("")
def get_seasonality(
    window: str = Query("전구간"),
    db: Session = Depends(get_db),
) -> dict:
    if window not in _WINDOWS:
        raise AppError(400, "VALIDATION_ERROR", "Unknown window.", {"allowed": list(_WINDOWS)})
    series, rows, version = _load(db)
    if not rows:
        return {"window": window, "t_sig": sea.T_SIG, "groups": {}}
    key = (window, version)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    result = _compute(series, rows, window)
    with _lock:
        if len(_cache) > 8:  # 구간 3개 × 데이터 판 몇 개면 충분하다
            _cache.clear()
        _cache[key] = result
    return result


@router.get("/cell")
def get_cell(
    series: str = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> dict:
    """한 시계열·한 달력월의 연도별 수익률 — 히트맵 칸을 누르면 뜬다."""
    all_series, rows, _ = _load(db)
    meta = {s["key"]: s for s in all_series}
    if series not in meta:
        raise AppError(404, "NOT_FOUND", "Unknown series.")
    frames = chained_returns([r for r in rows if r[1] == series])
    r = frames[meta[series]["grp"]][series].dropna()
    r = r[r.index.month == month]
    years = [{"year": int(ts.year), "ret": round(float(v) * 100, 2)} for ts, v in r.items()]
    return {"series": series, "label": meta[series]["label"], "month": month, "years": years}
