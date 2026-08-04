"""WRAP ① 전일확정 수익률의 기준일 판정.

2026-07-31 이전에는 이 모듈이 ``이상 포트폴리오 수익률.xlsx`` 의 ``Price`` 시트에서
종목별 최근 2영업일 종가와 날짜별 환율을 읽어 ① 을 직접 계산했다. 지금은 ① 이
운용역 소스 시트(``수익률_breakdown`` / ``TORUS_수익률``)의 E(T-2)·F(T-1) 종가와
``USDKRW`` 행 환율만으로 종목 단위에서 계산되므로(collector/wrap.py), Price 시트
판독기(``read_price_closes``/``compute_ret1``)는 제거했다. Price 시트는 리밸런싱
이력의 기여도 계산에서만 쓰인다(wrap.py ``_read_price_series``).

남은 것은 '기대 기준일' 판정 하나 — 카드의 '미갱신' 배지가 이 값을 쓴다.
"""
from __future__ import annotations

from datetime import date, timedelta


def expected_basis_date(today: date) -> date:
    """오늘(KST) 기준 '가장 최근 확정된 미장 종가일' = 오늘 직전 평일.

    미장 7/21 종가는 KST 7/22 05:00 확정 → 7/22 어느 시각이든 기대 최신종가일=7/21.
    주말은 건너뛴다(미 공휴일은 미반영 — 드물게 '미갱신' 오탐 가능, 날짜라벨은 정확).
    """
    d = today - timedelta(days=1)
    while d.weekday() >= 5:  # 5=토, 6=일
        d -= timedelta(days=1)
    return d
