"""계획 B3b — Investing.com 매출 컨센 크롤(파싱 · 날짜 창 · 막힘 → '수집 실패')."""
import uuid
from datetime import date

import pytest
from sqlalchemy import text

from handlers import earnings_revenue as er
from prices.investing import InvestingBlocked, InvestingRow, header_date, parse_company_ticker, rows_from_cells
from tests.test_earnings_calendar import EARN_DDL
from tests.test_sec_collect import SEC_DDL


def test_parsing():
    assert parse_company_ticker("Inventiva ( IVA )") == ("Inventiva", "IVA")        # 지금 서식(괄호 안 공백)
    assert parse_company_ticker("Palantir(PLTR)Palantir") == ("Palantir", "PLTR")  # 옛 서식
    assert header_date("Wednesday, August 26, 2026") == date(2026, 8, 26) and header_date("NVIDIA ( NVDA )") is None
    r = rows_from_cells(["", "NVIDIA ( NVDA )", "2.22 /", "2.08", "96.2B /", "91.9B", "5.43T", ""], 1, date(2026, 8, 26))
    assert (r.ticker, r.eps, r.revenue, r.revenue_forecast, r.timing) == ("NVDA", "2.22", "96.2B", "91.9B", "After Market")
    assert rows_from_cells(["", "Sunday, September 27, 2026", "", "", "", "", ""], 0, date(2026, 9, 27)) is None
    assert er.money("91.9B") == 91900000000 and er.money("6M") == 6000000 and er.money("") is None


def test_weekday_window():
    assert er.weekday_window(date(2026, 10, 27)) == [date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 27),
                                                     date(2026, 10, 28), date(2026, 10, 29)]


@pytest.fixture
def rdb(db):
    with db.begin() as c:
        c.execute(text(SEC_DDL + EARN_DDL))
        c.execute(text("TRUNCATE earnings_results, earnings_events, watchlist_items RESTART IDENTITY CASCADE"))
        for t in ("NVDA", "BE"):
            c.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, :t)"), {"i": uuid.uuid4(), "t": t})
        past = c.execute(text("INSERT INTO earnings_events (ticker, quarter, report_date, eps_forecast, source) "
                              "VALUES ('NVDA', '2026Q2', '2026-08-26', 2.09, 'nasdaq') RETURNING id")).scalar()
        c.execute(text("INSERT INTO earnings_results (event_id, eps_actual, eps_surprise_pct, verdict, source) "
                       "VALUES (:e, 2.22, 1.0, '부합', 'nasdaq')"), {"e": past})
        c.execute(text("INSERT INTO earnings_events (ticker, quarter, report_date, eps_forecast, source) "
                       "VALUES ('BE', '2026Q3', '2026-10-27', 0.57, 'nasdaq')"))
    return db


def _row(d, t, rev, rev_f):
    return InvestingRow(d, t, t, "", "", rev, rev_f, "", "")


def test_collect_fills_forecast_and_actual_nearest_day(rdb):
    today = date(2026, 9, 27)

    def crawl(days, on_day=None):
        assert date(2026, 10, 27) in days and date(2026, 8, 26) in days
        return {date(2026, 10, 28): [_row(date(2026, 10, 28), "BE", "", "0.9B")],      # 예상일 다음 날에 올라옴
                date(2026, 8, 26): [_row(date(2026, 8, 26), "NVDA", "96.2B", "91.9B")]}

    got = er.collect(rdb, today, crawl=crawl)
    assert got["revenue_forecast"] == 2 and got["revenue_actual"] == 1
    with rdb.begin() as c:
        be = c.execute(text("SELECT revenue_forecast, revenue_forecast_status, revenue_forecast_source FROM "
                            "earnings_events WHERE ticker = 'BE'")).one()
        nv = c.execute(text("SELECT r.revenue_actual, r.revenue_surprise_pct, r.verdict FROM earnings_results r "
                            "JOIN earnings_events e ON e.id = r.event_id WHERE e.ticker = 'NVDA'")).one()
    assert (float(be.revenue_forecast), be.revenue_forecast_status, be.revenue_forecast_source) == (9e8, "ok", "investing")
    assert float(nv.revenue_actual) == 96.2e9 and float(nv.revenue_surprise_pct) == 4.68
    assert nv.verdict == "상회"                          # EPS +1% 는 부합이지만 검증된 매출 +4.7% → 상회(원본 규칙)


def test_blocked_marks_upcoming_failed(rdb):
    def crawl(days, on_day=None):
        raise InvestingBlocked("Cloudflare 통과 실패 — 제목 'Just a moment...'")

    with pytest.raises(InvestingBlocked):
        er.collect(rdb, date(2026, 9, 27), crawl=crawl)
    with rdb.begin() as c:
        st = dict(c.execute(text("SELECT ticker, revenue_forecast_status FROM earnings_events")).all())
        src = c.execute(text("SELECT last_error_kind FROM source_status WHERE source = 'investing'")).scalar()
    assert st == {"BE": "failed", "NVDA": None} and src == "blocked"     # 다가오는 발표만 "수집 실패"


def test_partial_crawl_keeps_saved_days_and_fails_only_unfilled(rdb):
    """⚠️2026-10-04 — 드라이버가 죽으면 모은 날짜가 다 날아갔다. 이제 받은 날은 그때그때 저장된다."""
    today = date(2026, 9, 27)
    with rdb.begin() as c:
        c.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'GLW')"), {"i": uuid.uuid4()})
        c.execute(text("INSERT INTO earnings_events (ticker, quarter, report_date, eps_forecast, source) "
                       "VALUES ('GLW', '2026Q3', '2026-10-28', 0.5, 'nasdaq')"))

    def crawl(days, on_day=None):
        on_day(date(2026, 10, 29), [_row(date(2026, 10, 29), "BE", "", "0.8B")])    # 먼 날 먼저
        on_day(date(2026, 10, 27), [_row(date(2026, 10, 27), "BE", "", "0.9B")])    # 같은 날이 덮어쓴다
        raise RuntimeError("write EINVAL")

    with pytest.raises(RuntimeError) as ei:
        er.collect(rdb, today, crawl=crawl)
    assert "write EINVAL" in str(ei.value) and "저장된 날짜 2/" in str(ei.value)
    with rdb.begin() as c:
        st = {t: (f and float(f), s) for t, f, s in c.execute(text(
            "SELECT ticker, revenue_forecast, revenue_forecast_status FROM earnings_events")).all()}
        err = c.execute(text("SELECT last_error_message FROM source_status WHERE source = 'investing'")).scalar()
    assert st == {"BE": (9e8, "ok"), "GLW": (None, "failed"), "NVDA": (None, None)}
    assert "저장된 날짜 2/" in err
