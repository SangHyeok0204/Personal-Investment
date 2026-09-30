"""계획 A2 — 13F 정보표·표지 파서(오프라인 고정 문서)."""
from sec.parsers import parse_cover_amendment, parse_infotable, pick_infotable, submissions_rows

INFOTABLE = """<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip>
    <value>174347703</value>
    <shrsOrPrnAmt><sshPrnamt>915560382</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>DFND</investmentDiscretion>
    <votingAuthority><Sole>915560382</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>TAIWAN SEMICONDUCTOR</nameOfIssuer><titleOfClass>SPONSORED ADS</titleOfClass>
    <cusip>874039100</cusip><value>1,200</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <putCall>Call</putCall><investmentDiscretion>SOLE</investmentDiscretion>
  </infoTable>
</informationTable>"""

# 버크셔 2023Q3 정정 두 종류(표지 구조는 SEC 13F 스키마 그대로, 값만 줄임)
COVER_RESTATE = """<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <formData><coverPage><reportCalendarOrQuarter>09-30-2023</reportCalendarOrQuarter>
  <isAmendment>true</isAmendment><amendmentInfo><amendmentType>RESTATEMENT</amendmentType></amendmentInfo>
  </coverPage></formData></edgarSubmission>"""
COVER_NEW = COVER_RESTATE.replace("RESTATEMENT", "NEW HOLDINGS")
COVER_ORIGINAL = """<edgarSubmission><formData><coverPage><isAmendment>false</isAmendment>
  </coverPage></formData></edgarSubmission>"""


def test_parse_infotable_rows_and_options():
    rows = parse_infotable(INFOTABLE)
    assert len(rows) == 2
    aapl, tsm = rows
    assert aapl["cusip"] == "037833100" and aapl["value"] == 174347703 and aapl["shares"] == 915560382
    assert aapl["shr_type"] == "SH" and aapl["vote_sole"] == 915560382
    assert tsm["put_call"] == "Call" and tsm["value"] == 1200      # 쉼표 제거, 옵션 행 보존(비중 계산에서 뺀다)
    assert tsm["vote_sole"] is None


def test_parse_infotable_bad_xml():
    assert parse_infotable("<not xml") == []


def test_cover_amendment_kinds():
    assert parse_cover_amendment(COVER_RESTATE) == (True, "RESTATEMENT")
    assert parse_cover_amendment(COVER_NEW) == (True, "NEW HOLDINGS")
    assert parse_cover_amendment(COVER_ORIGINAL) == (False, None)


def test_pick_infotable_from_index():
    idx = {"directory": {"item": [
        {"name": "primary_doc.xml"}, {"name": "0000950123-23-010898-index.html"},
        {"name": "27893.xml"},
    ]}}
    assert pick_infotable(idx) == "27893.xml"
    assert pick_infotable({"directory": {"item": [{"name": "form13fInfoTable.xml"}, {"name": "x.xml"}]}}) == "form13fInfoTable.xml"


def test_submissions_rows_zip():
    block = {"accessionNumber": ["a", "b"], "form": ["13F-HR", "13F-HR/A"], "filingDate": ["2023-11-14", "2024-05-15"],
             "reportDate": ["2023-09-30", "2023-09-30"], "primaryDocument": ["x/primary_doc.xml", "y/primary_doc.xml"]}
    rows = submissions_rows(block)
    assert rows[1] == {"accessionNumber": "b", "form": "13F-HR/A", "filingDate": "2024-05-15",
                       "reportDate": "2023-09-30", "primaryDocument": "y/primary_doc.xml"}
