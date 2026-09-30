"""계절성 C2 — 원본 `_selfcheck` 이식 + 빈 달 처리 + '근거 없음' 판정.

원본 산출물 전량 대조는 `scripts/verify_seasonality_port.py`(DB·원본 CSV 필요)가 한다.
"""
import math

import pandas as pd

from app.core import seasonality as sea


def test_original_selfcheck_signal_and_hit():
    b = (-0.01, 0.02)
    w = sea.T_SIG
    assert sea.signal(w * 0.6, 0.004, 30, b) == ("상승", 1)       # 유의하지 않음 → 롱 기본값
    assert sea.signal(-w * 0.6, -0.004, 30, b) == ("상승", 1)
    assert sea.signal(-w * 0.6, -0.03, 30, b) == ("상승", 1)
    assert sea.signal(w, 0.03, 30, b) == ("상승", 1)              # 경계는 판단 대상
    assert sea.signal(-w, 0.004, 30, b) == ("중립", 0)
    assert sea.signal(-w - 0.1, -0.03, 30, b) == ("하락", -1)
    assert sea.signal(-3.0, -0.03, 10, b) == ("상승", 1)          # 표본 부족 → 롱
    assert sea.signal(-3.0, -0.03, 5, b, need=5) == ("하락", -1)
    assert sea.signal(1.5, 0.015, 30, b) == ("중립", 0)
    assert sea.signal(1.5, 0.03, 30, b) == ("상승", 1)
    assert sea.signal(-1.5, -0.03, 30, b) == ("하락", -1)
    assert sea.signal(-1.5, -0.03, 30, None) == ("하락", -1)
    assert sea.hit(1, 0.02, b) == 1 and sea.hit(1, -0.02, b) == 0
    assert sea.hit(-1, -0.02, b) == 1 and sea.hit(-1, 0.02, b) == 0
    assert sea.hit(0, 0.015, b) == 1 and sea.hit(0, 0.05, b) == 0 and sea.hit(0, -0.02, b) == 0


def test_original_selfcheck_stats():
    assert abs(sea.tstat(pd.Series([1.0, 2.0, 3.0])) - 3.4641) < 1e-3
    assert abs(sea.pvalue(1.96) - 0.05) < 0.01
    assert abs(sea.pvalue(3.89, 5) - 0.0177) < 5e-4      # Student-t, df=4
    assert abs(sea.pvalue(1.96, 200) - 0.0514) < 1e-3
    idx = pd.date_range("2019-01-01", "2025-12-01", freq="MS")
    r = pd.Series(range(len(idx)), index=idx, dtype=float) / 100
    lo, hi = sea.tercile_band(r, 2026)
    sub = r["2021":"2025"]
    assert abs(lo - sub.quantile(1 / 3)) < 1e-12 and abs(hi - sub.quantile(2 / 3)) < 1e-12
    assert sea.tercile_band(r, 2019) is None
    assert len(sea.clip_window(r, 5)) == 60 and sea.clip_window(r, None) is r
    assert sea.min_n(None) == 15 and sea.min_n(10) == 10 and sea.min_n(5) == 5


def test_monthly_returns_leave_gap_and_next_month_empty():
    """⚠️지수를 하나만 넣어도 빈 달 다음 달이 NaN 이어야 한다(원본은 합집합 인덱스에 기대고 있었다)."""
    rets = sea.monthly_returns({"HSI": {"1964-07": 100.0, "1964-08": 101.0, "1964-10": 104.0}})
    hsi = rets["HSI"]
    assert list(hsi.index.strftime("%Y-%m")) == ["1964-07", "1964-08", "1964-09", "1964-10"]
    assert math.isclose(hsi["1964-08-01"], 0.01)
    assert math.isnan(hsi["1964-09-01"])       # 빈 달
    assert math.isnan(hsi["1964-10-01"])       # 두 달 변화(+3%)를 한 달로 세지 않는다


def test_evidence_marks_default_long():
    # |t| < T_SIG → '상승' 이 나오지만 근거는 없다(화면: 근거 없음)
    assert sea.signal(0.1, 0.01, 30, None) == ("상승", 1)
    assert sea.evidence(0.1, 30) is False
    assert sea.evidence(2.0, 30) is True
    assert sea.evidence(2.0, 10) is False      # 표본 부족도 근거 없음
