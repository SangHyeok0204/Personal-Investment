"""price_returns 회귀 테스트 — 수익률 모니터의 순수 계산부.

xlsx 판독(_load_series)은 겨누지 않는다(openpyxl·마운트 의존) — compute_asset 에
합성 시계열을 넣는다. 원본과 같은 "주말 ffill 일단위" 모양으로 만든다.

  1) 고정 시간창 4종의 기준일: DtD=전 영업일, WtD=지난주 금요일, MtD=전월 말일,
     YtD=전년 12/31 — %수익률 수치까지 검산
  2) unit="bp": 금리는 %수익률이 아니라 변화폭 bp
  3) 저점 대비 상승: 3창 값은 단조증가하지만 √시간 정규화로 최근의 급반등(1주)이
     완만한 장기 반등(3달)을 이긴다
  4) 스파크 다운샘플: 60점 이하·양 끝점 보존
  5) fail-soft: 빈 시계열 → None, 짧은 시계열 → 계산 불가 항목만 None
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import price_returns as pr  # noqa: E402


def _daily(start: date, end: date, base: float, overrides: dict[date, float]):
    """start~end 매일 한 점(주말 포함 — 원본의 ffill 모양). overrides 로 앵커값 지정."""
    out = []
    d = start
    while d <= end:
        out.append((d, overrides.get(d, base)))
        d += timedelta(days=1)
    return out


def test_fixed_window_anchors_pct():
    # last=2026-08-26(수). DtD 앵커=8/25(화), WtD=지난주 금 8/21, MtD=7/31, YtD=전년 12/31.
    series = _daily(date(2025, 12, 31), date(2026, 8, 26), 90.0, {
        date(2025, 12, 31): 80.0,
        date(2026, 7, 31): 100.0,
        date(2026, 8, 21): 104.0,
        date(2026, 8, 25): 106.0,
        date(2026, 8, 26): 110.0,
    })
    out = pr.compute_asset(series, key="t", name="테스트", unit="pct")
    assert out["asof"] == "2026-08-26"
    assert out["last"] == 110.0
    r = out["returns"]
    assert r["ytd"] == pytest.approx(37.5)            # 110/80
    assert r["mtd"] == pytest.approx(10.0)            # 110/100
    assert r["wtd"] == pytest.approx(110 / 104 * 100 - 100)
    assert r["dtd"] == pytest.approx(110 / 106 * 100 - 100)


def test_dtd_skips_weekend():
    # last=월요일 → DtD 앵커는 일요일(ffill)이 아니라 금요일이어야 한다.
    series = _daily(date(2026, 8, 17), date(2026, 8, 24), 100.0, {
        date(2026, 8, 21): 100.0,  # 금
        date(2026, 8, 22): 100.0,  # 토(ffill)
        date(2026, 8, 23): 100.0,  # 일(ffill)
        date(2026, 8, 24): 103.0,  # 월
    })
    out = pr.compute_asset(series, key="t", name="테스트", unit="pct")
    assert out["returns"]["dtd"] == pytest.approx(3.0)


def test_yield_uses_bp():
    # last=2026-01-06(화). YtD 앵커=2025-12-31 → (4.155-4.10)×100 = +5.5bp.
    series = _daily(date(2025, 12, 30), date(2026, 1, 6), 4.20, {
        date(2025, 12, 30): 4.00,
        date(2025, 12, 31): 4.10,
        date(2026, 1, 5): 4.30,
        date(2026, 1, 6): 4.155,
    })
    out = pr.compute_asset(series, key="y", name="금리", unit="bp")
    r = out["returns"]
    assert r["ytd"] == pytest.approx(5.5)
    assert r["dtd"] == pytest.approx(-14.5)           # 4.155 - 4.30
    # 저점 대비도 bp — 창 내 최저 4.00(12/30) 대비 +15.5bp
    assert out["rebound"]["value"] == pytest.approx(15.5)


def test_rebound_normalization_prefers_recent_spike():
    # 3달 전 저점 100→110(+10%)은 완만, 1주 전 저점 101.85→110(+8%)은 급반등.
    # 값 자체는 3m(10%) > 1w(8%)로 단조지만 √시간 정규화 점수는 1w 가 이긴다:
    #   8/√7 ≈ 3.02  >  10/√91 ≈ 1.05
    last = date(2026, 8, 26)
    series = _daily(last - timedelta(days=91), last, 108.0, {
        last - timedelta(days=85): 100.0,               # 3달 창의 저점
        last - timedelta(days=5): 110.0 / 1.08,         # 1주 창의 저점 (+8%)
        last: 110.0,
    })
    out = pr.compute_asset(series, key="t", name="테스트", unit="pct")
    reb = out["rebound"]
    assert reb["window"] == "1w"
    assert reb["label"] == "1주일 저점 대비"
    assert reb["value"] == pytest.approx(8.0)
    # 3종 전부 동봉 + 창이 길수록 저점이 낮아 단조증가
    assert reb["all"]["3m"] >= reb["all"]["1m"] >= reb["all"]["1w"]
    assert reb["all"]["3m"] == pytest.approx(10.0)


def test_spark_downsample_keeps_endpoints():
    last = date(2026, 8, 26)
    series = [(last - timedelta(days=i), float(1000 - i)) for i in range(400)][::-1]
    out = pr.compute_asset(series, key="t", name="테스트", unit="pct")
    spark = out["spark"]
    assert len(spark) == pr.SPARK_POINTS
    # 스파크 창은 최근 1년 — 시작점은 365일 창 안의 첫 값, 끝점은 마지막 값
    assert spark[-1] == 1000.0
    assert spark[0] == min(v for d, v in series if d > last - timedelta(days=pr.SPARK_DAYS))


def test_fail_soft():
    assert pr.compute_asset([], key="t", name="테스트", unit="pct") is None
    # 한 점짜리 — 기준일이 시계열 시작 전이라 수익률은 전부 None, 저점 대비는 0
    out = pr.compute_asset([(date(2026, 8, 26), 100.0)], key="t", name="테스트", unit="pct")
    assert all(v is None for v in out["returns"].values())
    assert out["rebound"]["value"] == pytest.approx(0.0)
    assert out["spark"] == [100.0]
