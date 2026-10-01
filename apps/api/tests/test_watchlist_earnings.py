"""관심종목을 추가하면 실적 일정을 그 자리에서 다시 받게 한다 (2026-10-01 MU 누락)."""
from sqlalchemy import select

from app.models import Job


def _calendar_jobs(db):
    return db.execute(
        select(Job).where(Job.job_type == "EARNINGS_CALENDAR", Job.status.in_(("PENDING", "RUNNING")))
    ).scalars().all()


def test_adding_watchlist_enqueues_calendar_once(client, db):
    assert _calendar_jobs(db) == []

    assert client.post("/api/v1/watchlist", json={"ticker": "MU", "asset_name": "마이크론"}).status_code == 201
    jobs = _calendar_jobs(db)
    assert len(jobs) == 1
    assert jobs[0].payload == {"reason": "watchlist_added"}

    # 대기 중인 일정 작업이 있으면 또 넣지 않는다 — 연달아 추가해도 한 번.
    assert client.post("/api/v1/watchlist", json={"ticker": "SPCX", "asset_name": "SPCX"}).status_code == 201
    assert len(_calendar_jobs(db)) == 1
