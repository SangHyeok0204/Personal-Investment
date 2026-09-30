"""계획 A3b — SEC 수집기(가짜 SEC 응답 · 실제 테스트 DB).

- 13F: 원 공시 + NEW HOLDINGS 정정이 둘 다 들어오고 정정 종류가 적힌다(합산은 API 규칙).
- Form 4: 공동 신고 보고자 전원 · 4/A 가 앞선 거래를 대체 · 이미 받은 접수번호는 다시 안 받는다.
- 13D/G: 구조화 표지는 보유 이벤트로, 못 읽는 옛 서식은 색인만.
"""
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import text

import sec.client as sec_client_mod
from handlers import sec_collect
from sec.client import RateLimiter
from sec.ownership import parse_form4
from tests.test_sec_ownership import FORM4_JOINT
from tests.test_sec_parsers import COVER_NEW

SEC_DDL = """
CREATE TABLE IF NOT EXISTS guru_roster (cik VARCHAR(10) PRIMARY KEY, guru_name VARCHAR, firm VARCHAR NOT NULL,
  filer_name VARCHAR NOT NULL, kind VARCHAR NOT NULL, active BOOLEAN NOT NULL DEFAULT true,
  backfill_status VARCHAR NOT NULL DEFAULT 'pending', backfill_from DATE NOT NULL DEFAULT '2013-04-01',
  added_at TIMESTAMPTZ NOT NULL DEFAULT now(), note TEXT);
CREATE TABLE IF NOT EXISTS sec_filings (id BIGSERIAL PRIMARY KEY, form_type VARCHAR NOT NULL,
  accession_number VARCHAR NOT NULL, filing_date DATE, period_of_report DATE, issuer_name VARCHAR,
  issuer_cik VARCHAR(10), filer_name VARCHAR, filer_cik VARCHAR(10), watch_cik VARCHAR(10), watch_name VARCHAR,
  amendment_type VARCHAR, headline TEXT, summary_json JSONB, source_url TEXT,
  crawled_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (accession_number, form_type));
CREATE TABLE IF NOT EXISTS holdings_13f (id BIGSERIAL PRIMARY KEY, accession_number VARCHAR NOT NULL,
  seq INTEGER NOT NULL DEFAULT 0, name_of_issuer VARCHAR, title_of_class VARCHAR, cusip VARCHAR(9),
  value NUMERIC(20,2), shares NUMERIC(24,4), shr_type VARCHAR, put_call VARCHAR, investment_discretion VARCHAR,
  vote_sole NUMERIC(24,4), vote_shared NUMERIC(24,4), vote_none NUMERIC(24,4));
CREATE TABLE IF NOT EXISTS form4_transactions (id BIGSERIAL PRIMARY KEY, accession_number VARCHAR NOT NULL,
  seq INTEGER NOT NULL DEFAULT 0, issuer_name VARCHAR, issuer_cik VARCHAR(10), ticker VARCHAR, insider_name VARCHAR,
  insider_cik VARCHAR(10), insider_role VARCHAR, transaction_date DATE, transaction_code VARCHAR(4),
  transaction_description VARCHAR, buy_sell VARCHAR, shares NUMERIC(24,4), price NUMERIC(20,6),
  transaction_value NUMERIC(24,2), shares_owned_after NUMERIC(24,4), ownership_type VARCHAR,
  acquired_disposed VARCHAR(1), is_derivative BOOLEAN NOT NULL DEFAULT false,
  is_open_market BOOLEAN NOT NULL DEFAULT false, is_option_exercise BOOLEAN NOT NULL DEFAULT false,
  is_planned_trade BOOLEAN NOT NULL DEFAULT false, superseded_by VARCHAR);
CREATE TABLE IF NOT EXISTS ownership_events (id BIGSERIAL PRIMARY KEY, accession_number VARCHAR NOT NULL,
  seq INTEGER NOT NULL DEFAULT 0, subject_name VARCHAR, subject_cik VARCHAR(10), cusip VARCHAR(9),
  filer_name VARCHAR, percent NUMERIC(9,4), shares NUMERIC(24,4), event_date DATE,
  is_amendment BOOLEAN NOT NULL DEFAULT false, is_activist BOOLEAN NOT NULL DEFAULT false);
CREATE TABLE IF NOT EXISTS watchlist_items (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker VARCHAR NOT NULL UNIQUE, asset_name VARCHAR, memo TEXT, target_price NUMERIC(20,6),
  stop_price NUMERIC(20,6), sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
"""

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
BRK = "0001067983"
NVDA = "0001045810"

INFOTABLE = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
<infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip>
<value>1000</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
<investmentDiscretion>SOLE</investmentDiscretion></infoTable></informationTable>"""


def _subs(name, rows):
    keys = ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument")
    return {"name": name, "filings": {"recent": {k: [r[i] for r in rows] for i, k in enumerate(keys)}}}


@pytest.fixture
def sec_db(db):
    with db.begin() as c:
        c.execute(text(SEC_DDL))
        c.execute(text("TRUNCATE guru_roster, sec_filings, holdings_13f, form4_transactions, ownership_events, "
                       "watchlist_items RESTART IDENTITY"))
    return db


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch):
    monkeypatch.setattr(sec_client_mod, "_limiter", RateLimiter(10_000))
    yield
    sec_client_mod._reset_for_tests()            # 403 시험이 건 10분 차단을 다음 시험에 넘기지 않는다


def _client(routes: dict[str, object], calls: list[str]):
    def handler(req: httpx.Request):
        url = str(req.url)
        calls.append(url)
        body = routes.get(url)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, json=body) if isinstance(body, dict) else httpx.Response(200, text=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_13f_new_holdings_amendment_is_stored_with_type(sec_db):
    with sec_db.begin() as c:
        c.execute(text("INSERT INTO guru_roster (cik, guru_name, firm, filer_name, kind) "
                       "VALUES (:c, 'Warren Buffett', 'Berkshire', 'BERKSHIRE', 'guru')"), {"c": BRK})
    arch = "https://www.sec.gov/Archives/edgar/data/1067983/"
    idx = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "infotable.xml"}]}}
    routes = {
        f"https://data.sec.gov/submissions/CIK{BRK}.json": _subs("BERKSHIRE", [
            ("0000950123-23-010898", "13F-HR", "2023-11-14", "2023-09-30", "primary_doc.xml"),
            ("0000950123-24-005653", "13F-HR/A", "2024-05-15", "2023-09-30", "xslForm13F_X02/primary_doc.xml"),
        ]),
        arch + "000095012323010898/index.json": idx, arch + "000095012323010898/infotable.xml": INFOTABLE,
        arch + "000095012324005653/index.json": idx, arch + "000095012324005653/infotable.xml": INFOTABLE,
        arch + "000095012324005653/primary_doc.xml": COVER_NEW,
    }
    calls: list[str] = []
    with _client(routes, calls) as cl:
        got = sec_collect.collect_13f(sec_db, cl)
        assert got["added"] == 2 and got["amendments"] == {"NEW HOLDINGS": 1}
        again = sec_collect.collect_13f(sec_db, cl)           # 이미 받은 공시는 원문을 다시 받지 않는다
    assert again["added"] == 0
    with sec_db.begin() as c:
        rows = c.execute(text("SELECT form_type, amendment_type, (SELECT count(*) FROM holdings_13f h "
                              "WHERE h.accession_number = f.accession_number) FROM sec_filings f "
                              "ORDER BY filing_date")).all()
    assert [tuple(r) for r in rows] == [("13F-HR", None, 1), ("13F-HR/A", "NEW HOLDINGS", 1)]


def _form4_routes(extra=None):
    arch = "https://www.sec.gov/Archives/edgar/data/1045810/"
    routes = {
        "https://www.sec.gov/files/company_tickers.json": {"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA"}},
        f"https://data.sec.gov/submissions/CIK{NVDA}.json": _subs("NVIDIA CORP", [
            ("0001-26-000002", "4/A", "2026-09-15", "", "xslF345X05/form4a.xml"),
            ("0001-26-000001", "4", "2026-09-12", "", "xslF345X05/form4.xml"),
            ("0001-25-000009", "4", "2025-01-02", "", "form4.xml"),          # 조회 기간 밖
            ("0001-26-000003", "8-K", "2026-09-20", "", "x.htm"),            # 다른 서식
        ]),
        arch + "000126000001/form4.xml": FORM4_JOINT,
        # 정정본: 같은 매수를 주수만 고쳐 다시 신고
        arch + "000126000002/form4a.xml": FORM4_JOINT.replace("<value>1,000</value>", "<value>1,100</value>"),
    }
    routes.update(extra or {})
    return routes


def test_form4_joint_filers_and_amendment_supersedes(sec_db):
    with sec_db.begin() as c:
        c.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (gen_random_uuid(), 'NVDA')"))
    calls: list[str] = []
    with _client(_form4_routes(), calls) as cl:
        got = sec_collect.collect_form4(sec_db, cl, now=NOW)
    assert got["issuers"] == 1 and got["added"] == 2 and got["failed"] == 0
    assert got["latest_filing"] == "2026-09-15"
    assert not any("000125000009" in u for u in calls)        # 기간 밖은 원문을 받지 않는다
    with sec_db.begin() as c:
        tx = c.execute(text("SELECT accession_number, transaction_code, shares, superseded_by, insider_name "
                            "FROM form4_transactions ORDER BY accession_number, seq")).all()
        summary = c.execute(text("SELECT summary_json FROM sec_filings WHERE form_type = '4'")).scalar()
    # 목록은 최신순(4/A 먼저)이지만 오래된 것부터 넣으므로 정정이 원 공시 거래를 대체한다.
    by = {(a, code): (float(sh), sup) for a, code, sh, sup, _ in tx}
    assert by[("0001-26-000001", "P")] == (1000.0, "0001-26-000002")
    assert by[("0001-26-000001", "S")] == (200.0, "0001-26-000002")
    assert by[("0001-26-000002", "P")] == (1100.0, None)
    assert tx[0].insider_name == "ALPHA FUND LP; DOE JANE"
    assert [o["name"] for o in summary["owners"]] == ["ALPHA FUND LP", "DOE JANE"]


def test_13dg_structured_and_legacy(sec_db):
    xml_13g = """<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13g"><formData><coverPageHeader>
      <issuerInfo><issuerCik>0001045810</issuerCik><issuerName>NVIDIA CORP</issuerName>
      <issuerCusips><issuerCusipNumber>67066G104</issuerCusipNumber></issuerCusips></issuerInfo>
      <eventDateRequiresFilingThisStatement>06/30/2026</eventDateRequiresFilingThisStatement></coverPageHeader>
      <coverPageHeaderReportingPersonDetails><aggregateAmountOwned>1500000000</aggregateAmountOwned>
      <classPercent>6.1</classPercent></coverPageHeaderReportingPersonDetails></formData></edgarSubmission>"""
    arch = "https://www.sec.gov/Archives/edgar/data/1045810/"
    routes = _form4_routes({
        f"https://data.sec.gov/submissions/CIK{NVDA}.json": _subs("NVIDIA CORP", [
            ("0002-26-000001", "SCHEDULE 13G", "2026-08-01", "", "xslSCHEDULE_13G_X01/primary_doc.xml"),
            ("0002-24-000001", "SC 13G/A", "2026-04-01", "", "d1.txt"),
        ]),
        arch + "000226000001/primary_doc.xml": xml_13g,
    })
    with sec_db.begin() as c:
        c.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (gen_random_uuid(), 'NVDA')"))
    with _client(routes, []) as cl:
        got = sec_collect.collect_13dg(sec_db, cl, now=NOW)
    assert got == {"watch": 1, "added": 2, "parsed": 1}
    with sec_db.begin() as c:
        ev = c.execute(text("SELECT subject_name, cusip, percent, event_date, is_amendment FROM ownership_events")).one()
        legacy = c.execute(text("SELECT form_type, summary_json FROM sec_filings "
                                "WHERE accession_number = '0002-24-000001'")).one()
    assert ev.subject_name == "NVIDIA CORP" and ev.cusip == "67066G104" and float(ev.percent) == 6.1
    assert str(ev.event_date) == "2026-06-30" and ev.is_amendment is False
    assert legacy.form_type == "13G" and legacy.summary_json["parsed"] is False and legacy.summary_json["amendment"]


def test_missing_user_agent_records_config_error(sec_db, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    logs = []
    with pytest.raises(sec_client_mod.SecConfigError):
        sec_collect.run_form4(sec_db, "job", {}, None, lambda *a: logs.append(a))
    with sec_db.begin() as c:
        row = c.execute(text("SELECT last_error_kind FROM source_status WHERE source = 'sec_form4'")).one()
    assert row.last_error_kind == "config"


def test_blocked_records_403(sec_db, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test test@example.com")
    monkeypatch.setattr(sec_collect, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(403))))
    with sec_db.begin() as c:
        c.execute(text("INSERT INTO guru_roster (cik, firm, filer_name, kind) VALUES (:c, 'B', 'B', 'guru')"),
                  {"c": BRK})
    with pytest.raises(sec_client_mod.SecBlocked):
        sec_collect.run_13f(sec_db, "job", {}, None, lambda *a: None)
    with sec_db.begin() as c:
        row = c.execute(text("SELECT last_error_kind, last_ok_at FROM source_status WHERE source = 'sec_13f'")).one()
    assert row.last_error_kind == "403" and row.last_ok_at is None


def test_form4_original_arriving_after_its_amendment_is_superseded(sec_db):
    """같은 날 4/A 가 원 공시보다 먼저 접수된 경우(실측 ONTO) — 순서와 무관하게 한 번만 센다."""
    rows, owners = parse_form4(FORM4_JOINT)
    kw = dict(filing_date=None, url="u", watch_cik=NVDA, watch_name="NVIDIA", rows=rows, owners=owners)
    assert sec_collect.store_form4(sec_db, acc="x-26-000005", form="4/A", **kw) == 0
    assert sec_collect.store_form4(sec_db, acc="x-26-000007", form="4", **kw) == 3
    with sec_db.begin() as c:
        live = c.execute(text("SELECT DISTINCT accession_number FROM form4_transactions "
                              "WHERE superseded_by IS NULL")).scalars().all()
    assert live == ["x-26-000005"]


def test_backfill_new_guru_from_sec_pages(sec_db):
    """새 거장: 과거 페이지까지 훑어 2013Q2 이후만 · NEW HOLDINGS 정정 종류 기록 · 끝나면 done + CUSIP 작업 예약."""
    cik = "0001079114"
    with sec_db.begin() as c:
        c.execute(text("INSERT INTO guru_roster (cik, guru_name, firm, filer_name, kind) "
                       "VALUES (:c, 'David Einhorn', 'Greenlight', 'GREENLIGHT CAPITAL INC', 'guru')"), {"c": cik})
        c.execute(text("DELETE FROM jobs WHERE job_type = 'CUSIP_RESOLVE'"))
    arch = "https://www.sec.gov/Archives/edgar/data/1079114/"
    idx = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "infotable.xml"}]}}
    sub = _subs("GREENLIGHT", [("0001-24-000001", "13F-HR", "2024-02-14", "2023-12-31", "primary_doc.xml")])
    sub["filings"]["files"] = [{"name": "CIK0001079114-submissions-001.json"}]
    old_page = _subs("", [
        ("0001-14-000002", "13F-HR/A", "2014-06-01", "2014-03-31", "primary_doc.xml"),
        ("0001-14-000001", "13F-HR", "2014-05-15", "2014-03-31", "primary_doc.xml"),
        ("0001-12-000001", "13F-HR", "2012-11-14", "2012-09-30", "form13f.txt"),       # 2013Q2 이전 — 건너뜀
    ])["filings"]["recent"]
    routes = {
        f"https://data.sec.gov/submissions/CIK{cik}.json": sub,
        "https://data.sec.gov/submissions/CIK0001079114-submissions-001.json": old_page,
        arch + "000124000001/index.json": idx, arch + "000124000001/infotable.xml": INFOTABLE,
        arch + "000114000001/index.json": idx, arch + "000114000001/infotable.xml": INFOTABLE,
        arch + "000114000002/index.json": idx, arch + "000114000002/infotable.xml": INFOTABLE,
        arch + "000114000002/primary_doc.xml": COVER_NEW,
    }
    calls: list[str] = []
    with _client(routes, calls) as cl:
        got = sec_collect.backfill_guru(sec_db, cl, cik)
    assert got["added"] == 3 and got["amendments"] == {"NEW HOLDINGS": 1} and got["periods"] == 2
    assert not any("000112000001" in u for u in calls)
    with sec_db.begin() as c:
        st = c.execute(text("SELECT backfill_status, note FROM guru_roster WHERE cik = :c"), {"c": cik}).one()
        amend = c.execute(text("SELECT amendment_type FROM sec_filings WHERE accession_number = '0001-14-000002'")).scalar()
        queued = c.execute(text("SELECT count(*) FROM jobs WHERE job_type = 'CUSIP_RESOLVE' AND status = 'PENDING'")).scalar()
    assert st.backfill_status == "done" and "2분기" in st.note
    assert amend == "NEW HOLDINGS" and queued == 1


def test_backfill_failure_marks_failed(sec_db, monkeypatch):
    cik = "0001079114"
    with sec_db.begin() as c:
        c.execute(text("INSERT INTO guru_roster (cik, firm, filer_name, kind) VALUES (:c, 'G', 'G', 'guru')"), {"c": cik})
    with pytest.raises(sec_client_mod.SecBlocked):
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as cl:
            sec_collect.backfill_guru(sec_db, cl, cik)
    with sec_db.begin() as c:
        st = c.execute(text("SELECT backfill_status, note FROM guru_roster WHERE cik = :c"), {"c": cik}).one()
    assert st.backfill_status == "failed" and "SecBlocked" in st.note
