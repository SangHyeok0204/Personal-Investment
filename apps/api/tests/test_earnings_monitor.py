"""계획 B3a — 실적 모니터 API(주 경계 · 다가오는 발표 · 최근 결과)."""
import json
import pytest
import uuid
from datetime import date, timedelta

from sqlalchemy import text

from app.api.earnings_monitor import _week_start


def test_week_start_weekend_rolls_forward():
    assert _week_start(date(2026, 9, 27)) == date(2026, 9, 28)     # 일요일 → 다가오는 월요일
    assert _week_start(date(2026, 9, 26)) == date(2026, 9, 28)     # 토요일
    assert _week_start(date(2026, 9, 30)) == date(2026, 9, 28)     # 수요일 → 이번 주 월요일


def test_overview_and_stock(client, db):
    today = date.today()
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'NVDA')"), {"i": uuid.uuid4()})
    up = db.execute(text(
        "INSERT INTO earnings_events (ticker, quarter, report_date, timing, eps_forecast, source) "
        "VALUES ('NVDA', '2026Q9', :d, 'AMC', 2.47, 'nasdaq') RETURNING id"), {"d": today + timedelta(days=40)}).scalar()
    past = db.execute(text(
        "INSERT INTO earnings_events (ticker, quarter, report_date, timing, eps_forecast, source) "
        "VALUES ('NVDA', '2026Q8', :d, 'AMC', 2.09, 'import') RETURNING id"), {"d": today - timedelta(days=30)}).scalar()
    db.execute(text("INSERT INTO earnings_results (event_id, eps_actual, eps_surprise_pct, verdict, source, detail) "
                    "VALUES (:e, 2.22, 6.22, '상회', 'nasdaq', '{\"eps_from\": \"nasdaq calendar\"}')"), {"e": past})
    db.execute(text("INSERT INTO earnings_watchpoints (ticker, quarter, rank, point, source) "
                    "VALUES ('NVDA', '2026Q9', 1, '데이터센터', 'llm')"))
    db.commit()
    d = client.get("/api/v1/research/earnings/overview").json()
    assert d["targets"] == ["NVDA"] and d["next"]["id"] == up and d["next"]["within_4w"] is False
    assert d["upcoming"][0]["timing"] == "장후" and d["upcoming"][0]["revenue_forecast_status"] is None
    assert d["recent"][0]["eps_surprise_pct"] == 6.22 and d["recent"][0]["verified"] is True
    s = client.get("/api/v1/research/earnings/stock/nvda").json()
    assert [e["quarter"] for e in s["events"]] == ["2026Q9", "2026Q8"]
    assert s["events"][0]["watchpoints"][0]["point"] == "데이터센터"
    assert client.get("/api/v1/research/earnings/stock/ZZZ").status_code == 404


def test_results_ready_after_window(db):
    from datetime import datetime, timezone
    from app.core.sec_sync import results_ready
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'NVDA')"), {"i": uuid.uuid4()})
    db.execute(text("INSERT INTO earnings_events (ticker, quarter, report_date, timing, source) "
                    "VALUES ('NVDA', '2026Q2', '2026-08-26', 'AMC', 'nasdaq')"))
    db.commit()
    assert not results_ready(db, datetime(2026, 8, 26, 21, 0, tzinfo=timezone.utc))   # 17:00 ET — 아직
    assert results_ready(db, datetime(2026, 8, 26, 21, 45, tzinfo=timezone.utc))      # 17:45 ET — 장후 구간 끝
    assert not results_ready(db, datetime(2026, 10, 30, tzinfo=timezone.utc))         # 30일 넘으면 그만



def test_watchpoints_due_d3(db):
    from datetime import datetime, timezone
    from app.core.sec_sync import watchpoints_due
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'GLW')"), {"i": uuid.uuid4()})
    db.execute(text("INSERT INTO earnings_events (ticker, quarter, report_date, source) VALUES "
                    "('GLW', '2026Q3', '2026-10-27', 'nasdaq'), ('GLW', '2026Q4', '2027-01-27', 'nasdaq')"))
    db.commit()
    at = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)                 # 10/24 09:00 KST — D-3
    assert watchpoints_due(db, at) == [("GLW", "2026Q3")]                 # 먼 발표는 아직
    db.execute(text("INSERT INTO jobs (id, job_type, status, queue, payload, created_at, updated_at) VALUES "
                    "(gen_random_uuid(), 'LLM_WATCHPOINTS', 'FAILED', 'llm', "
                    "'{\"ticker\": \"GLW\", \"quarter\": \"2026Q3\"}', :t, :t)"), {"t": at})
    db.commit()
    assert watchpoints_due(db, at) == []                                  # 오늘 이미 시도 — 내일 07:30 에 다시
    assert watchpoints_due(db, datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc)) == [("GLW", "2026Q3")]


@pytest.mark.parametrize(
    'source,detail,rev_source,eps_surprise,rev_surprise,expected',
    [
        ('nasdaq', {'import': 'workbook', 'eps_from': 'nasdaq calendar', 'forecast_unverified': False},
         'import', 10, None, (True, False, True, False, True)),
        ('sec', {'filing_form': '8-K'}, 'import', None, None, (False, False, False, False, False)),
        ('sec', {'exhibit_parsed': True, 'currency': 'USD'},
         'import', None, None, (False, False, False, False, False)),
        ('nasdaq', {'forecast_unverified': False},
         'import', 10, None, (False, False, False, False, False)),
        ('investing', {'revenue_from': 'investing'},
         'investing', None, 10, (False, True, False, True, True)),
        ('nasdaq', {'eps_from': 'nasdaq calendar'},
         'investing', 10, 10, (True, True, True, False, False)),
        ('nasdaq', {'eps_from': 'nasdaq calendar'},
         'import', 0, None, (True, False, True, False, False)),
        ('import', {'verdict_source': '원본 판정(컨센대비 칸)'},
         'import', None, None, (False, False, False, False, False)),
    ],
)
def test_field_provenance_both_endpoints(client, db, source, detail, rev_source,
                                         eps_surprise, rev_surprise, expected):
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:id, 'NVDA')"), {'id': uuid.uuid4()})
    eid = db.execute(text(
        "INSERT INTO earnings_events (ticker, quarter, report_date, eps_forecast, revenue_forecast, "
        "revenue_forecast_source, revenue_forecast_status, source) "
        "VALUES ('NVDA', '2026Q2', :day, 2, 100, :rev_source, 'ok', 'import') RETURNING id"),
        {'day': date.today() - timedelta(days=5), 'rev_source': rev_source}).scalar_one()
    db.execute(text(
        "INSERT INTO earnings_results (event_id, eps_actual, revenue_actual, eps_surprise_pct, "
        "revenue_surprise_pct, verdict, source, detail, filing_url) "
        "VALUES (:id, 2.2, 110, :eps_s, :rev_s, '상회', :source, CAST(:detail AS JSONB), 'https://sec.gov/filing')"),
        {'id': eid, 'eps_s': eps_surprise, 'rev_s': rev_surprise, 'source': source, 'detail': json.dumps(detail)})
    db.commit()
    overview = client.get('/api/v1/research/earnings/overview')
    stock = client.get('/api/v1/research/earnings/stock/NVDA')
    assert overview.status_code == stock.status_code == 200
    keys = ('eps_forecast_verified', 'revenue_forecast_verified', 'eps_actual_verified',
            'revenue_actual_verified', 'verdict_verified')
    for event in (overview.json()['recent'][0], stock.json()['events'][0]):
        assert tuple(event[k] for k in keys) == expected
        assert event['verified'] == expected[-1]
        assert event['revenue_forecast_status'] == ('unverified' if rev_source == 'import' else 'ok')
        assert (event['eps_actual'], event['revenue_actual'], event['revenue_forecast']) == (2.2, 110, 100)
    raw = db.execute(text('SELECT revenue_forecast_status FROM earnings_events WHERE id = :id'), {'id': eid}).scalar_one()
    assert raw == 'ok'  # read-time normalization leaves historical data intact
    assert db.execute(text('SELECT detail FROM earnings_results WHERE event_id = :id'), {'id': eid}).scalar_one() == detail


def test_upcoming_import_forecast_is_unverified(client, db):
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:id, 'NVDA')"), {'id': uuid.uuid4()})
    db.execute(text(
        "INSERT INTO earnings_events (ticker, quarter, report_date, eps_forecast, revenue_forecast, "
        "revenue_forecast_source, revenue_forecast_status, source) "
        "VALUES ('NVDA', '2026Q3', :day, 2, 100, 'import', 'ok', 'import')"),
        {'day': date.today() + timedelta(days=5)})
    db.commit()
    overview = client.get('/api/v1/research/earnings/overview').json()
    stock = client.get('/api/v1/research/earnings/stock/NVDA').json()
    for event in (overview['upcoming'][0], overview['next'], stock['events'][0]):
        assert event['revenue_forecast_status'] == 'unverified'
        assert not event['revenue_forecast_verified'] and not event['eps_forecast_verified']


def test_llm_catchup_retries_failed_exhibit_and_late_points(db):
    """B7 감사 G8 — 실패한 구조화는 1시간 뒤 다시(3번까지), 보도자료보다 늦게 생긴 관전포인트는 판정을 다시 넣는다."""
    from datetime import datetime, timezone
    from app.core.sec_sync import llm_catchup
    now = datetime.now(timezone.utc)
    eid = db.execute(text("INSERT INTO earnings_events (ticker, quarter, report_date, timing, source) "
                          "VALUES ('NVDA', '2026Q2', :d, 'AMC', 'nasdaq') RETURNING id"),
                     {"d": now.date() - timedelta(days=2)}).scalar()
    db.execute(text("INSERT INTO earnings_results (event_id, filing_url, filing_accession, source) "
                    "VALUES (:e, 'u', 'acc-1', 'sec')"), {"e": eid})
    job = ("INSERT INTO jobs (id, job_type, status, queue, payload, created_at) VALUES "
           "(:i, :t, :s, 'llm', CAST(:p AS JSONB), :c)")
    db.execute(text(job), {"i": uuid.uuid4(), "t": "LLM_EXHIBIT", "s": "FAILED",
                           "p": json.dumps({"event_id": eid}), "c": now - timedelta(minutes=10)})
    db.commit()
    assert llm_catchup(db, now) == []                                            # 방금 실패 — 1시간 기다린다
    assert llm_catchup(db, now + timedelta(hours=2)) == [("LLM_EXHIBIT", {"event_id": eid, "accession": "acc-1"})]
    for k in range(2):
        db.execute(text(job), {"i": uuid.uuid4(), "t": "LLM_EXHIBIT", "s": "FAILED",
                               "p": json.dumps({"event_id": eid}), "c": now - timedelta(hours=3 + k)})
    db.commit()
    assert llm_catchup(db, now + timedelta(hours=2)) == []                       # 실패 3번 — 그만
    # 구조화가 끝났고 판정도 했는데, 그 뒤에 관전포인트가 생겼다 → 판정을 다시
    db.execute(text("UPDATE earnings_results SET detail = '{\"exhibit_parsed\": true}' WHERE event_id = :e"), {"e": eid})
    db.execute(text(job), {"i": uuid.uuid4(), "t": "LLM_JUDGE", "s": "SUCCESS",
                           "p": json.dumps({"event_id": eid}), "c": now - timedelta(hours=5)})
    db.commit()
    assert llm_catchup(db, now) == []                                            # 결과 빈 관전포인트 없음
    db.execute(text("INSERT INTO earnings_watchpoints (ticker, quarter, rank, point, source, created_at) "
                    "VALUES ('NVDA', '2026Q2', 1, '데이터센터', 'llm', :c)"), {"c": now - timedelta(hours=4)})
    db.commit()
    assert llm_catchup(db, now) == [("LLM_JUDGE", {"event_id": eid})]
    db.execute(text(job), {"i": uuid.uuid4(), "t": "LLM_JUDGE", "s": "SUCCESS",
                           "p": json.dumps({"event_id": eid}), "c": now - timedelta(hours=3)})
    db.commit()
    assert llm_catchup(db, now) == []                                            # 관전포인트 뒤 판정 있음 — 끝
