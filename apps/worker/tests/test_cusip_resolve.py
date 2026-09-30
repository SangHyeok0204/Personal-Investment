"""계획 A4 — CUSIP 해소(OpenFIGI → SEC 이름 일치) · 캐시."""
import json

import httpx
import pytest
from sqlalchemy import text

import sec.client as sec_client_mod
import sec.cusip as cusip_mod
from handlers import cusip_resolve
from sec.client import RateLimiter
from sec.cusip import pick_figi, unique_name_map
from tests.test_sec_collect import SEC_DDL

CUSIP_DDL = """
CREATE TABLE IF NOT EXISTS cusip_map (cusip VARCHAR(9) PRIMARY KEY, name VARCHAR, ticker VARCHAR,
  confidence VARCHAR NOT NULL DEFAULT 'none', figi VARCHAR, updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
ALTER TABLE cusip_map ADD COLUMN IF NOT EXISTS sic VARCHAR;
ALTER TABLE cusip_map ADD COLUMN IF NOT EXISTS sector VARCHAR;
"""


def test_pick_prefers_us_composite_and_dash_class():
    entry = {"data": [
        {"ticker": "BRK/B", "exchCode": "UN", "figi": "X1"},
        {"ticker": "BRK/B", "exchCode": "US", "figi": "X2", "compositeFIGI": "C2", "name": "BERKSHIRE HATHAWAY"},
    ]}
    assert pick_figi(entry) == {"ticker": "BRK-B", "name": "BERKSHIRE HATHAWAY", "figi": "C2"}
    assert pick_figi({"warning": "No identifier found."}) is None


def test_unique_name_map_drops_collisions():
    m = unique_name_map({
        "0": {"ticker": "AAPL", "title": "Apple Inc."},
        "1": {"ticker": "GOOGL", "title": "Alphabet Inc."},
        "2": {"ticker": "GOOG", "title": "Alphabet Inc."},
    })
    assert m == {"APPLE": "AAPL"}


@pytest.fixture
def cdb(db):
    with db.begin() as c:
        c.execute(text(SEC_DDL + CUSIP_DDL))
        c.execute(text("TRUNCATE sec_filings, holdings_13f, cusip_map RESTART IDENTITY"))
        c.execute(text("INSERT INTO sec_filings (form_type, accession_number, period_of_report) "
                       "VALUES ('13F-HR', 'a1', '2026-06-30')"))
        c.execute(text(
            "INSERT INTO holdings_13f (accession_number, seq, name_of_issuer, cusip, value) VALUES "
            "('a1', 0, 'BANK AMER CORP', '060505104', 900), ('a1', 1, 'APPLE INC', '037833100', 800), "
            "('a1', 2, 'MYSTERY CO', 'ZZZZZZZZZ', 10), ('a1', 3, 'OLD MANUAL', '111111111', 5), "
            "('a1', 4, 'TRIED BEFORE', '222222222', 5)"))
        c.execute(text("INSERT INTO cusip_map (cusip, name, ticker, confidence, figi) VALUES "
                       "('111111111', 'OLD MANUAL', 'OLDM', 'manual', NULL), "
                       "('222222222', 'TRIED BEFORE', NULL, 'none', '')"))
    return db


def test_resolve_fills_and_caches(cdb, monkeypatch):
    monkeypatch.setattr(cusip_mod, "_figi_limiter", RateLimiter(10_000))
    monkeypatch.setattr(sec_client_mod, "_limiter", RateLimiter(10_000))
    asked = []

    def figi(req):
        ids = [b["idValue"] for b in json.loads(req.content)]
        asked.extend(ids)
        known = {"060505104": {"data": [{"ticker": "BAC", "exchCode": "US", "compositeFIGI": "BBG0"}]}}
        return httpx.Response(200, json=[known.get(i, {"warning": "No identifier found."}) for i in ids])

    def sec(req):
        return httpx.Response(200, json={"0": {"ticker": "AAPL", "title": "Apple Inc."}})

    fc = httpx.Client(transport=httpx.MockTransport(figi))
    sc = httpx.Client(transport=httpx.MockTransport(sec))
    got = cusip_resolve.resolve(cdb, fc, sc)
    assert got == {"targets": 3, "openfigi": 1, "exact": 1, "none": 1}
    assert set(asked) == {"060505104", "037833100", "ZZZZZZZZZ"}      # manual · 이미 물어본 것은 안 묻는다
    with cdb.begin() as c:
        m = {r.cusip: (r.ticker, r.confidence, r.figi) for r in c.execute(text("SELECT * FROM cusip_map"))}
    assert m["060505104"] == ("BAC", "openfigi", "BBG0")
    assert m["037833100"] == ("AAPL", "exact", "")
    assert m["ZZZZZZZZZ"] == (None, "none", "")
    assert m["111111111"] == ("OLDM", "manual", None)
    assert cusip_resolve.resolve(cdb, fc, sc) == {"targets": 0}              # 두 번째 회차는 할 일 없음


def test_openfigi_429_waits_a_minute(monkeypatch):
    calls = iter([httpx.Response(429), httpx.Response(200, json=[{"warning": "x"}])])
    slept = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: next(calls))) as c:
        got = cusip_mod.openfigi_lookup(c, ["000000000"], limiter=RateLimiter(10_000), sleep=slept.append)
    assert got == [None] and slept == [60]


def test_openfigi_timeout_and_disconnect_retried():
    n = {"c": 0}

    def flaky(req):
        n["c"] += 1
        if n["c"] == 1:
            raise httpx.ReadTimeout("slow", request=req)
        if n["c"] == 2:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=req)
        return httpx.Response(200, json=[{"warning": "x"}])

    slept = []
    with httpx.Client(transport=httpx.MockTransport(flaky)) as c:
        assert cusip_mod.openfigi_lookup(c, ["000000000"], limiter=RateLimiter(10_000), sleep=slept.append) == [None]
    assert slept == [1, 2]


def test_foreign_cins_and_lowercase():
    sent = []

    def h(req):
        sent.extend(json.loads(req.content))
        return httpx.Response(200, json=[{"warning": "x"}] * 3)

    with httpx.Client(transport=httpx.MockTransport(h)) as c:
        cusip_mod.openfigi_lookup(c, ["N07059210", "48251w104", "037833100"], limiter=RateLimiter(10_000))
    assert sent == [{"idType": "ID_CINS", "idValue": "N07059210"}, {"idType": "ID_CUSIP", "idValue": "48251W104"},
                    {"idType": "ID_CUSIP", "idValue": "037833100"}]


def test_sic_to_sector_ranges():
    from sec.sic import sic_to_sector
    assert sic_to_sector("7372") == "정보기술"           # 소프트웨어
    assert sic_to_sector(2834) == "헬스케어"             # 제약
    assert sic_to_sector("1311") == "에너지"
    assert sic_to_sector("1531") == "임의소비재"         # 주택 건설
    assert sic_to_sector("6798") == "부동산" and sic_to_sector("6022") == "금융"
    assert sic_to_sector("4922") == "에너지" and sic_to_sector("4911") == "유틸리티"
    assert sic_to_sector("9995") is None and sic_to_sector("") is None and sic_to_sector(None) is None


def test_fill_sectors_once_per_company(cdb, monkeypatch):
    monkeypatch.setattr(sec_client_mod, "_limiter", RateLimiter(10_000))
    with cdb.begin() as c:
        c.execute(text("INSERT INTO cusip_map (cusip, name, ticker, confidence) VALUES "
                       "('060505104', 'BANK AMER', 'BAC', 'openfigi'), ('037833100', 'APPLE', 'AAPL', 'exact'), "
                       "('ZZZZZZZZZ', 'MYSTERY', 'ZZZZ', 'openfigi')"))
    calls = []

    def sec(req):
        calls.append(str(req.url))
        if req.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 70858, "ticker": "BAC"},
                                             "1": {"cik_str": 320193, "ticker": "AAPL"}})
        sic = {"CIK0000070858.json": "6021", "CIK0000320193.json": "3571"}[req.url.path.rsplit("/", 1)[-1]]
        return httpx.Response(200, json={"sic": sic})

    with httpx.Client(transport=httpx.MockTransport(sec)) as sc:
        got = cusip_resolve.fill_sectors(cdb, sc)
        again = cusip_resolve.fill_sectors(cdb, sc)
    assert got == {"sector_targets": 4, "sector_filled": 2, "companies": 2}   # + 수동 OLDM(SEC 목록에 없음)
    assert again == {"sector_targets": 0}                       # '' = 찾아봤지만 없음 → 다시 안 묻는다
    with cdb.begin() as c:
        m = {r.cusip: (r.sic, r.sector) for r in c.execute(text("SELECT cusip, sic, sector FROM cusip_map"))}
    assert m["060505104"] == ("6021", "금융") and m["037833100"] == ("3571", "정보기술")
    assert m["ZZZZZZZZZ"] == ("", None)
