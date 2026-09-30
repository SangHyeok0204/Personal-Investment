"""계획 A7 — 거장 추가: EDGAR 검색 파싱 · 명단 추가/재활성 · 백필 작업 예약 · 따라잡기."""
from datetime import datetime, timezone

from sqlalchemy import text

from app.core import sec_sync
from app.core.sec_search import parse_search

SINGLE = '<span class="companyName">GREENLIGHT CAPITAL INC <acronym title="Central Index Key">CIK</acronym>' \
         '#: <a href="/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001079114&amp;owner=include">0001079114</a>'
MULTI = ('<tr><td><a href="/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001336528&amp;type=13F-HR">0001336528</a>'
         '</td>\n<td scope="row">Pershing Square Capital Management, L.P.</td></tr>'
         '<tr><td><a href="/cgi-bin/browse-edgar?action=getcompany&amp;CIK=1234&amp;type=13F-HR">0000001234</a>'
         '</td><td>Pershing &amp; Co</td></tr>')


def test_parse_search_single_and_multi():
    assert parse_search(SINGLE) == [{"cik": "0001079114", "name": "GREENLIGHT CAPITAL INC"}]
    assert parse_search(MULTI) == [{"cik": "0001336528", "name": "Pershing Square Capital Management, L.P."},
                                   {"cik": "0000001234", "name": "Pershing & Co"}]
    assert parse_search("<html>No matching companies</html>") == []


def _jobs(db):
    return db.execute(text("SELECT job_type, payload FROM jobs WHERE job_type = 'SEC_13F_BACKFILL'")).all()


def test_add_new_guru_queues_backfill(client, db):
    r = client.post("/api/v1/research/guru/roster",
                    json={"cik": "1079114", "filer_name": "GREENLIGHT CAPITAL INC", "guru_name": "David Einhorn"})
    assert r.status_code == 201
    body = r.json()
    assert body["cik"] == "0001079114" and body["backfill_status"] == "pending" and body["kind"] == "guru"
    assert [j.payload for j in _jobs(db)] == [{"cik": "0001079114"}]
    assert client.post("/api/v1/research/guru/roster",
                       json={"cik": "0001079114", "filer_name": "X"}).status_code == 409


def test_promote_index_and_toggle_active(client, db):
    db.execute(text("INSERT INTO guru_roster (cik, firm, filer_name, kind, active, backfill_status) "
                    "VALUES ('0000000042', 'Quant', 'QUANT LLC', 'index', false, 'pending')"))
    db.commit()
    r = client.post("/api/v1/research/guru/roster", json={"cik": "42", "filer_name": "QUANT LLC", "guru_name": "Q"})
    assert r.status_code == 201 and r.json()["kind"] == "guru" and r.json()["active"] is True
    assert len(_jobs(db)) == 1                                   # 백필 안 된 곳이라 백필도
    off = client.patch("/api/v1/research/guru/roster/0000000042", json={"active": False}).json()
    assert off["active"] is False
    assert client.patch("/api/v1/research/guru/roster/9", json={"active": True}).status_code == 404


def test_sync_requeues_orphan_pending(db):
    db.execute(text("INSERT INTO guru_roster (cik, firm, filer_name, kind, backfill_status) "
                    "VALUES ('0000000077', 'F', 'F', 'guru', 'pending')"))
    db.commit()
    now = datetime(2026, 9, 26, 15, tzinfo=timezone.utc)   # 토요일 — Form 4 는 안 넣는다
    types = [j.job_type for j in sec_sync.maybe_enqueue(db, now)]
    assert "SEC_13F_BACKFILL" in types
    again = [j.job_type for j in sec_sync.maybe_enqueue(db, now)]
    assert "SEC_13F_BACKFILL" not in again                  # 이미 대기 중이면 또 넣지 않는다
