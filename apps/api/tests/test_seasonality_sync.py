"""계절성 C3 — 따라잡기 판정과 원천을 이은 수익률."""
import math
from datetime import datetime, timedelta, timezone

from app.core import seasonality_sync as ss
from app.models import Job, MonthlyClose, SeasonalitySeries


def test_last_completed_month_uses_kst():
    # UTC 9/30 16:00 = KST 10/1 01:00 → 지난달은 9월
    assert ss.last_completed_month(datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)) == "2026-09"
    assert ss.last_completed_month(datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)) == "2026-08"


def test_chained_returns_switch_source_at_cutover_without_level_splice():
    rows = [
        ("sector", "IT", "2026-06", 100.0, "bloomberg"),
        ("sector", "IT", "2026-07", 110.0, "bloomberg"),
        ("sector", "IT", "2026-08", 121.0, "bloomberg"),
        # XLK 는 수준이 전혀 다르다 — 수익률만 잇는다
        ("sector", "IT", "2026-07", 20.0, "yahoo"),
        ("sector", "IT", "2026-08", 25.0, "yahoo"),
        ("sector", "IT", "2026-09", 30.0, "yahoo"),
    ]
    r = ss.chained_returns(rows)["sector"]["IT"]
    assert math.isclose(r["2026-08-01"], 0.10)          # 전환 달까지는 블룸버그(121/110)
    assert math.isclose(r["2026-09-01"], 0.20)          # 다음 달은 Yahoo 끼리(30/25)
    assert list(r.index.strftime("%Y-%m")) == ["2026-06", "2026-07", "2026-08", "2026-09"]


def _seed(db, with_yahoo_aug: bool):
    db.add(SeasonalitySeries(key="SPX", label="S&P", grp="index", yahoo_symbol="^GSPC"))
    db.add(SeasonalitySeries(key="ChiNext", label="창업판", grp="index", yahoo_symbol=None,
                             continuation="frozen"))
    db.commit()  # 관계 선언이 없어 ORM 이 순서를 모른다 — 부모(시계열)를 먼저
    db.add(MonthlyClose(series="SPX", month="2026-08", close=1, source="bloomberg"))
    if with_yahoo_aug:
        db.add(MonthlyClose(series="SPX", month="2026-08", close=1, source="yahoo"))
    db.commit()


NOW = datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)


def test_enqueue_when_last_month_missing_and_not_twice(db):
    _seed(db, with_yahoo_aug=False)
    job = ss.maybe_enqueue(db, NOW)
    assert job is not None and job.queue == "sec_crawl" and job.payload == {"target": "2026-08"}
    assert ss.maybe_enqueue(db, NOW) is None                      # 이미 PENDING


def test_no_enqueue_when_filled_or_recently_tried(db):
    _seed(db, with_yahoo_aug=True)
    assert ss.maybe_enqueue(db, NOW) is None                      # 창업판(동결)은 판정에서 빠진다


def test_backoff_after_recent_failure(db):
    _seed(db, with_yahoo_aug=False)
    db.add(Job(job_type=ss.JOB_TYPE, queue="sec_crawl", status="FAILED",
               created_at=NOW - timedelta(hours=1)))
    db.commit()
    assert ss.maybe_enqueue(db, NOW) is None                      # 6시간 안에는 다시 두드리지 않는다
    assert ss.maybe_enqueue(db, NOW + timedelta(hours=6)) is not None
