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


def test_far_events_beyond_crawl_horizon_are_not_marked_failed(rdb):
    """크롤 범위(35일) 밖 발표는 시도조차 안 했다 — 실패가 아니라 '수집 전'(실측 2026-10-04 NVDA·WMT 등)."""
    with rdb.begin() as c:
        c.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'WMT')"), {"i": uuid.uuid4()})
        c.execute(text("INSERT INTO earnings_events (ticker, quarter, report_date, eps_forecast, source) "
                       "VALUES ('WMT', '2026Q3', '2026-11-10', 0.6, 'nasdaq')"))

    def crawl(days, on_day=None):
        raise RuntimeError("write EINVAL")

    with pytest.raises(RuntimeError):
        er.collect(rdb, date(2026, 9, 27), crawl=crawl)
    with rdb.begin() as c:
        st = dict(c.execute(text("SELECT ticker, revenue_forecast_status FROM earnings_events")).all())
    assert st["BE"] == "failed" and st["WMT"] is None


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


def test_closer_day_without_forecast_does_not_keep_farther_value(rdb):
    """★2026-10-05 먼 날(+2) 값을 먼저 받고 더 가까운 날(+1)이 '컨센 없음'으로 오면, 먼 날 값을 남기지 않는다.

    크롤 도중엔 당일 매칭만 쓰고, 나머지는 끝날 때 가장 가까운 매칭으로 한 번 쓴다 → BE 는 실행 전 그대로(NULL).
    """
    def be():
        with rdb.begin() as c:
            return c.execute(text("SELECT revenue_forecast FROM earnings_events WHERE ticker = 'BE'")).scalar()

    def crawl(days, on_day=None):
        on_day(date(2026, 10, 29), [_row(date(2026, 10, 29), "BE", "", "0.8B")])
        assert be() is None                       # 당일이 아니면 크롤 도중엔 쓰지 않는다
        on_day(date(2026, 10, 28), [_row(date(2026, 10, 28), "BE", "", "")])
        return {}

    er.collect(rdb, date(2026, 9, 27), crawl=crawl)
    assert be() is None


def test_farther_day_is_saved_when_crawl_dies(rdb):
    """★2026-10-05 당일이 아닌 매칭도 크롤이 죽으면 except 경로에서 저장된다(받은 만큼은 남긴다)."""
    def crawl(days, on_day=None):
        on_day(date(2026, 10, 28), [_row(date(2026, 10, 28), "BE", "", "0.9B")])
        raise RuntimeError("write EINVAL")

    with pytest.raises(RuntimeError):
        er.collect(rdb, date(2026, 9, 27), crawl=crawl)
    with rdb.begin() as c:
        f, s = c.execute(text("SELECT revenue_forecast, revenue_forecast_status FROM earnings_events "
                              "WHERE ticker = 'BE'")).one()
    assert (float(f), s) == (9e8, "ok")


def test_wallclock_timeout_keeps_type_and_cause(rdb):
    """★2026-10-05 감싼 예외도 `WallClockTimeout` 이어야 worker main 이 timeout_wallclock 으로 적는다."""
    from wallclock import WallClockTimeout

    original = WallClockTimeout("timeout_wallclock: _crawl_streaming 10초 초과")

    def crawl(days, on_day=None):
        raise original

    with pytest.raises(WallClockTimeout) as ei:
        er.collect(rdb, date(2026, 9, 27), crawl=crawl)
    assert str(ei.value).startswith("timeout_wallclock") and "저장된 날짜 0/" in str(ei.value)
    assert ei.value.__cause__ is original
    with rdb.begin() as c:
        kind = c.execute(text("SELECT last_error_kind FROM source_status WHERE source = 'investing'")).scalar()
    assert kind == "timeout"


def test_cleanup_failure_does_not_mask_crawl_error(rdb, monkeypatch):
    """★2026-10-05 정리(_mark_failed·record_error)가 터져도 원래 크롤 오류가 올라온다."""
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(er, "_mark_failed", boom)
    monkeypatch.setattr(er, "record_error", boom)

    def crawl(days, on_day=None):
        raise RuntimeError("write EINVAL")

    with pytest.raises(RuntimeError, match="write EINVAL"):
        er.collect(rdb, date(2026, 9, 27), crawl=crawl)
    with pytest.raises(InvestingBlocked):
        er.collect(rdb, date(2026, 9, 27), crawl=lambda days, on_day=None: (_ for _ in ()).throw(InvestingBlocked("cf")))
