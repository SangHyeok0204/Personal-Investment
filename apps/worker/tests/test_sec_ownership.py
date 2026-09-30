"""계획 A3b — Form 4 · 13D/G 파서(오프라인 고정 문서)."""
from datetime import date

from sec.ownership import parse_13dg, parse_form4

# 공동 신고: 펀드 + 운용역이 같은 매수를 함께 신고. 계획매도(10b5-1) 각주 하나, 파생 행 하나.
FORM4_JOINT = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerCik>0001045810</issuerCik><issuerName>NVIDIA CORP</issuerName>
    <issuerTradingSymbol>nvda</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>1111111</rptOwnerCik><rptOwnerName>ALPHA FUND LP</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isTenPercentOwner>1</isTenPercentOwner></reportingOwnerRelationship>
  </reportingOwner>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>2222222</rptOwnerCik><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>1</isOfficer>
      <officerTitle>CFO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-09-10</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>1,000</value></transactionShares>
        <transactionPricePerShare><value>150.5</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-09-11</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode><footnoteId id="F1"/></transactionCoding>
      <transactionAmounts><transactionShares><value>200</value></transactionShares>
        <transactionPricePerShare><value>160</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction>
      <securityTitle><value>Stock Option</value></securityTitle>
      <transactionDate><value>2026-09-12</value></transactionDate>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>300</value></transactionShares></transactionAmounts>
    </derivativeTransaction>
  </derivativeTable>
  <footnotes><footnote id="F1">Sold pursuant to a Rule 10b5-1 trading plan adopted 2026-03-01.</footnote></footnotes>
</ownershipDocument>"""


def test_form4_joint_filing_lists_all_owners_without_duplicating_rows():
    rows, owners = parse_form4(FORM4_JOINT)
    assert len(rows) == 3                                  # 거래 3건 — 보고자 2명이어도 복제하지 않는다
    assert [o["name"] for o in owners] == ["ALPHA FUND LP", "DOE JANE"]
    assert rows[0]["insider_name"] == "ALPHA FUND LP; DOE JANE"
    assert rows[0]["insider_role"] == "10% Owner; Director, Officer (CFO)"
    assert rows[0]["ticker"] == "NVDA" and rows[0]["issuer_cik"] == "0001045810"


def test_form4_codes_flags_and_values():
    rows, _ = parse_form4(FORM4_JOINT)
    buy, sell, opt = rows
    assert buy["transaction_code"] == "P" and buy["buy_sell"] == "BUY" and buy["is_open_market"]
    assert buy["shares"] == 1000 and buy["transaction_value"] == 150500
    assert buy["transaction_date"] == date(2026, 9, 10) and not buy["is_planned_trade"]
    assert sell["buy_sell"] == "SELL" and sell["is_planned_trade"]          # 10b5-1 각주
    assert opt["is_derivative"] and opt["is_option_exercise"] and opt["buy_sell"] == "NEUTRAL"


def test_form4_document_level_10b5_flag():
    xml = FORM4_JOINT.replace("<issuer>", "<aff10b5One>1</aff10b5One><issuer>", 1)
    rows, _ = parse_form4(xml)
    assert all(r["is_planned_trade"] for r in rows)


def test_13dg_structured_cover():
    xml = """<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13D">
      <formData><coverPageHeader><issuerInfo><issuerCik>0001045810</issuerCik>
      <issuerName>NVIDIA CORP</issuerName><cusipNumber>67066G104</cusipNumber></issuerInfo>
      <dateOfEvent>09/01/2026</dateOfEvent></coverPageHeader>
      <reportingPersons><reportingPersonInfo><aggregateAmountOwned>12,345,678</aggregateAmountOwned>
      <percentOfClass>5.1</percentOfClass></reportingPersonInfo></reportingPersons></formData>
    </edgarSubmission>"""
    ev = parse_13dg(xml)
    assert ev["subject_name"] == "NVIDIA CORP" and ev["cusip"] == "67066G104"
    assert ev["percent"] == 5.1 and ev["shares"] == 12345678 and ev["subject_cik"] == "0001045810"
    assert ev["event_date"] == date(2026, 9, 1)


def test_13dg_unreadable():
    assert parse_13dg("not xml") is None
    assert parse_13dg("<x><y/></x>") is None
