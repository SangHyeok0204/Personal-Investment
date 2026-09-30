"""계획 B1 — 어닝모니터 엑셀 이관 파싱."""
from datetime import date
from decimal import Decimal

from app.core import earnings_import as ei

HEADER = ("기업명", "티커", "관리상태", "보유펀드", "최근실적발표일", "예정실적발표일", "Before/After", "시가총액",
          "예상매출", "예상EPS", "관전포인트1", "관전포인트2", "관전포인트3", "관전포인트4", "결과매출", "결과EPS",
          "컨센대비", "관전포인트결과1", "관전포인트결과2", "관전포인트결과3", "관전포인트결과4", "기타시장반응")


def test_money_timing_quarter():
    assert ei.parse_money("108.86B") == Decimal("108860000000")
    assert ei.parse_money("4.89T") == Decimal("4890000000000") and ei.parse_money("815.6M") == Decimal("815600000")
    assert ei.parse_money(1.6) == Decimal("1.6") and ei.parse_money("-0.84") == Decimal("-0.84")
    assert ei.parse_money("") is None and ei.parse_money("N/A") is None
    assert ei.parse_timing("After Market") == "AMC" and ei.parse_timing("Before Market") == "BMO"
    assert ei.parse_timing(None) is None
    # 원본 derive_fiscal_quarter: 1~3월 발표 = 전년 Q4, 4~6 = Q1, 7~9 = Q2, 10~12 = Q3
    assert ei.quarter_of(date(2026, 2, 25)) == "2025Q4" and ei.quarter_of(date(2026, 5, 20)) == "2026Q1"
    assert ei.quarter_of(date(2026, 8, 26)) == "2026Q2" and ei.quarter_of(date(2026, 11, 3)) == "2026Q3"
    assert ei.norm_ticker("GOOG US") == "GOOGL" and ei.norm_ticker("aapl us equity") == "AAPL"


def test_result_rows_filters_targets_and_skips_failure_text():
    rows = [
        ("Apple", "AAPL", "활성", "9002Q", "2026-07-30", None, "After Market", "4.89T", "108.86B", "1.89",
         "p1", "p2", "p3", "p4", "109.42B", "2.02", "상회", "r1", None, None, None, "note"),
        ("BridgeBio", "BBIO", "활성", "x", "2026-05-07", None, "After Market", "13.2B", "178.16M", "-0.68",
         "[타임아웃] CLI 응답 500초 초과", None, None, None, "194.5M", "-0.84", "상회", None, None, None, None, None),
        ("Airbnb", "ABNB", "비활성", "x", "2026-05-07", None, "After Market", "1B", "1B", "0.3",
         None, None, None, None, None, None, None, None, None, None, None, None),
    ]
    out = ei.result_rows(HEADER, rows, {"AAPL", "BBIO"})
    assert [o["event"]["ticker"] for o in out] == ["AAPL", "BBIO"]           # ABNB 는 대상 아님
    a = out[0]
    assert a["event"]["quarter"] == "2026Q2" and a["event"]["timing"] == "AMC"
    assert a["event"]["revenue_forecast"] == Decimal("108860000000")
    assert a["event"]["revenue_forecast_status"] == "unverified"
    assert a["event"]["revenue_forecast_source"] == "import"
    assert a["result"]["verdict"] == "상회" and a["result"]["eps_actual"] == Decimal("2.02")
    assert a["result"]["eps_surprise_pct"] is None and a["result"]["detail"]["forecast_unverified"]  # 원본 예상치 불신
    assert a["points"][0] == (1, "p1", "r1")
    assert out[1]["points"][0] == (1, None, None)                              # 실패 문구는 내용이 아니다


def test_watchpoint_rows():
    rows = [("AAOI", "2026Q2", "1", "포인트", "결과"), ("NVDA", "2026Q2", 2, "[오류] 실패", None),
            ("NVDA", "bad", 1, "x", None), ("NVDA", "2026Q2", 5, "x", None), ("GOOG", "2026Q1", 3, "p", None)]
    got = ei.watchpoint_rows(rows, {"NVDA", "GOOGL"})
    assert got == [{"ticker": "GOOGL", "quarter": "2026Q1", "rank": 3, "point": "p", "result": None}]
    assert ei.text_or_none("nan") is None and ei.text_or_none(" NaN ") is None and ei.text_or_none("0") == "0"


def test_surprise_pct():
    assert ei.surprise_pct(Decimal("2.2"), Decimal("2.0")) == Decimal("10.00")
    assert ei.surprise_pct(Decimal("-0.5"), Decimal("-1.0")) == Decimal("50.00")
    assert ei.surprise_pct(Decimal("1"), Decimal("0")) is None
