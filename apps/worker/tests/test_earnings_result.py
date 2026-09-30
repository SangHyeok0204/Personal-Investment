"""계획 B4 — 발표 후 반응(세션 구간) · 보도자료 구조화 검증 · 결과 수집(8-K · 반응 · 장중 미룸)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from handlers import earnings_result as er
from handlers.llm_exhibit import _direction
from llm.exhibit import clip, scaled, validate
from prices import reaction as rx
from tests.test_earnings_calendar import EARN_DDL
from tests.test_sec_collect import SEC_DDL


def test_session_windows():
    base, end, label = rx.session_window(date(2026, 8, 26), "AMC")
    assert (base.hour, end.hour, end.minute, base.date()) == (16, 17, 30, date(2026, 8, 26)) and "장후" in label
    base, end, _ = rx.session_window(date(2026, 9, 28), "BMO")          # 월요일 장전 → 기준은 금요일 종가
    assert base.date() == date(2026, 9, 25) and (end.hour, end.minute) == (8, 30)
    assert rx.session_window(date(2026, 8, 26), None) is None            # 시각 모르면 값을 내지 않는다
    assert rx.toss_symbol("BRK-B") == "BRK.B" and rx.toss_symbol("NVDA") == "NVDA"


def test_compute_waits_for_window_end():
    base = {"dt": datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc), "close": 100.0}
    end = {"dt": datetime(2026, 8, 26, 21, 30, tzinfo=timezone.utc), "close": 103.7}
    end_at = datetime(2026, 8, 26, 21, 30, tzinfo=timezone.utc)
    assert rx.compute(base, end, end_at, now=datetime(2026, 8, 26, 21, 0, tzinfo=timezone.utc)) is None
    assert rx.compute(base, end, end_at, now=datetime(2026, 8, 27, tzinfo=timezone.utc)) == 3.7
    assert rx.us_regular_session_open(datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc))       # 월 11:00 ET
    assert not rx.us_regular_session_open(datetime(2026, 9, 28, 21, 45, tzinfo=timezone.utc))  # 17:45 ET


def test_exhibit_validation_and_units():
    ok, w = validate({"fiscal_quarter": "2027Q2", "eps": {"actual": 2.22}, "revenue": {"actual": 46.7, "unit": "B"},
                      "segments": [{"name": "Data Center", "revenue": 41.1, "unit": "B"}]})
    assert ok and w == []
    ok, w = validate({"fiscal_quarter": "Q2", "eps": {"actual": 1}})             # 분기를 못 읽어도 버리지 않는다
    assert ok and "회계분기" in w[0]
    from llm.exhibit import norm_quarter
    assert [norm_quarter(x) for x in ("2026Q2", "FY2026 Q2", "Q2 FY27", "2Q26", "Q3 2026", None)] == \
        ["2026Q2", "2026Q2", "2027Q2", "2026Q2", "2026Q3", None]
    assert validate({"fiscal_quarter": "2027Q2", "eps": {}, "revenue": {"actual": -1}})[0] is False
    ok, w = validate({"fiscal_quarter": "2027Q2", "revenue": {"actual": 10, "unit": "B"},
                      "segments": [{"name": "a", "revenue": 30, "unit": "B"}]})
    assert ok and "±50%" in w[0]
    assert scaled(46.7, "B") == Decimal("46700000000") and scaled(2.5, None) == Decimal("2.5")
    assert len(clip("x" * 50000)) < 30100 and len(clip("x" * 20000)) == 20000
    assert _direction(Decimal(110), Decimal(100)) == "raise" and _direction(Decimal("100.5"), Decimal(100)) == "maintain"
    assert _direction(Decimal(90), Decimal(100)) == "lower" and _direction(Decimal(1), None) == "new"


class FakeToss:
    def __init__(self):
        self.calls = []

    def _get(self, path, params):
        self.calls.append(params)
        return {"candles": [{"timestamp": "2026-08-27T05:00:00+09:00", "closePrice": "209.66"},     # 16:00 ET
                            {"timestamp": "2026-08-27T06:30:00+09:00", "closePrice": "217.41"}]}    # 17:30 ET


@pytest.fixture
def rdb(db):
    with db.begin() as c:
        c.execute(text(SEC_DDL + EARN_DDL))
        c.execute(text("TRUNCATE earnings_results, earnings_events, watchlist_items, jobs RESTART IDENTITY CASCADE"))
        c.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'NVDA')"), {"i": uuid.uuid4()})
        c.execute(text("INSERT INTO earnings_events (ticker, quarter, report_date, timing, source) "
                       "VALUES ('NVDA', '2026Q2', '2026-08-26', 'AMC', 'nasdaq')"))
    return db


def test_collect_filing_reaction_and_exhibit_job(rdb, monkeypatch):
    monkeypatch.setattr(er, "sec_get", lambda client, url: type("R", (), {"json": lambda self: {
        "0": {"cik_str": 1045810, "ticker": "NVDA"}}})())
    monkeypatch.setattr(er, "earnings_release", lambda sec, cik, asof: {
        "accession": "0001045810-26-000073", "url": "https://sec/x/q2fy27pr.htm", "form": "8-K",
        "filing_date": "2026-08-26", "text": "…"})
    toss = FakeToss()
    now = datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc)                  # 8/26 21:00 ET — 장 닫힘
    got = er.collect(rdb, now=now, sec=object(), toss=toss)
    assert got["filings"] == 1 and got["reactions"] == 1 and got["exhibit_jobs"] == 1
    with rdb.begin() as c:
        r = c.execute(text("SELECT filing_url, reaction_pct, reaction_window, detail FROM earnings_results")).one()
        jobs = c.execute(text("SELECT job_type, queue, payload FROM jobs")).all()
    assert r.filing_url.endswith("q2fy27pr.htm") and float(r.reaction_pct) == 3.7 and "장후" in r.reaction_window
    assert r.detail["filing_form"] == "8-K" and r.detail["reaction_base"] == 209.66
    assert [(j.job_type, j.queue, j.payload) for j in jobs] == \
        [("LLM_EXHIBIT", "llm", {"event_id": 1, "accession": "0001045810-26-000073"})]
    assert er.collect(rdb, now=now, sec=object(), toss=toss)["candidates"] == 0   # 다 채웠으면 끝


def test_reaction_deferred_while_market_open(rdb, monkeypatch):
    monkeypatch.setattr(er, "sec_get", lambda client, url: type("R", (), {"json": lambda self: {}})())
    toss = FakeToss()
    got = er.collect(rdb, now=datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc), sec=None, toss=toss)  # 11:00 ET
    assert got["reaction_deferred"] == 1 and toss.calls == []            # 토큰 충돌 방지 — 토스를 부르지 않는다


def test_6k_candidates_nearest_first_and_results_check():
    from sec.exhibit import earnings_filing_candidates, looks_like_results
    recent = {"form": ["6-K", "6-K", "6-K"], "items": ["", "", ""], "accessionNumber": ["notes", "results", "old"],
              "primaryDocument": ["a", "b", "c"], "filingDate": ["2026-08-19", "2026-08-12", "2026-07-01"]}
    got = [c["accession"] for c in earnings_filing_candidates(recent, date(2026, 8, 12))]
    assert got == ["results", "notes"]                              # 가까운 순 · 창 밖(7/01) 제외
    assert looks_like_results("Nebius reports second quarter 2026 results. Revenue was $45.8 million")
    assert not looks_like_results("Nebius announces proposed private offering of convertible senior notes")
    assert looks_like_results("Corning Announces Strong First-Quarter 2026 Financial Results. First-quarter core sales grew")


def test_plausible_revenue():
    from llm.exhibit import plausible_revenue
    assert not plausible_revenue(Decimal("45830000000"), Decimal("569900000"))     # NBIS 실측 — 80배
    assert plausible_revenue(Decimal("582300000"), Decimal("569900000"))
    assert plausible_revenue(Decimal("1"), None)                                    # 컨센 없으면 판단 안 함


def test_exhibit_store_replaces_unverified_import_revenue(rdb):
    from types import SimpleNamespace
    from handlers.llm_exhibit import store
    with rdb.begin() as c:
        c.execute(text("INSERT INTO earnings_results (event_id, revenue_actual, source) VALUES (1, 45830000000, 'import')"))
    ev = SimpleNamespace(id=1, ticker="NVDA", report_date=date(2026, 8, 26), revenue_forecast=Decimal("29220000000"),
                         revenue_forecast_source="import", revenue_actual=Decimal("45830000000"), detail={},
                         filing_url="u")
    data = {"currency": "USD", "revenue": {"actual": 582.3, "unit": "M"},
            "guidance": {"next_quarter_revenue": {"low": 0.9, "high": 1.1, "unit": "B"}}}
    out = store(rdb, ev, data, [], "m")
    assert out["guidance"] == 1 and "이관 매출" in out["warnings"][0]
    with rdb.begin() as c:
        rev = c.execute(text("SELECT revenue_actual FROM earnings_results WHERE event_id = 1")).scalar()
        g = c.execute(text("SELECT low, high, direction FROM earnings_guidance")).one()
    assert float(rev) == 582.3e6                                   # 이관(미검증) 45.83B → 8-K 582.3M
    assert (float(g.low), float(g.high), g.direction) == (9e8, 1.1e9, "new")


def test_past_event_never_takes_latest_quarter_8k():
    from sec.exhibit import earnings_filing_candidates
    recent = {"form": ["8-K", "8-K"], "items": ["2.02,9.01", "7.01,9.01"], "accessionNumber": ["q2", "q1"],
              "primaryDocument": ["a", "b"], "filingDate": ["2026-07-28", "2026-04-28"]}
    assert [c["accession"] for c in earnings_filing_candidates(recent, date(2026, 4, 28))] == ["q1"]   # GLW 실측
    assert [c["accession"] for c in earnings_filing_candidates(recent)] == ["q2"]                     # 날짜 없으면 최근


def test_release_fallback_by_name_then_size():
    """B7 감사 G8 — 문서 타입(EX-99.1)이 없을 때 원본처럼 파일명 → 크기 → 표지 순."""
    from sec.exhibit import select_release_by_name
    cover = {"name": "d8k.htm", "size": "20000"}
    assert select_release_by_name([cover, {"name": "ex99-1.htm", "size": "900"}], "d8k.htm") == "ex99-1.htm"
    assert select_release_by_name([cover, {"name": "q2fy27cfocommentary.htm", "size": "900"},      # 실측 NVDA
                                   {"name": "q2fy27pr.htm", "size": "900"}], "d8k.htm") == "q2fy27pr.htm"
    big = {"name": "cls-20260728prcondensedfs.htm", "size": "180000"}          # 원본 실측 CLS — 이름 규칙 밖
    assert select_release_by_name([cover, big, {"name": "R2.htm", "size": "999999"}], "d8k.htm") == big["name"]
    assert select_release_by_name([cover, {"name": "other.htm", "size": "30000"}], "d8k.htm") == "d8k.htm"
