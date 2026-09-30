"""계획 A2 — 13F 정정공시 규칙(버크셔 2023Q3 = 152 + 1 = 153종목)."""
from datetime import date

from app.core.guru13f import Filing13F, effective_accessions

# 실측(원본 filings.db): 버크셔 2023-09-30 공시 셋 — 11/14(152행) · 11/16(152행) · 2024-05-15(1행)
BRK_ROWS = {"0000950123-23-010898": 152, "0000950123-23-011029": 152, "0000950123-24-005653": 1}


def test_berkshire_2023q3_restatement_then_new_holdings():
    filings = [
        Filing13F("0000950123-23-010898", date(2023, 11, 14), "13F-HR", None),
        Filing13F("0000950123-23-011029", date(2023, 11, 16), "13F-HR/A", "RESTATEMENT"),
        Filing13F("0000950123-24-005653", date(2024, 5, 15), "13F-HR/A", "NEW HOLDINGS"),
    ]
    eff, warnings = effective_accessions(filings)
    assert eff == ["0000950123-23-011029", "0000950123-24-005653"]
    assert sum(BRK_ROWS[a] for a in eff) == 153          # 원본 규칙이면 1
    assert warnings == []


def test_restatement_after_new_holdings_resets():
    f = [
        Filing13F("a", date(2024, 2, 14), "13F-HR", None),
        Filing13F("b", date(2024, 5, 1), "13F-HR/A", "NEW HOLDINGS"),
        Filing13F("c", date(2024, 6, 1), "13F-HR/A", "RESTATEMENT"),
    ]
    assert effective_accessions(f)[0] == ["c"]


def test_unknown_amendment_is_conservative_and_warned():
    f = [
        Filing13F("a", date(2024, 2, 14), "13F-HR", None),
        Filing13F("b", date(2024, 3, 1), "13F-HR/A", None),
    ]
    eff, warnings = effective_accessions(f)
    assert eff == ["b"] and len(warnings) == 1
