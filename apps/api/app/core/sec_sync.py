"""SEC 공시 따라잡기 — 13F · Form 4 · 13D/G 수집 작업을 주기표대로 넣는다 (계획 A3b).

`seasonality_sync` 와 같은 방식이다 — 정각 타이머가 아니라 "마지막으로 넣은 지 주기가 지났으면
지금 넣는다". 맥이 자고 있었어도 깨는 순간 따라잡는다(수집기는 DB 에 없는 접수번호만 받는다).

주기(계획 §A 데이터·파이프라인):
  - Form 4: **미국 영업일 1시간마다**(뉴욕 시각 월~금). 주말엔 EDGAR 가 접수하지 않는다 — 넣지 않는다.
  - 13D/13G: 12시간마다(하루 2회).
  - 13F: **시즌(분기말 +30~50일) 매일**, 그 밖엔 주 1회. 마감이 분기말 +45일이다.
  - 거장 백필(A7): 명단에 pending 이 있는데 작업이 없으면 바로.
  - 관전포인트(B5): 발표 D-3 안 · 관전포인트 없음 → 07:30 KST 이후 하루 한 번 LLM_WATCHPOINTS(llm 큐).
  - 실적 결과(B4): 발표 구간이 끝난 내 종목에 8-K · 반응이 비었으면 15분마다(장후 17:40 · 장전 08:40 ET).
  - LLM 따라잡기(B7 G8): 실패한 보도자료 구조화 · 늦게 생긴 관전포인트의 결과 판정 — 발표당 실패 3번까지, 1시간 간격.
  - 실적 캘린더(B3a): 매일 07:10 KST 이후 한 번(맥이 잤으면 깨어나서). 매출 컨센(B3b, 화면 있는 크롬): 07:20.
  - CUSIP 해소(A4): 하루 1회 — 새 13F 보유의 새 CUSIP 만 OpenFIGI 에 묻는다(없으면 바로 끝).
실패한 작업도 "넣은 것"으로 센다 — SEC 가 막혀 있을 때 5분마다 두드리지 않게(차단은 /data-operations).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models import Job

logger = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
QUEUE = "sec_crawl"
CHECK_INTERVAL_SECONDS = 5 * 60
JOB_TYPES = ("SEC_FORM4", "SEC_13DG", "SEC_13F", "CUSIP_RESOLVE", "EARNINGS_CALENDAR", "EARNINGS_REVENUE")
KST = ZoneInfo("Asia/Seoul")
EARNINGS_AT = (7, 10)          # 매일 07:10 KST 이후 한 번(계획 B 데이터·파이프라인 표)
# 정해진 시각형 작업 — Investing.com 매출 컨센(B3b)은 Nasdaq 캘린더(07:10) 뒤에. 막히면 그날은 "수집 실패", 다음 날 다시.
DAILY_SLOTS = {"EARNINGS_CALENDAR": EARNINGS_AT, "EARNINGS_REVENUE": (7, 20)}


def in_13f_season(d: date) -> bool:
    """직전 분기말 +30~50일 안인가."""
    last_qe = date(d.year, (d.month - 1) // 3 * 3 + 1, 1) - timedelta(days=1)
    return 30 <= (d - last_qe).days <= 50


def interval_for(job_type: str, now: datetime) -> timedelta | None:
    """지금 이 작업의 주기. None 이면 지금은 넣지 않는다."""
    ny = now.astimezone(NY)
    if job_type == "SEC_FORM4":
        return timedelta(hours=1) if ny.weekday() < 5 else None
    if job_type == "SEC_13DG":
        return timedelta(hours=12)
    if job_type == "SEC_13F":
        return timedelta(days=1) if in_13f_season(ny.date()) else timedelta(days=7)
    if job_type == "CUSIP_RESOLVE":
        return timedelta(days=1)
    raise ValueError(job_type)


def last_slot(now: datetime, hm: tuple[int, int] = EARNINGS_AT) -> datetime:
    """가장 최근에 지난 '매일 hh:mm KST' 시각."""
    k = now.astimezone(KST)
    slot = k.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    return slot if k >= slot else slot - timedelta(days=1)


def due(job_type: str, last: Job | None, now: datetime) -> bool:
    if job_type in DAILY_SLOTS:
        # 정해진 시각형 — 마지막 hh:mm 이후로 넣은 적이 없으면(진행 중이 아니면) 지금
        return last is None or (last.status not in ("PENDING", "RUNNING")
                                and last.created_at < last_slot(now, DAILY_SLOTS[job_type]))
    every = interval_for(job_type, now)
    if every is None:
        return False
    if last is None:
        return True
    if last.status in ("PENDING", "RUNNING"):
        return False
    # 몇 초 일찍 끝난 주기도 이번 확인에서 잡히게(5분마다 확인 — 1시간 주기가 1시간 5분이 되지 않게).
    return now - last.created_at >= every - timedelta(seconds=CHECK_INTERVAL_SECONDS)


RESULT_EVERY_MIN = 15
# 결과 수집 시작 시각(ET) — 장후 17:40 · 장전 08:40 · 시각 모름은 다음 날 09:00 (계획 데이터·파이프라인 표)
_READY_AT = {"AMC": (0, 17, 40), "BMO": (0, 8, 40)}


def result_ready_at(report_date: date, timing: str | None) -> datetime:
    off, h, m = _READY_AT.get(timing or "", (1, 9, 0))
    return datetime.combine(report_date + timedelta(days=off), datetime.min.time(), tzinfo=NY).replace(hour=h, minute=m)


def results_ready(db, now: datetime) -> bool:
    rows = db.execute(text(
        "SELECT e.report_date, e.timing FROM earnings_events e LEFT JOIN earnings_results r ON r.event_id = e.id "
        "WHERE e.ticker IN (SELECT upper(a.ticker) FROM current_positions p JOIN assets a ON a.id = p.asset_id "
        "  WHERE p.quantity > 0 AND a.country = 'US' UNION SELECT upper(ticker) FROM watchlist_items) "
        "AND e.report_date BETWEEN :lo AND :today "
        "AND ((r.filing_url IS NULL AND COALESCE(r.detail->>'filing_missing', 'false') <> 'true') "
        "  OR (r.reaction_pct IS NULL AND e.timing IN ('AMC', 'BMO') "
        "      AND COALESCE(r.detail->>'reaction_missing', 'false') <> 'true'))"),
        {"lo": now.date() - timedelta(days=30), "today": now.astimezone(NY).date()}).all()
    return any(now >= result_ready_at(d, t) for d, t in rows)


WATCHPOINTS_AT = (7, 30)      # 발표 D-3 07:30 KST (계획 데이터·파이프라인 표)
WATCHPOINTS_AHEAD_DAYS = 3


def watchpoints_due(db, now: datetime) -> list[tuple[str, str]]:
    """[(티커, 분기)] — D-3 안에 발표하는데 관전포인트가 없고, 오늘 07:30 KST 이후로 생성 작업을 넣은 적 없는 것."""
    slot = last_slot(now, WATCHPOINTS_AT)
    today = now.astimezone(KST).date()
    rows = db.execute(text(
        "SELECT e.ticker, e.quarter FROM earnings_events e "
        "WHERE e.ticker IN (SELECT upper(a.ticker) FROM current_positions p JOIN assets a ON a.id = p.asset_id "
        "  WHERE p.quantity > 0 AND a.country = 'US' UNION SELECT upper(ticker) FROM watchlist_items) "
        "AND e.report_date BETWEEN :d AND :hi "
        "AND NOT EXISTS (SELECT 1 FROM earnings_watchpoints w WHERE w.ticker = e.ticker AND w.quarter = e.quarter) "
        "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.job_type = 'LLM_WATCHPOINTS' "
        "  AND j.payload->>'ticker' = e.ticker AND j.payload->>'quarter' = e.quarter "
        "  AND (j.status IN ('PENDING', 'RUNNING') OR j.created_at >= :slot))"),
        {"d": today, "hi": today + timedelta(days=WATCHPOINTS_AHEAD_DAYS), "slot": slot}).all()
    return [(t, q) for t, q in rows]


LLM_RETRY_MAX = 3            # 같은 발표의 LLM 단계는 실패 3번까지만 다시 넣는다(하루 상한 40 을 한 종목이 먹지 않게)
LLM_RETRY_GAP = timedelta(hours=1)


def llm_catchup(db, now: datetime) -> list[tuple[str, dict]]:
    """놓친 LLM 단계를 다시 넣는다 (계획 B7 감사 G8 — 원본 pending-result 재처리 대신).

    - LLM_EXHIBIT: 8-K 는 찾았는데(`filing_url`) 구조화가 안 끝난 것(`exhibit_parsed` 없음) — 앞 작업이 실패했거나
      넣기 전에 죽은 경우. 대기·실행 중이 없고, 실패 3번 미만, 마지막 시도 1시간 뒤.
    - LLM_JUDGE: 구조화는 끝났는데 결과 빈 관전포인트가 있고, **그 관전포인트가 생긴 뒤로** 판정 작업이 없던 것
      (관전포인트가 보도자료보다 늦게 생긴 경우 — `llm_exhibit` 은 그때 한 번만 판정을 넣는다). 같은 재시도 규칙.
    """
    base = ("SELECT e.id, r.filing_accession FROM earnings_events e JOIN earnings_results r ON r.event_id = e.id "
            "WHERE e.report_date >= :lo AND r.filing_url IS NOT NULL AND {cond} "
            "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.job_type = :jt AND j.payload->>'event_id' = e.id::text "
            "  AND (j.status IN ('PENDING', 'RUNNING') OR j.created_at > :cut {since})) "
            "AND (SELECT count(*) FROM jobs j WHERE j.job_type = :jt AND j.payload->>'event_id' = e.id::text "
            "  AND j.status = 'FAILED') < :cap")
    args = {"lo": now.date() - timedelta(days=30), "cut": now - LLM_RETRY_GAP, "cap": LLM_RETRY_MAX}
    out = []
    for eid, acc in db.execute(text(base.format(
            cond="COALESCE(r.detail->>'exhibit_parsed', 'false') <> 'true'", since="")),
            {**args, "jt": "LLM_EXHIBIT"}).all():
        out.append(("LLM_EXHIBIT", {"event_id": eid, "accession": acc}))
    points = ("SELECT max(w.created_at) FROM earnings_watchpoints w WHERE w.ticker = e.ticker "
              "AND w.quarter = e.quarter AND w.point IS NOT NULL")
    for eid, _ in db.execute(text(base.format(
            cond="COALESCE(r.detail->>'exhibit_parsed', 'false') = 'true' AND EXISTS (SELECT 1 FROM "
                 "earnings_watchpoints w WHERE w.ticker = e.ticker AND w.quarter = e.quarter "
                 "AND w.point IS NOT NULL AND w.result IS NULL)",
            since=f"OR (j.status = 'SUCCESS' AND j.created_at >= ({points}))")),
            {**args, "jt": "LLM_JUDGE"}).all():
        out.append(("LLM_JUDGE", {"event_id": eid}))
    return out


def maybe_enqueue(db, now: datetime | None = None) -> list[Job]:
    now = now or datetime.now(timezone.utc)
    added = []
    for job_type in JOB_TYPES:
        last = db.execute(
            select(Job).where(Job.job_type == job_type).order_by(Job.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        if due(job_type, last, now):
            job = Job(job_type=job_type, queue=QUEUE, payload={})
            db.add(job)
            added.append(job)
    # B4 — 발표 구간이 끝난 내 종목 중 8-K · 반응이 빈 게 있으면 15분마다(찾거나 기한이 지날 때까지)
    if results_ready(db, now):
        last = db.execute(select(Job).where(Job.job_type == "EARNINGS_RESULT")
                          .order_by(Job.created_at.desc()).limit(1)).scalar_one_or_none()
        if last is None or (last.status not in ("PENDING", "RUNNING")
                            and now - last.created_at >= timedelta(minutes=RESULT_EVERY_MIN)):
            job = Job(job_type="EARNINGS_RESULT", queue=QUEUE, payload={})
            db.add(job)
            added.append(job)
    # B5 — 발표 D-3 이내인데 관전포인트가 없는 내 종목 → 07:30 KST 이후 하루 한 번 생성
    for ticker, quarter in watchpoints_due(db, now):
        job = Job(job_type="LLM_WATCHPOINTS", queue="llm", payload={"ticker": ticker, "quarter": quarter})
        db.add(job)
        added.append(job)
    # B7 감사 G8 — 실패했거나 순서가 어긋나 빠진 보도자료 구조화 · 결과 판정을 다시 넣는다
    for job_type, payload in llm_catchup(db, now):
        job = Job(job_type=job_type, queue="llm", payload=payload)
        db.add(job)
        added.append(job)
    # A7 — 명단에 백필 대기(pending) 거장이 있는데 작업이 없으면(추가 직후 API 가 죽었다든지) 넣는다.
    pending = db.execute(text(
        "SELECT count(*) FROM guru_roster WHERE kind = 'guru' AND active AND backfill_status = 'pending'")).scalar()
    queued = db.execute(text(
        "SELECT count(*) FROM jobs WHERE job_type = 'SEC_13F_BACKFILL' AND status IN ('PENDING', 'RUNNING')")).scalar()
    if pending and not queued:
        job = Job(job_type="SEC_13F_BACKFILL", queue=QUEUE, payload={})
        db.add(job)
        added.append(job)
    if added:
        db.commit()
    return added


async def sec_sync_loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                for job in maybe_enqueue(db):
                    logger.info("sec: enqueued %s %s", job.job_type, job.id)
        except Exception:
            logger.exception("sec sync check failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
