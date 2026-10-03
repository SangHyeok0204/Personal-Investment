"""계획 A3b — SEC 수집 주기 판정."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from app.core.sec_sync import due, in_13f_season, interval_for

UTC = timezone.utc


def test_13f_season_windows():
    assert not in_13f_season(date(2026, 10, 29))      # 9/30 +29일
    assert in_13f_season(date(2026, 10, 30))          # +30
    assert in_13f_season(date(2026, 11, 14))          # +45 마감
    assert in_13f_season(date(2026, 11, 19))          # +50
    assert not in_13f_season(date(2026, 11, 20))
    assert in_13f_season(date(2027, 2, 14))           # 12/31 +45 — 해를 넘긴다
    assert in_13f_season(date(2026, 5, 15))           # 3/31 +45
    assert not in_13f_season(date(2026, 9, 26))


def test_intervals():
    fri = datetime(2026, 9, 25, 15, tzinfo=UTC)       # 뉴욕 금 11시
    sat = datetime(2026, 9, 26, 15, tzinfo=UTC)
    assert interval_for("SEC_FORM4", fri) == timedelta(hours=1)
    assert interval_for("SEC_FORM4", sat) is None     # 주말엔 넣지 않는다
    assert interval_for("SEC_13DG", sat) == timedelta(hours=12)
    assert interval_for("SEC_13F", sat) == timedelta(days=7)
    assert interval_for("CUSIP_RESOLVE", sat) == timedelta(days=1)
    assert interval_for("SEC_13F", datetime(2026, 11, 14, 15, tzinfo=UTC)) == timedelta(days=1)


def test_due():
    now = datetime(2026, 9, 25, 15, tzinfo=UTC)
    job = lambda status, ago: SimpleNamespace(status=status, created_at=now - ago)  # noqa: E731
    assert due("SEC_FORM4", None, now)
    assert not due("SEC_FORM4", job("RUNNING", timedelta(hours=5)), now)       # 진행 중이면 안 넣는다
    assert not due("SEC_FORM4", job("SUCCEEDED", timedelta(minutes=30)), now)
    assert due("SEC_FORM4", job("SUCCEEDED", timedelta(minutes=56)), now)       # 5분 확인 주기 여유
    assert not due("SEC_13DG", job("FAILED", timedelta(hours=2)), now)          # 실패도 주기를 지킨다
    assert not due("SEC_FORM4", None, datetime(2026, 9, 26, 15, tzinfo=UTC))    # 주말


def test_earnings_calendar_daily_slot():
    from app.core.sec_sync import last_slot
    kst = lambda h, m=0, d=27: datetime(2026, 9, d, h - 9 if h >= 9 else h + 15, m, tzinfo=UTC) if h >= 9 else \
        datetime(2026, 9, d - 1, h + 15, m, tzinfo=UTC)  # noqa: E731
    at_8 = kst(8)                                    # 09-27 08:00 KST
    assert last_slot(at_8).astimezone(timezone(timedelta(hours=9))).strftime("%m-%d %H:%M") == "09-27 07:10"
    at_6 = kst(6)                                    # 07:10 전 → 어제 슬롯
    assert last_slot(at_6).astimezone(timezone(timedelta(hours=9))).strftime("%m-%d %H:%M") == "09-26 07:10"
    job = lambda status, t: SimpleNamespace(status=status, created_at=t)  # noqa: E731
    assert due("EARNINGS_CALENDAR", None, at_8)
    assert due("EARNINGS_CALENDAR", job("SUCCESS", kst(6)), at_8)          # 오늘 07:10 전에 돈 것 → 다시
    assert not due("EARNINGS_CALENDAR", job("SUCCESS", kst(7, 30)), at_8)  # 오늘 07:10 뒤에 돌았음
    assert not due("EARNINGS_CALENDAR", job("RUNNING", kst(6)), at_8)


def test_earnings_revenue_slot_after_calendar():
    from app.core.sec_sync import DAILY_SLOTS
    assert DAILY_SLOTS["EARNINGS_REVENUE"] > DAILY_SLOTS["EARNINGS_CALENDAR"]
    at = datetime(2026, 9, 27, 22, 15, tzinfo=UTC)          # 09-28 07:15 KST — 캘린더는 됐고 매출은 아직
    job = lambda t: SimpleNamespace(status="SUCCESS", created_at=t)  # noqa: E731
    yday = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    assert due("EARNINGS_CALENDAR", job(yday), at) and not due("EARNINGS_REVENUE", job(yday), at)


def test_result_ready_at():
    from app.core.sec_sync import result_ready_at
    ny = lambda dt: dt.astimezone(ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")  # noqa: E731
    assert ny(result_ready_at(date(2026, 8, 26), "AMC")) == "08-26 17:40"
    assert ny(result_ready_at(date(2026, 8, 26), "BMO")) == "08-26 08:40"
    assert ny(result_ready_at(date(2026, 8, 26), None)) == "08-27 09:00"


def test_llm_catchup_skips_escalated_event(db, tmp_path, monkeypatch):
    """하네스 L1 — 수리 재시도까지 실패해 에스컬레이션 패킷이 생긴 발표는 다시 넣지 않는다(손으로 다시 넣으면 재개)."""
    import json
    import os
    import uuid

    from sqlalchemy import text

    from app.core import sec_sync
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    now = datetime.now(UTC)
    eid = db.execute(text("INSERT INTO earnings_events (ticker, quarter, report_date, timing, source) "
                          "VALUES ('NVDA', '2026Q2', :d, 'AMC', 'nasdaq') RETURNING id"),
                     {"d": now.date() - timedelta(days=2)}).scalar()
    db.execute(text("INSERT INTO earnings_results (event_id, filing_url, filing_accession, source) "
                    "VALUES (:e, 'u', 'acc-1', 'sec')"), {"e": eid})
    job = ("INSERT INTO jobs (id, job_type, status, queue, payload, created_at) VALUES "
           "(:i, 'LLM_EXHIBIT', 'FAILED', 'llm', CAST(:p AS JSONB), :c)")
    db.execute(text(job), {"i": uuid.uuid4(), "p": json.dumps({"event_id": eid}), "c": now - timedelta(hours=3)})
    db.commit()
    later = now + timedelta(hours=2)
    assert sec_sync.llm_catchup(db, later) == [("LLM_EXHIBIT", {"event_id": eid, "accession": "acc-1"})]

    esc = tmp_path / "llm" / "escalations"
    esc.mkdir(parents=True)
    packet = esc / f"{now:%Y-%m-%d}-LLM_EXHIBIT-{eid}.json"
    packet.write_text("{}")
    assert sec_sync.escalated(db, "LLM_EXHIBIT", eid)
    assert sec_sync.llm_catchup(db, later) == []                       # 패킷이 마지막 시도보다 새것 — 건너뜀
    # 다른 발표·다른 단계의 패킷은 영향 없음
    assert not sec_sync.escalated(db, "LLM_JUDGE", eid)
    # 사람이 손으로 다시 넣으면(패킷보다 새 시도) 그 뒤 실패는 다시 따라잡는다
    old = (now - timedelta(hours=4)).timestamp()
    os.utime(packet, (old, old))
    assert not sec_sync.escalated(db, "LLM_EXHIBIT", eid)
    assert sec_sync.llm_catchup(db, later) == [("LLM_EXHIBIT", {"event_id": eid, "accession": "acc-1"})]
