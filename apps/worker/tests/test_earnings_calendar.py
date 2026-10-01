"""계획 B3a — Nasdaq 캘린더 → 실적 표(향후 4주 · 지난 발표의 당시 컨센/실적/서프라이즈)."""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from handlers import earnings_calendar as ec
from prices.earnings import EarningsEvent
from tests.test_sec_collect import SEC_DDL

EARN_DDL = """
CREATE TABLE IF NOT EXISTS earnings_events (id BIGSERIAL PRIMARY KEY, ticker VARCHAR NOT NULL, quarter VARCHAR(8) NOT NULL,
  company VARCHAR, report_date DATE, timing VARCHAR(8), eps_forecast NUMERIC(14,4), n_estimates INTEGER,
  revenue_forecast NUMERIC(20,2), revenue_forecast_status VARCHAR, revenue_forecast_source VARCHAR,
  market_cap NUMERIC(20,2), source VARCHAR NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ticker, quarter));
CREATE TABLE IF NOT EXISTS earnings_results (event_id BIGINT PRIMARY KEY REFERENCES earnings_events(id) ON DELETE CASCADE,
  eps_actual NUMERIC(14,4), revenue_actual NUMERIC(20,2), eps_surprise_pct NUMERIC(10,2), revenue_surprise_pct NUMERIC(10,2),
  verdict VARCHAR, filing_accession VARCHAR, filing_url TEXT, reaction_pct NUMERIC(10,2), reaction_window VARCHAR,
  reaction_note TEXT, source VARCHAR NOT NULL, collected_at TIMESTAMPTZ NOT NULL DEFAULT now(), detail JSONB);
"""
TODAY = date(2026, 9, 27)


def _ev(d, sym, **kw):
    base = dict(report_date=d, ticker=sym, company=sym + " Inc", timing="장후", eps_forecast=Decimal("1.00"),
                estimate_count=10, last_year_eps=None, market_cap=Decimal("1e12"))
    return EarningsEvent(**{**base, **kw})


@pytest.fixture
def edb(db):
    with db.begin() as c:
        c.execute(text(SEC_DDL + EARN_DDL))
        c.execute(text("TRUNCATE earnings_results, earnings_events, watchlist_items RESTART IDENTITY CASCADE"))
        for t in ("NVDA", "GOOGL"):
            c.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, :t)"), {"i": uuid.uuid4(), "t": t})
        # B1 이관분 — 미검증 컨센(2.08)과 원본 판정
        eid = c.execute(text(
            "INSERT INTO earnings_events (ticker, quarter, report_date, timing, eps_forecast, source) "
            "VALUES ('NVDA', '2026Q2', '2026-08-26', 'AMC', 2.08, 'import') RETURNING id")).scalar()
        c.execute(text("INSERT INTO earnings_results (event_id, eps_actual, verdict, source, detail) "
                       "VALUES (:e, 2.22, '상회', 'import', '{\"forecast_unverified\": true}')"), {"e": eid})
    return db


def test_verdict_rule():
    assert ec.verdict(Decimal("6.2"), None) == "상회"
    assert ec.verdict(Decimal("-3"), None) == "하회" and ec.verdict(Decimal("2.9"), Decimal("-2.9")) == "부합"
    assert ec.verdict(Decimal("-5"), Decimal("3.1")) == "상회"        # 원본: 하나라도 +3% 면 상회가 먼저
    assert ec.verdict(None, None) is None


def test_collect_upcoming_and_past(edb):
    calls = []

    def fake(start, days):
        calls.append((start, days))
        if days == ec.RECENT_DAYS + ec.AHEAD_DAYS:
            return [_ev(date(2026, 10, 28), "GOOG", timing="장후", eps_forecast=Decimal("2.51")),   # 별칭 GOOG → GOOGL
                    _ev(date(2026, 10, 2), "AAPL")]                                              # 대상 아님
        if start == date(2026, 8, 26):
            return [_ev(start, "NVDA", timing="미정", eps_forecast=Decimal("2.09"),
                        eps_actual=Decimal("2.22"), eps_surprise_pct=Decimal("6.22"))]
        return []

    got = ec.collect(edb, TODAY, fetch=fake)
    assert got["upcoming"] == 1 and got["past_filled"] == 1 and got["past_missing"] == []
    with edb.begin() as c:
        g = c.execute(text("SELECT quarter, report_date, timing, eps_forecast, source FROM earnings_events "
                           "WHERE ticker = 'GOOGL'")).one()
        n = c.execute(text("SELECT e.eps_forecast, e.timing, r.eps_actual, r.eps_surprise_pct, r.verdict, r.source, "
                           "r.detail FROM earnings_events e JOIN earnings_results r ON r.event_id = e.id "
                           "WHERE e.ticker = 'NVDA'")).one()
    assert (g.quarter, str(g.report_date), g.timing, g.eps_forecast, g.source) == \
        ("2026Q3", "2026-10-28", "AMC", Decimal("2.5100"), "nasdaq")
    assert n.eps_forecast == Decimal("2.0900")            # 미검증 이관 컨센(2.08) → 당시 Nasdaq 컨센
    assert n.timing == "AMC"                               # 지난 날짜의 '미정'이 기존 장후를 지우지 않는다
    assert (n.eps_actual, n.eps_surprise_pct, n.verdict, n.source) == (Decimal("2.2200"), Decimal("6.22"), "상회", "nasdaq")
    assert n.detail["forecast_unverified"] is False
    assert ec.collect(edb, TODAY, fetch=fake)["past_checked"] == 0        # 이미 채운 건 다시 안 부른다


def test_import_revenue_not_used_and_blank_surprise_computed(edb):
    with edb.begin() as c:
        eid = c.execute(text(
            "INSERT INTO earnings_events (ticker, quarter, report_date, eps_forecast, revenue_forecast, "
            "revenue_forecast_source, source) VALUES ('GOOGL', '2026Q1', '2026-04-28', 0.7, 4.63e9, 'import', 'import') "
            "RETURNING id")).scalar()
        c.execute(text("INSERT INTO earnings_results (event_id, revenue_actual, source) VALUES (:e, 4.35e9, 'import')"),
                  {"e": eid})

    def fake(start, days):
        if start == date(2026, 4, 28):   # Nasdaq 이 surprise 를 비워 보낸 날
            return [_ev(start, "GOOGL", eps_forecast=Decimal("0.70"), eps_actual=Decimal("0.70"), eps_surprise_pct=None)]
        return []

    ec.collect(edb, TODAY, fetch=fake)
    with edb.begin() as c:
        r = c.execute(text("SELECT eps_surprise_pct, verdict FROM earnings_results WHERE event_id = :e"), {"e": eid}).one()
    assert r.eps_surprise_pct == Decimal("0.00") and r.verdict == "부합"    # 이관 매출(−6%)로 '하회'가 되지 않는다


def test_recently_reported_ticker_added_after_the_report_is_caught(edb):
    """발표 다음 날 관심종목에 넣은 종목(2026-10-01 MU) — 행이 생기고 같은 실행에서 EPS 까지 채운다."""
    with edb.begin() as c:
        c.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'MU')"), {"i": uuid.uuid4()})
    reported = date(2026, 9, 25)                       # TODAY(9/27) 이틀 전

    def fake(start, days):
        if days == ec.RECENT_DAYS + ec.AHEAD_DAYS:
            assert start <= reported                   # 지난 2주도 훑는다
            return [_ev(reported, "MU", eps_forecast=Decimal("31.41"))]
        if start == reported:
            return [_ev(reported, "MU", timing="미정", eps_forecast=Decimal("31.41"),
                        eps_actual=Decimal("33.00"), eps_surprise_pct=Decimal("5.06"))]
        return []

    got = ec.collect(edb, TODAY, fetch=fake)
    assert got["past_filled"] >= 1
    with edb.begin() as c:
        mu = c.execute(text("SELECT e.report_date, e.timing, r.eps_actual, r.verdict FROM earnings_events e "
                            "JOIN earnings_results r ON r.event_id = e.id WHERE e.ticker = 'MU'")).one()
    assert (mu.report_date, mu.timing, mu.eps_actual, mu.verdict) == (reported, "AMC", Decimal("33.0000"), "상회")
