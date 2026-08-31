"""rate_topics 회귀 테스트 — 금리 5주제의 순수 파서.

xlsx 판독(_read_sheets)은 겨누지 않는다(마운트 의존) — 파서에 합성 행을 넣는다.

  1) 채권: 연도 요약·발행사 합계·최신 발행일. ★Issue Date 가 **텍스트**로 저장돼
     있다는 게 이 시트의 함정이다(_출처.md 경고) — 문자열 날짜를 읽어야 asof 가 산다
  2) 다계열 시트: '#N/A' 문자열 건너뛰기, 계열별 last/last_date
  3) 주간 솎기: 같은 주는 마지막 값만
  4) fail-soft: 빈 입력 → 주제 전부 None
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import rate_topics as rt  # noqa: E402


def test_bonds_text_issue_date_and_totals():
    # 실제 시트 모양: B~K 발행내역 + M~N 연도요약(위쪽 몇 행에만).
    rows = [
        (None, "Alphabet Inc", "GOOGL", "2026-08-27", 2_000_000_000, 6.9,
         "2046-08-27", "REGS", "#N/A N/A", "AT MATURITY", "USD", None, 2025, 108.412),
        (None, "Oracle Corp", "ORCL", "2026-02-04", 1_000_000_000, 6.55,
         "2046-02-04", None, "BBB-", "CALLABLE", "USD", None, 2026, 223.075),
        (None, "Alphabet Inc", "GOOGL", "2020-04-01", 3_000_000_000, 3.6,
         "2040-04-01", None, "BBB-", "CALLABLE", "USD", None, None, None),
    ]
    b = rt.parse_bonds(rows)
    assert b["by_year"] == [[2025, 108.412], [2026, 223.075]]
    assert b["total_b"] == pytest.approx(331.49)  # 소수 2자리 반올림해서 낸다
    assert b["n"] == 3
    # ★텍스트 날짜를 못 읽으면 여기가 None 이 된다
    assert b["asof"] == "2026-08-27"
    assert [(g["ticker"], g["amt_b"], g["n"]) for g in b["by_issuer"]] == [
        ("GOOGL", 5.0, 2),
        ("ORCL", 1.0, 1),
    ]


def test_multi_series_skips_na_strings():
    header = (None, "Date", "미국 CPI YoY (%)", "클리블랜드 (%)")
    rows = [
        (None, datetime(2026, 8, 3), 3.1, "#N/A"),
        (None, datetime(2026, 8, 10), 3.2, 3.0),
        (None, datetime(2026, 8, 17), 3.4, 3.36),
    ]
    out = rt.parse_inflation(rows, header)
    assert out["asof"] == "2026-08-17"
    cpi = next(s for s in out["series"] if s["key"] == "cpi")
    cle = next(s for s in out["series"] if s["key"] == "cleveland")
    assert cpi["label"] == "미국 CPI YoY (%)"
    assert (cpi["last"], cpi["last_date"]) == (3.4, "2026-08-17")
    # '#N/A' 행은 그 계열에서만 빠진다 — 다른 계열은 멀쩡하다
    assert len(cle["points"]) == 2
    assert len(cpi["points"]) == 3


def test_weekly_downsample_keeps_last_of_week():
    header = (None, "Date", "WTI CL1", "CL6", "CL12", "스프레드")
    # 같은 주(2026-08-17 월 ~ 21 금) 5영업일 → 1점만 남아야 한다
    rows = [(None, datetime(2026, 8, d), float(d), 0.0, 0.0, 0.0) for d in (17, 18, 19, 20, 21)]
    out = rt.parse_wti(rows, header)
    cl1 = next(s for s in out["series"] if s["key"] == "cl1")
    assert cl1["points"] == [["2026-08-21", 21.0]]
    assert cl1["last"] == 21.0


def test_monthly_topics_are_not_downsampled():
    header = (None, "Date", "ADP 증감 (천명)", "12개월 이동평균 (천명)")
    rows = [(None, datetime(2026, m, 28), float(m), float(m) * 2) for m in (5, 6, 7)]
    out = rt.parse_adp(rows, header)
    chg = next(s for s in out["series"] if s["key"] == "chg")
    assert len(chg["points"]) == 3  # 월별은 그대로


def test_fail_soft():
    out = rt.build_payload({})
    assert all(out[k] is None for k in ("bonds", "inflation", "wti", "adp", "fomc_prob"))
    assert out["note"] is None
    # 값이 하나도 없는 시트는 계열을 만들지 않는다
    empty = rt.parse_fomc_prob([(None, datetime(2026, 8, 3), "#N/A")], (None, "Date", "확률 (%)"))
    assert empty["series"] == []
    assert empty["asof"] is None
