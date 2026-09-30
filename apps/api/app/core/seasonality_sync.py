"""계절성 월말 종가 따라잡기 + 원천을 이은 수익률 (계획 C3).

[따라잡기] `daily_sync` 와 같은 방식이다 — 정각 타이머가 아니라 "지난달 값이 비어
있으면 지금 넣는다". 맥이 월말에 자고 있었어도 깨는 순간 따라잡는다.
  - 판정: Yahoo 로 잇는 시계열 중 하나라도 **지난달(KST 기준 완결된 달)** 의
    source='yahoo' 종가가 없으면 SEASONALITY_APPEND 작업(sec_crawl 큐)을 넣는다.
  - 이미 PENDING/RUNNING 이면 넣지 않는다. 최근 6시간 안에 넣은 적이 있으면 넣지
    않는다 — Yahoo 가 막혀 있을 때 30분마다 두드리지 않게(차단 신호는 /data-operations).

[이은 수익률] 수익률은 **같은 원천 안에서만** 낸다(0020·0021). 블룸버그 마지막 달
(전환 달)까지는 블룸버그 종가끼리, 그 다음 달부터는 Yahoo 종가끼리 — 전환 달의 Yahoo
종가가 첫 Yahoo 수익률의 기준이다. 가격 수준을 서로 잇지 않는다(XLK≠S5INFT, ASHR≠CSI300).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select, text

from app.core import seasonality as sea
from app.db.session import SessionLocal
from app.models import Job

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
JOB_TYPE = "SEASONALITY_APPEND"
QUEUE = "sec_crawl"
CHECK_INTERVAL_SECONDS = 30 * 60
RETRY_AFTER = timedelta(hours=6)


def last_completed_month(now: datetime | None = None) -> str:
    kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    first = kst.replace(day=1)
    prev = first - timedelta(days=1)
    return prev.strftime("%Y-%m")


def needs_append(db, now: datetime | None = None) -> bool:
    """이어 붙일 시계열 중 지난달 Yahoo 값이 빠진 게 있나."""
    target = last_completed_month(now)
    missing = db.execute(
        text(
            "SELECT count(*) FROM seasonality_series s WHERE s.yahoo_symbol IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM monthly_closes c WHERE c.series = s.key "
            "AND c.source = 'yahoo' AND c.month = :m)"
        ),
        {"m": target},
    ).scalar()
    return bool(missing)


def maybe_enqueue(db, now: datetime | None = None) -> Job | None:
    now = now or datetime.now(timezone.utc)
    if not needs_append(db, now):
        return None
    recent = db.execute(
        select(Job).where(Job.job_type == JOB_TYPE).order_by(Job.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if recent is not None:
        if recent.status in ("PENDING", "RUNNING"):
            return None
        if now - recent.created_at < RETRY_AFTER:
            return None
    job = Job(job_type=JOB_TYPE, queue=QUEUE, payload={"target": last_completed_month(now)})
    db.add(job)
    db.commit()
    return job


async def seasonality_sync_loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                job = maybe_enqueue(db)
                if job is not None:
                    logger.info("seasonality: enqueued %s for %s", job.id, job.payload)
        except Exception:
            logger.exception("seasonality sync check failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def chained_returns(rows) -> dict[str, pd.DataFrame]:
    """[(grp, series, month, close, source)] → {grp: 월 수익률 표}. 원천 안에서만 수익률을 낸다."""
    by: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    for grp, series, month, close, source in rows:
        by.setdefault((grp, series), {}).setdefault(source, {})[month] = float(close)

    out: dict[str, dict[str, pd.Series]] = {}
    for (grp, series), sources in by.items():
        bbg = sources.get("bloomberg", {})
        cutover = max(bbg) if bbg else None
        parts = []
        if bbg:
            parts.append(sea.monthly_returns({series: bbg})[series])
        yahoo = sources.get("yahoo", {})
        if yahoo:
            yr = sea.monthly_returns({series: yahoo})[series]
            if cutover is not None:
                yr = yr[yr.index > pd.Timestamp(int(cutover[:4]), int(cutover[5:7]), 1)]
            parts.append(yr)
        if parts:
            s = pd.concat(parts)
            s = s[~s.index.duplicated(keep="first")].sort_index()
            out.setdefault(grp, {})[series] = s
    frames = {}
    for grp, cols in out.items():
        df = pd.DataFrame(cols).sort_index()
        # 합친 뒤에도 달력에 빈틈이 없게(한 시계열만 끝난 달이 있어도 행은 있다).
        full = pd.date_range(df.index[0], df.index[-1], freq="MS")
        frames[grp] = df.reindex(full)
    return frames
